# coverage_tool.py

import ast
import importlib.abc
import importlib.util
import os
import pathlib
import sys
import traceback
import types
import unittest
import collections  # Added for defaultdict
from typing import Dict, List, Optional, Set, Tuple

# --- Configuration ---
# Directories relative to the script's execution location
TEST_DIR: str = "./tests"
TEST_FILE_PATTERN: str = "test_*.py"
TARGET_FILE_SUFFIX: str = ".py"

# Directories or files to exclude from coverage analysis
EXCLUDE_DIRS: Set[str] = {
    "venv",
    ".venv",  # Common virtualenv name
    "tests",
    "__pycache__",
    ".git",
    ".hg",
    ".svn",
    ".tox",
    ".nox",
    ".eggs",
    "build",
    "dist",
    "docs",
    "examples",
    ".mypy_cache",
    ".pytest_cache",
    "node_modules",
    # Add potentially conflicting names if they are never source dirs
    "site-packages",
}
EXCLUDE_FILENAMES: Set[str] = {
    "setup.py",
    "conftest.py",  # Common pytest configuration file
    "coverage_tool.py",  # Exclude the tool itself
}

# Get the absolute path of the directory where this script resides
# Used to ensure the tool's own directory isn't processed if run from elsewhere
_TOOL_SCRIPT_PATH: pathlib.Path = pathlib.Path(__file__).resolve()
_CURRENT_WORKING_DIR: pathlib.Path = pathlib.Path(".").resolve()


# --- Coverage Tracking ---


class CoverageTracker:
    """
    Tracks executed lines during code execution.

    Stores hit lines as tuples of (resolved_filepath, lineno).
    """

    def __init__(self) -> None:
        """Initializes the CoverageTracker."""
        # Using resolved paths ensures consistency regardless of how the file
        # was imported or accessed.
        self.hits: Set[Tuple[str, int]] = set()

    def hit(self, filepath: str, lineno: int) -> None:
        """
        Records a line as executed. Called by instrumented code.

        Args:
            filepath: The path to the file where the line was executed.
                      This should typically be the value of `__file__`.
            lineno: The line number that was executed.
        """
        # Resolve the path to ensure consistency. This might be slightly
        # redundant if __file__ is already resolved, but guarantees it.
        try:
            resolved_path = str(pathlib.Path(filepath).resolve())
            self.hits.add((resolved_path, lineno))
        except OSError as e:
            # Handle cases where the path might be invalid (e.g., during cleanup)
            print(
                f"Warning: Could not resolve path '{filepath}' during hit: {e}",
                file=sys.stderr,
            )


# Global tracker instance accessible by instrumented code via injection.
# Using a double underscore prefix makes it less likely to clash with user code.
__coverage_tracker__: CoverageTracker = CoverageTracker()


# --- AST Helper ---


class ScopeFinder(ast.NodeVisitor):
    """
    Visits an AST to map line numbers to their containing scope name string
    (e.g., '[module level] / class MyClass / function my_method').

    Requires Python 3.8+ for accurate end_lineno on all node types.
    Without end_lineno, mapping might be less precise for multi-line statements.
    """

    def __init__(self):
        # Maps line number -> scope name string
        self.line_to_scope: Dict[int, str] = {}
        # Stack to keep track of the current scope hierarchy
        self._scope_stack: List[str] = []

    def _get_current_scope_name(self) -> str:
        """Returns the current scope name string."""
        return " / ".join(self._scope_stack) if self._scope_stack else "[unknown]"

    def visit(self, node: ast.AST):
        """Generic visit: map node's lines to current scope before specific visits."""
        # Map lines for the current node *before* potentially entering/leaving a scope
        if hasattr(node, "lineno"):
            current_scope = self._get_current_scope_name()
            start_line = node.lineno
            # Use end_lineno if available (Python 3.8+)
            end_line = getattr(node, "end_lineno", start_line)
            # Ensure end_line is not None, default to start_line if it is
            if end_line is None:
                end_line = start_line

            # Map all lines within this node's range to the current scope context.
            # Deeper scopes visited later will overwrite the mapping for their lines.
            for line_num in range(start_line, end_line + 1):
                self.line_to_scope[line_num] = current_scope

        # Continue traversal - specific visitors below handle scope stack changes
        super().visit(node)

    # Override scope-defining nodes to manage the stack

    def visit_Module(self, node: ast.Module):
        """Visit module, setting the base scope."""
        # Module node itself doesn't have line numbers in the same way statements do.
        # We rely on the generic visit mapping lines before we enter specific scopes.
        self._scope_stack.append("[module level]")
        self.generic_visit(node)  # Visit module body children
        self._scope_stack.pop()  # Pop module scope at the end

    def visit_FunctionDef(self, node: ast.FunctionDef):
        """Visit function, manage scope stack."""
        scope_id = f"function {node.name}"
        self._scope_stack.append(scope_id)
        # Let generic visit handle mapping lines for the function node itself first
        # Then visit children within the new scope context
        self.generic_visit(node)
        self._scope_stack.pop()  # Pop function scope after visiting children

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        """Visit async function, manage scope stack."""
        scope_id = f"async function {node.name}"
        self._scope_stack.append(scope_id)
        self.generic_visit(node)
        self._scope_stack.pop()

    def visit_ClassDef(self, node: ast.ClassDef):
        """Visit class, manage scope stack."""
        scope_id = f"class {node.name}"
        self._scope_stack.append(scope_id)
        self.generic_visit(node)  # Visit children (methods, etc.) within this new scope
        self._scope_stack.pop()  # Pop class scope


def _is_docstring_or_bare_constant(node: ast.AST) -> bool:
    """
    Checks if an AST node is an expression consisting solely of a constant
    string or bytes. This is typically a docstring or a module-level constant
    assignment without a variable.

    Args:
        node: The AST node to check.

    Returns:
        True if the node is a bare string/bytes constant expression, False otherwise.
    """
    return (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, (str, bytes))
    )


# --- AST Analysis: Find Executable Lines ---


class ExecutableLineCollector(ast.NodeVisitor):
    """
    Collects the line numbers of potentially executable statements in an AST.

    Excludes lines containing only docstrings or bare string/bytes constants.
    """

    def __init__(self) -> None:
        """Initializes the ExecutableLineCollector."""
        self.lines: Set[int] = set()

    def visit(self, node: ast.AST) -> None:
        """
        Visits an AST node, adding its line number to the set if executable.

        Args:
            node: The AST node to visit.
        """
        # We are interested in statements that have a line number.
        # AST nodes that are not statements (e.g., expressions, operators)
        # don't represent standalone executable lines in the way we track coverage.
        if isinstance(node, ast.stmt) and hasattr(node, "lineno"):
            # Exclude nodes that are just docstrings or bare constants
            if not _is_docstring_or_bare_constant(node):
                self.lines.add(node.lineno)

        # Continue traversing the AST
        self.generic_visit(node)


# --- AST Transformation: Instrument Code ---


class InstrumentationTransformer(ast.NodeTransformer):
    """
    Transforms an AST to insert coverage tracking calls before executable lines.
    """

    def __init__(self, filename: str) -> None:
        """
        Initializes the InstrumentationTransformer.

        Args:
            filename: The original path of the file being instrumented. This
                      will be embedded in the tracking calls. Should be resolved path.
        """
        self.filename: str = filename  # Expecting resolved path here
        # Tracks lines instrumented within the current list of statements being processed
        # to avoid inserting multiple trackers for the same line number if a single
        # statement spans multiple lines conceptually but resolves to one line number.
        self._instrumented_in_current_block: Set[int] = set()

    def _create_tracking_call(self, lineno: int) -> ast.Expr:
        """
        Creates the AST node for the coverage tracker call.

        Generates AST for: `__coverage_tracker__.hit(self.filename, lineno)`

        Args:
            lineno: The line number to be recorded.

        Returns:
            An ast.Expr node representing the tracking call.
        """
        return ast.Expr(
            value=ast.Call(
                func=ast.Attribute(
                    value=ast.Name(id="__coverage_tracker__", ctx=ast.Load()),
                    attr="hit",
                    ctx=ast.Load(),
                ),
                args=[
                    ast.Constant(value=self.filename),  # Pass the resolved path
                    ast.Constant(value=lineno),
                ],
                keywords=[],
            )
        )

    def _process_statement_list(self, body: List[ast.stmt]) -> List[ast.stmt]:
        """
        Processes a list of statements (like a function body or module body),
        inserting tracking calls before executable lines.

        Args:
            body: The list of statement nodes.

        Returns:
            A new list of statements with tracking calls inserted.
        """
        new_body: List[ast.stmt] = []
        # Reset tracking for this specific block/list of statements
        self._instrumented_in_current_block = set()

        for node in body:
            # Ensure node is a statement with a line number before processing
            if isinstance(node, ast.stmt) and hasattr(node, "lineno"):
                # Check if it's an executable line (not just a docstring)
                # and hasn't been instrumented in this block yet.
                if (
                    not _is_docstring_or_bare_constant(node)
                    and node.lineno not in self._instrumented_in_current_block
                ):
                    new_body.append(self._create_tracking_call(node.lineno))
                    self._instrumented_in_current_block.add(node.lineno)

            # Visit the original node itself to process nested structures
            # (like function defs, class defs, loops) using the transformer's logic.
            visited_node = self.visit(
                node
            )  # This calls the appropriate visit_... method

            # Add the (potentially transformed) original node
            # If visit returns None (e.g., for deleted nodes), skip.
            # If visit returns a list (e.g., for expanded constructs), extend.
            if visited_node:
                # Ensure we handle the case where visit returns a list (though unlikely for stmts)
                if isinstance(visited_node, list):
                    new_body.extend(visited_node)
                # If visit returns a single node (the common case)
                elif isinstance(visited_node, ast.AST):  # Check it's still an AST node
                    new_body.append(visited_node)  # type: ignore # AST node is expected here
                # else: Handle other potential return types if necessary
            # else: Node was removed by visit method

        return new_body

    # Override visit methods for nodes that contain lists of statements
    # Ensure they recursively call _process_statement_list or self.visit correctly

    def visit_Module(self, node: ast.Module) -> ast.Module:
        """Instruments the main body of a module."""
        # We need to handle the module body directly, then visit children
        # The default generic_visit might not handle module body list correctly
        node.body = self._process_statement_list(node.body)
        # No need to call generic_visit if we processed the body list
        return node

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.FunctionDef:
        """Instruments the body of a function."""
        outer_instrumented = self._instrumented_in_current_block
        # Process decorators first if they exist
        node.decorator_list = [self.visit(d) for d in node.decorator_list]
        # Process args if needed (usually not for line coverage)
        # Process return annotation if needed
        # Process the body
        node.body = self._process_statement_list(node.body)
        self._instrumented_in_current_block = outer_instrumented
        return node

    def visit_AsyncFunctionDef(
        self, node: ast.AsyncFunctionDef
    ) -> ast.AsyncFunctionDef:
        """Instruments the body of an async function."""
        outer_instrumented = self._instrumented_in_current_block
        node.decorator_list = [self.visit(d) for d in node.decorator_list]
        node.body = self._process_statement_list(node.body)
        self._instrumented_in_current_block = outer_instrumented
        return node

    def visit_ClassDef(self, node: ast.ClassDef) -> ast.ClassDef:
        """Instruments the body of a class definition."""
        outer_instrumented = self._instrumented_in_current_block
        node.decorator_list = [self.visit(d) for d in node.decorator_list]
        # Process base classes, keywords if necessary
        node.body = self._process_statement_list(node.body)
        self._instrumented_in_current_block = outer_instrumented
        return node

    # --- Blocks with bodies ---
    def visit_With(self, node: ast.With) -> ast.With:
        """Instruments the body of a 'with' block."""
        outer_instrumented = self._instrumented_in_current_block
        # Visit context items
        node.items = [self.visit(item) for item in node.items]
        # Process body
        node.body = self._process_statement_list(node.body)
        self._instrumented_in_current_block = outer_instrumented
        return node

    def visit_AsyncWith(self, node: ast.AsyncWith) -> ast.AsyncWith:
        """Instruments the body of an 'async with' block."""
        outer_instrumented = self._instrumented_in_current_block
        node.items = [self.visit(item) for item in node.items]
        node.body = self._process_statement_list(node.body)
        self._instrumented_in_current_block = outer_instrumented
        return node

    def visit_If(self, node: ast.If) -> ast.If:
        """Instruments the 'if' and 'else' bodies."""
        outer_instrumented = self._instrumented_in_current_block
        # Visit the test expression
        node.test = self.visit(node.test)
        # Process the 'if' body
        node.body = self._process_statement_list(node.body)
        # Process the 'else' body (which could be another If, or a list)
        if node.orelse:
            # Visit the 'orelse' part. If it's a list, process it. If single If, visit it.
            new_orelse = []
            current_orelse_instrumented = set()  # Reset for the else block
            self._instrumented_in_current_block = current_orelse_instrumented
            for item in node.orelse:
                # Add tracker if needed for the first line of the else item
                if isinstance(item, ast.stmt) and hasattr(item, "lineno"):
                    if (
                        not _is_docstring_or_bare_constant(item)
                        and item.lineno not in self._instrumented_in_current_block
                    ):
                        new_orelse.append(self._create_tracking_call(item.lineno))
                        self._instrumented_in_current_block.add(item.lineno)
                visited_item = self.visit(item)  # Recursively visit item in else block
                if visited_item:
                    if isinstance(visited_item, list):
                        new_orelse.extend(visited_item)
                    elif isinstance(visited_item, ast.AST):
                        new_orelse.append(visited_item)  # type: ignore
            node.orelse = new_orelse
        self._instrumented_in_current_block = outer_instrumented
        return node

    def visit_For(self, node: ast.For) -> ast.For:
        """Instruments the 'for' loop body and 'else' block."""
        outer_instrumented = self._instrumented_in_current_block
        # Visit target and iter
        node.target = self.visit(node.target)
        node.iter = self.visit(node.iter)
        # Process body
        node.body = self._process_statement_list(node.body)
        # Process orelse
        if node.orelse:
            node.orelse = self._process_statement_list(node.orelse)  # type: ignore
        self._instrumented_in_current_block = outer_instrumented
        return node

    def visit_AsyncFor(self, node: ast.AsyncFor) -> ast.AsyncFor:
        """Instruments the 'async for' loop body and 'else' block."""
        outer_instrumented = self._instrumented_in_current_block
        node.target = self.visit(node.target)
        node.iter = self.visit(node.iter)
        node.body = self._process_statement_list(node.body)
        if node.orelse:
            node.orelse = self._process_statement_list(node.orelse)  # type: ignore
        self._instrumented_in_current_block = outer_instrumented
        return node

    def visit_While(self, node: ast.While) -> ast.While:
        """Instruments the 'while' loop body and 'else' block."""
        outer_instrumented = self._instrumented_in_current_block
        node.test = self.visit(node.test)
        node.body = self._process_statement_list(node.body)
        if node.orelse:
            node.orelse = self._process_statement_list(node.orelse)  # type: ignore
        self._instrumented_in_current_block = outer_instrumented
        return node

    def visit_Try(self, node: ast.Try) -> ast.Try:
        """Instruments 'try', 'except', 'else', and 'finally' blocks."""
        outer_instrumented = self._instrumented_in_current_block
        node.body = self._process_statement_list(node.body)
        # Instrument handlers
        new_handlers = []
        for handler in node.handlers:
            handler_outer_instrumented = self._instrumented_in_current_block
            # visit handler.type, handler.name if needed
            handler.body = self._process_statement_list(handler.body)
            self._instrumented_in_current_block = handler_outer_instrumented
            new_handlers.append(handler)  # Add the processed handler
        node.handlers = new_handlers
        # Instrument orelse
        if node.orelse:
            node.orelse = self._process_statement_list(node.orelse)  # type: ignore
        # Instrument finalbody
        if node.finalbody:
            node.finalbody = self._process_statement_list(node.finalbody)  # type: ignore
        self._instrumented_in_current_block = outer_instrumented
        return node

    # Add visit_TryStar for Python 3.11+ if needed


# --- Import Hook ---


class CoverageImportHook(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    """
    An import hook that intercepts imports of target files and loads
    the pre-instrumented source code instead.
    """

    def __init__(
        self, instrumented_sources: Dict[str, str], tracker: CoverageTracker
    ) -> None:
        """
        Initializes the CoverageImportHook.

        Args:
            instrumented_sources: A dictionary mapping resolved file paths to
                                  their instrumented source code.
            tracker: The CoverageTracker instance to inject into modules.
        """
        self._instrumented_sources: Dict[str, str] = instrumented_sources
        self._tracker: CoverageTracker = tracker
        # Track modules currently being executed by this hook to prevent recursion
        self._modules_in_exec: Set[str] = set()

    def find_spec(
        self,
        fullname: str,
        path: Optional[List[str]],
        target: Optional[types.ModuleType] = None,
    ) -> Optional[importlib.machinery.ModuleSpec]:
        # --- Standard filtering ---
        # ... (filtering code remains the same) ...
        # --- End standard filtering ---

        module_name = fullname.split(".")[-1]
        potential_relative_filenames = [
            pathlib.Path(f"{module_name}.py"),
            pathlib.Path(module_name, "__init__.py"),
        ]
        search_paths = path if path is not None else sys.path

        # print(f"DEBUG find_spec: fullname='{fullname}', path='{path}', searching in: {search_paths}") # Debug

        for entry in search_paths:
            try:
                base_path = pathlib.Path(entry)
                if not base_path.is_dir():
                    continue

                for potential_filename in potential_relative_filenames:
                    potential_file_candidate = base_path / potential_filename
                    if potential_file_candidate.is_file():
                        try:
                            resolved_path = potential_file_candidate.resolve()
                            resolved_path_str = str(resolved_path)

                            if resolved_path_str in self._instrumented_sources:
                                is_package = potential_filename.name == "__init__.py"
                                # print(f"  DEBUG find_spec: Match found! {fullname} -> {resolved_path_str}, is_package={is_package}") # Debug

                                # Create the spec using the loader
                                spec = importlib.util.spec_from_loader(
                                    fullname,
                                    self,  # Loader is this hook instance
                                    origin=resolved_path_str,
                                    is_package=is_package,
                                )

                                # --- START CHANGE ---
                                # IMPORTANT: If it's a package, explicitly set submodule_search_locations.
                                # Relying on importlib to infer this from is_package=True with a
                                # custom loader seems unreliable.
                                if spec and is_package:
                                    package_dir = str(resolved_path.parent)
                                    spec.submodule_search_locations = [package_dir]
                                    # print(f"  DEBUG find_spec: Set submodule_search_locations for package {fullname} to: {[package_dir]}") # Optional Debug
                                # --- END CHANGE ---

                                return spec  # Return the potentially modified spec

                        except OSError as e:
                            # print(f"  DEBUG find_spec: OSError resolving {potential_file_candidate}: {e}") # Debug
                            continue
            except OSError as e:
                # print(f"  DEBUG find_spec: OSError accessing base_path {entry}: {e}") # Debug
                continue
            except Exception as e:
                print(
                    f"Warning: Unexpected error in find_spec for {fullname} in {entry}: {type(e).__name__} - {e}",
                    file=sys.stderr,
                )
                continue

        # print(f"DEBUG find_spec: No instrumented source found for {fullname}") # Debug
        return None

    def exec_module(self, module: types.ModuleType) -> None:
        """
        Executes the instrumented source code for the given module.
        Injects the `__coverage_tracker__` global before execution.
        """
        if module.__spec__ is None or module.__spec__.origin is None:
            raise ImportError(f"Module spec or origin missing for {module.__name__}")

        module_path = module.__spec__.origin

        if module_path in self._modules_in_exec:
            # print(f"DEBUG: Skipping re-entrant exec_module for {module_path}") # Debug
            return

        instrumented_source = self._instrumented_sources.get(module_path)
        if instrumented_source is None:
            raise ImportError(
                f"Internal Error: Instrumented source not found for {module_path} "
                f"during exec_module for module {module.__name__}"
            )

        # Set standard attributes (importlib usually does this based on spec)
        module.__name__ = module.__spec__.name
        module.__file__ = module.__spec__.origin
        module.__loader__ = self
        module.__package__ = module.__spec__.parent
        module.__spec__ = module.__spec__
        # If it's a package, importlib should set __path__ based on submodule_search_locations in the spec
        # if module.__spec__.submodule_search_locations is not None:
        #     module.__path__ = module.__spec__.submodule_search_locations

        # Inject the tracker
        module.__dict__["__coverage_tracker__"] = self._tracker

        # print(f"DEBUG: Executing module: {module.__name__} ({module_path})")
        # print(f"DEBUG: Spec Origin: {module.__spec__.origin}")
        # # --- Add more debug ---
        # print(f"DEBUG: Spec Name: {module.__spec__.name}")
        # print(f"DEBUG: Spec is_package: {getattr(module.__spec__, 'submodule_search_locations', None) is not None}") # Better check for package nature based on locations
        # print(f"DEBUG: Spec submodule_search_locations: {getattr(module.__spec__, 'submodule_search_locations', None)}")
        # print(f"DEBUG: Module __package__: {getattr(module, '__package__', None)}")
        # # --- End Add more debug ---

        self._modules_in_exec.add(module_path)
        try:
            code = compile(instrumented_source, module_path, "exec", dont_inherit=True)
            # print(f"DEBUG: Module dict before exec: {list(module.__dict__.keys())}") # Optional Debug
            exec(code, module.__dict__)
            # print(f"DEBUG: Finished executing module: {module.__name__}") # Debug
            # print(f"DEBUG: Module dict after exec: {list(module.__dict__.keys())}") # Optional Debug

        except Exception as e:
            print(
                f"\n--- Error during execution of instrumented module: {module_path} ---",
                file=sys.stderr,
            )
            traceback.print_exc()
            print(
                f"--- Module Dict Keys: {list(module.__dict__.keys())} ---",
                file=sys.stderr,
            )  # Debug info
            print("--- End Error ---", file=sys.stderr)
            raise e
        finally:
            self._modules_in_exec.discard(module_path)


def _is_excluded(filepath: pathlib.Path, root_dir: pathlib.Path) -> bool:
    """
    Checks if a file path should be excluded based on configuration.

    Args:
        filepath: The absolute, resolved path to the file.
        root_dir: The absolute, resolved root directory of the project scan.

    Returns:
        True if the file should be excluded, False otherwise.
    """
    # 1. Exclude the tool script itself
    if filepath == _TOOL_SCRIPT_PATH:
        # print(f"DEBUG: Excluding tool script: {filepath}")
        return True

    # 2. Exclude specific filenames
    if filepath.name in EXCLUDE_FILENAMES:
        # print(f"DEBUG: Excluding filename: {filepath.name}")
        return True

    # 3. Check if any directory component in the path relative to the root
    #    matches an excluded directory name. This handles nested exclusions.
    try:
        relative_path = filepath.relative_to(root_dir)
        # Check all parent directory names in the relative path
        for part in relative_path.parts[:-1]:  # Exclude the filename part itself
            if part in EXCLUDE_DIRS:
                # print(f"DEBUG: Excluding {filepath} due to directory part '{part}'")
                return True
    except ValueError:
        # The file is not under the root_dir. This shouldn't typically happen
        # with os.walk starting at root_dir unless symlinks are involved and point
        # outside, but it's safer to exclude such files.
        # print(f"DEBUG: Excluding {filepath} as it's outside root {root_dir}")
        return True

    # If none of the above rules matched, do not exclude the file.
    return False


def find_target_files(root_dir: str) -> List[str]:
    """
    Finds all target Python files within the root directory, respecting exclusions.

    Args:
        root_dir: The path to the root directory to scan.

    Returns:
        A list of absolute, resolved paths to the Python files to be instrumented.
        Returns an empty list if the root directory doesn't exist or no files are found.
    """
    target_files: Set[str] = set()  # Use a set to avoid duplicates
    try:
        root_path = pathlib.Path(root_dir).resolve()
    except OSError as e:
        print(
            f"Error: Could not resolve root directory '{root_dir}': {e}",
            file=sys.stderr,
        )
        return []

    if not root_path.is_dir():
        print(
            f"Error: Root directory '{root_path}' not found or is not a directory.",
            file=sys.stderr,
        )
        return []

    print(f"Scanning for Python files in: {root_path}")
    print(f"Excluding directories (during walk): {EXCLUDE_DIRS}")
    print(f"Excluding filenames (during check): {EXCLUDE_FILENAMES}")

    try:
        # os.walk is efficient for traversing directories and allows pruning
        for dirpath_str, dirnames, filenames in os.walk(
            root_path, topdown=True, followlinks=False
        ):  # Avoid following symlinks by default
            dirpath = pathlib.Path(dirpath_str)

            # Prune excluded directories based on their *name* only.
            # This stops os.walk from descending into them.
            original_dirnames = list(dirnames)  # Copy before modifying
            dirnames[:] = [d for d in dirnames if d not in EXCLUDE_DIRS]
            # Debug print pruned dirs
            # pruned = set(original_dirnames) - set(dirnames)
            # if pruned: print(f"  Pruning dirs in {dirpath}: {pruned}")

            for filename in filenames:
                if filename.endswith(TARGET_FILE_SUFFIX):
                    try:
                        filepath = (dirpath / filename).resolve()
                        # Apply exclusion rules using the resolved path and root
                        if not _is_excluded(filepath, root_path):
                            # print(f"DEBUG: Including file: {filepath}") # Debug print
                            target_files.add(str(filepath))
                        # else:
                        # print(f"DEBUG: Excluding file: {filepath}") # Debug print

                    except OSError as e:
                        # Handle potential errors during resolve (e.g., symlink loops if followlinks=True)
                        print(
                            f"Warning: Could not resolve path for {dirpath / filename}, skipping: {e}",
                            file=sys.stderr,
                        )
                    except Exception as e:
                        print(
                            f"Warning: Unexpected error processing file {dirpath / filename}, skipping: {e}",
                            file=sys.stderr,
                        )

    except Exception as e:
        print(
            f"Error during file discovery in '{root_dir}': {type(e).__name__}: {e}",
            file=sys.stderr,
        )
        traceback.print_exc(file=sys.stderr)
        return []

    return sorted(list(target_files))  # Return a sorted list


def process_file(filepath: str) -> Tuple[Set[int], Optional[str]]:
    """
    Reads a Python file, finds executable lines, and generates instrumented source code.

    Args:
        filepath: The absolute, resolved path to the Python file.

    Returns:
        A tuple containing:
        - A set of line numbers deemed executable in the original file.
        - The instrumented source code as a string, or None if processing failed
          (e.g., due to read errors, syntax errors, or instrumentation errors).
    """
    filepath_obj = pathlib.Path(filepath)
    source: str
    tree: ast.AST
    instrumented_tree: ast.AST
    executable_lines: Set[int] = set()
    instrumented_source: Optional[str] = None

    # 1. Read the source file
    try:
        with open(
            filepath_obj, "r", encoding="utf-8", errors="surrogateescape"
        ) as f:  # Be more robust reading
            source = f.read()
    except FileNotFoundError:
        print(f"Error: File not found: {filepath}", file=sys.stderr)
        return set(), None
    except OSError as e:
        print(f"Error reading file {filepath}: {e}", file=sys.stderr)
        return set(), None
    except UnicodeDecodeError as e:
        print(f"Error decoding file {filepath} (check encoding): {e}", file=sys.stderr)
        # Try to read with a fallback encoding? Or just fail. Failing is safer.
        return set(), None

    # 2. Parse the source to find executable lines
    try:
        tree = ast.parse(source, filename=filepath)
        collector = ExecutableLineCollector()
        collector.visit(tree)
        executable_lines = collector.lines
    except SyntaxError as e:
        print(
            f"Syntax error parsing {filepath}:{e.lineno}:{e.offset}: {e.msg}",
            file=sys.stderr,
        )
        return set(), None  # Cannot instrument if syntax is invalid
    except Exception as e:
        # Catch other potential AST processing errors
        print(
            f"Error during AST analysis of {filepath}: {type(e).__name__}: {e}",
            file=sys.stderr,
        )
        traceback.print_exc(file=sys.stderr)
        return set(), None

    # If no executable lines were found, no need to instrument
    # Return the empty set and None for source to indicate no instrumentation needed/possible.
    if not executable_lines:
        # print(f"No executable lines found in {filepath}") # Optional debug info
        return set(), None

    # 3. Instrument the code (re-parse for a clean tree)
    try:
        # Pass filename for better error messages during transformation/unparsing
        tree_to_instrument = ast.parse(source, filename=filepath)
        transformer = InstrumentationTransformer(filepath)  # Pass resolved path
        instrumented_tree = transformer.visit(tree_to_instrument)
        # Add missing line/column info required after transformations
        ast.fix_missing_locations(instrumented_tree)
        instrumented_source = ast.unparse(instrumented_tree)
    except Exception as e:
        print(
            f"Error during AST instrumentation of {filepath}: {type(e).__name__}: {e}",
            file=sys.stderr,
        )
        traceback.print_exc(file=sys.stderr)
        # Return the found executable lines, but None for the source as it failed
        return executable_lines, None

    return executable_lines, instrumented_source


# --- Test Execution ---


def run_tests(test_dir: str, test_pattern: str) -> Tuple[bool, int]:
    """
    Discovers and runs tests using unittest.

    Args:
        test_dir: The directory containing the tests.
        test_pattern: The filename pattern for discovering test files.

    Returns:
        A tuple containing:
        - bool: True if tests ran successfully (or no tests found), False if errors occurred.
        - int: The number of tests found and run.
    """
    print("\nDiscovering and running tests...")
    tests_passed = True
    tests_run_count = 0
    loader = unittest.TestLoader()
    runner = unittest.TextTestRunner(verbosity=1, failfast=False)  # Standard verbosity

    try:
        # Resolve paths for clarity and consistency
        test_suite_path = str(pathlib.Path(test_dir).resolve())
        # Top-level dir helps with imports if tests are in a subdir of the project
        project_root_dir = str(_CURRENT_WORKING_DIR)  # Use resolved CWD

        if not os.path.exists(test_suite_path):
            print(f"Error: Test directory not found: {test_dir}", file=sys.stderr)
            return False, 0  # Cannot run tests

        # Ensure the project root is temporarily in sys.path for discovery to work robustly,
        # especially if tests import code using relative paths from the project root.
        original_sys_path = sys.path[:]
        if project_root_dir not in sys.path:
            sys.path.insert(0, project_root_dir)
            path_added = True
        else:
            path_added = False

        try:
            # Discover tests. Requires the test directory or its parent to be importable.
            test_suite = loader.discover(
                start_dir=test_suite_path,
                pattern=test_pattern,
                top_level_dir=project_root_dir,  # Helps resolve imports relative to project root
            )

            tests_run_count = test_suite.countTestCases()

            if tests_run_count == 0:
                print(
                    f"Warning: No tests found in '{test_dir}' matching pattern '{test_pattern}'."
                )
                # Technically not a failure, but coverage will be 0
                return True, 0
            else:
                print(f"Found {tests_run_count} tests.")
                # Running the tests triggers imports, which will use our hook
                result = runner.run(test_suite)
                tests_passed = result.wasSuccessful()
                if not tests_passed:
                    print("Test execution failed.")

        finally:
            # Restore sys.path
            if path_added:
                # Use original_sys_path to be safe, avoid removing if it was there before
                sys.path = original_sys_path

    except ImportError as e:
        print(
            f"Error discovering tests in '{test_dir}': {type(e).__name__}: {e}",
            file=sys.stderr,
        )
        print(
            "Hint: Ensure the test directory or project root is in PYTHONPATH or discoverable.",
            file=sys.stderr,
        )
        traceback.print_exc(file=sys.stderr)  # Show where import failed
        tests_passed = False  # Critical failure
    except Exception as e:
        print(
            f"Unexpected error during test discovery or execution: {type(e).__name__}: {e}",
            file=sys.stderr,
        )
        traceback.print_exc(file=sys.stderr)
        tests_passed = False  # Critical failure

    return tests_passed, tests_run_count


# --- Report Generation ---


def generate_report(
    tracker: CoverageTracker, all_executable_lines: Dict[str, Set[int]]
) -> Tuple[int, int]:
    """
    Calculates coverage and prints a report to the console.

    Args:
        tracker: The CoverageTracker instance containing hit lines.
        all_executable_lines: A dictionary mapping resolved file paths to their
                              sets of executable line numbers.

    Returns:
        A tuple containing (total_lines_hit, total_executable_lines).
    """
    print("\n--- Coverage Report ---")

    total_hit: int = 0
    total_executable: int = 0
    covered_files_count: int = 0

    # Get all hits once from the tracker
    all_hits: Set[Tuple[str, int]] = tracker.hits

    # Sort files by relative path for consistent reporting
    # Use a list of (relative_path, resolved_path) tuples for sorting
    file_paths_for_report: List[Tuple[str, str]] = []
    # Use the keys from all_executable_lines which represent successfully processed files
    for resolved_fpath in sorted(all_executable_lines.keys()):
        try:
            # Make path relative to the current directory for cleaner output
            relative_fpath = str(
                pathlib.Path(resolved_fpath).relative_to(_CURRENT_WORKING_DIR)
            )
        except ValueError:
            # If the file is outside the current directory, use the absolute path
            relative_fpath = resolved_fpath
        # Only add files that actually have executable lines to the report list
        if all_executable_lines.get(resolved_fpath):
            file_paths_for_report.append((relative_fpath, resolved_fpath))

    # Sort alphabetically by the calculated relative path
    file_paths_for_report.sort(key=lambda item: item[0])

    for relative_fpath, resolved_fpath in file_paths_for_report:
        executable_lines = all_executable_lines.get(
            resolved_fpath, set()
        )  # Should always exist here
        # Filter hits efficiently for the current file
        hit_lines = {lineno for fpath, lineno in all_hits if fpath == resolved_fpath}

        num_executable = len(executable_lines)
        num_hit = len(hit_lines)

        # Don't report on files with 0 executable lines found
        if num_executable > 0:
            total_executable += num_executable
            total_hit += num_hit
            covered_files_count += 1

            coverage_percentage = num_hit / num_executable * 100
            # Format output neatly
            formatted_line = f"{relative_fpath:<50} {num_hit:>4}/{num_executable:<4} lines ({coverage_percentage:>6.1f}%)"
            print(formatted_line)

            # Optional: Show missing lines (can be verbose)
            missing = sorted(list(executable_lines - hit_lines))
            if missing:
                # Format missing lines compactly
                missing_str = ", ".join(map(str, missing))
                if len(missing_str) > 80:  # Truncate if too long
                    missing_str = missing_str[:77] + "..."
                print(f"  Missing: {missing_str}")
        # else: # No executable lines, skip report line for this file

    print("-" * 60)
    if total_executable > 0:
        overall_percentage = total_hit / total_executable * 100
        print(
            f"Overall coverage ({covered_files_count} files): "
            f"{total_hit}/{total_executable} lines "
            f"({overall_percentage:.1f}%)"
        )
    elif covered_files_count > 0:
        print(
            f"Overall coverage ({covered_files_count} files): "
            f"0/0 lines (100.0%) - No executable lines found in covered files."
        )
    else:
        print(
            "Overall coverage: No target files with executable lines found or processed."
        )
    print("-" * 60)

    return total_hit, total_executable


# --- Uncovered Code Context Generation ---


def get_uncovered_code_context(root_dir: str = ".") -> str:
    """
    Runs the full coverage analysis and returns a string containing the
    source code lines that were *not* covered by tests, formatted for LLMs.

    Args:
        root_dir: The root directory to scan for source files and tests.

    Returns:
        A string containing the uncovered code lines, prefixed with file paths,
        or an error/status message if the process fails or finds nothing.
    """
    # --- Replicate core logic from main() but use a local tracker ---
    local_tracker = CoverageTracker()
    all_executable_lines: Dict[str, Set[int]] = {}
    instrumented_sources: Dict[str, str] = {}

    # 1. Find and process target files
    target_files = find_target_files(root_dir)
    if not target_files:
        return "No target Python files found."

    processed_count = 0
    for fpath in target_files:
        exec_lines, instrumented_src = process_file(fpath)
        if exec_lines or instrumented_src is not None:
            all_executable_lines[fpath] = exec_lines
        if instrumented_src is not None:
            instrumented_sources[fpath] = instrumented_src
            processed_count += 1

    if not instrumented_sources:
        return "No source files could be successfully instrumented."

    # 2. Set up the import hook
    hook = CoverageImportHook(instrumented_sources, local_tracker)
    original_meta_path = sys.meta_path[:]
    sys.meta_path.insert(0, hook)
    hook_installed = True

    # 3. Run the tests
    tests_passed: bool = False
    try:
        # Assuming TEST_DIR and TEST_FILE_PATTERN are globally accessible constants
        tests_passed, _ = run_tests(TEST_DIR, TEST_FILE_PATTERN)
        if not tests_passed:
            print(
                "Warning: Tests failed during uncovered context generation.",
                file=sys.stderr,
            )
            # Continue to report coverage based on hits before failure
    except Exception as e:
        print(f"Error running tests during context generation: {e}", file=sys.stderr)
        # Continue if possible, coverage might be partial
    finally:
        # 4. VERY IMPORTANT: Remove the import hook
        if hook_installed:
            sys.meta_path = (
                original_meta_path  # Simple restoration if no modification occurred
            )
            # More robust removal if other hooks might have been added/removed:
            # current_meta_path = sys.meta_path[:]
            # sys.meta_path.clear()
            # hook_removed = False
            # for item in current_meta_path:
            #     if item is hook: # Check instance equality
            #         hook_removed = True
            #         continue
            #     sys.meta_path.append(item)
            # if not hook_removed:
            #      print("Warning: Could not reliably remove coverage hook.", file=sys.stderr)

    # 5. Calculate missed lines
    all_hits: Set[Tuple[str, int]] = local_tracker.hits
    missed_lines_map: Dict[str, List[int]] = (
        {}
    )  # Map resolved path to list of missed lines

    reportable_files = sorted(
        instrumented_sources.keys()
    )  # Only report on instrumented files

    for resolved_fpath in reportable_files:
        executable_lines = all_executable_lines.get(resolved_fpath, set())
        if not executable_lines:
            continue  # Skip files with no executable lines

        hit_lines = {lineno for fpath, lineno in all_hits if fpath == resolved_fpath}
        missed = sorted(list(executable_lines - hit_lines))

        if missed:
            missed_lines_map[resolved_fpath] = missed

    # 6. Generate the context string
    if not missed_lines_map:
        return (
            "No uncovered lines found."
            if tests_passed
            else "Tests failed, coverage incomplete, no uncovered lines reported."
        )

    context_lines: List[str] = []
    # Sort by relative path for consistent output
    sorted_resolved_paths = sorted(
        missed_lines_map.keys(),
        key=lambda p: (
            str(pathlib.Path(p).relative_to(_CURRENT_WORKING_DIR))
            if p.startswith(str(_CURRENT_WORKING_DIR))
            else p
        ),
    )

    for resolved_fpath in sorted_resolved_paths:
        try:
            relative_fpath = str(
                pathlib.Path(resolved_fpath).relative_to(_CURRENT_WORKING_DIR)
            )
        except ValueError:
            relative_fpath = resolved_fpath  # Use absolute if not relative

        context_lines.append(f"## {relative_fpath}")
        missed_line_numbers = missed_lines_map[resolved_fpath]

        try:
            # Read source code
            with open(
                resolved_fpath, "r", encoding="utf-8", errors="surrogateescape"
            ) as f:
                source = f.read()
                # Use splitlines() to handle different line endings consistently
                # Keepends=False removes line ending characters
                source_lines = source.splitlines()

            # --- Find scope for each line using AST ---
            line_to_scope: Dict[int, str] = {}
            try:
                # Parse the original source code
                tree = ast.parse(source, filename=resolved_fpath)
                scope_finder = ScopeFinder()
                scope_finder.visit(tree)
                line_to_scope = scope_finder.line_to_scope
            except SyntaxError as e:
                context_lines.append(f"  [SyntaxError parsing for scope: {e}]")
                # Fallback: print lines without scope info if parsing fails
                context_lines.append("  Uncovered lines (scope unavailable):")
                for lineno in missed_line_numbers:
                    if 0 < lineno <= len(source_lines):
                        code_line = source_lines[lineno - 1].strip()
                        if code_line:
                            context_lines.append(f"    {code_line}")
                    else:
                        context_lines.append(f"    [Error reading line {lineno}]")
                context_lines.append("")  # Blank line after file
                continue  # Skip to next file
            except Exception as e:
                context_lines.append(
                    f"  [Error finding scope: {type(e).__name__}: {e}]"
                )
                # Consider fallback here too, or just report error and continue

            # --- Group missed lines by their determined scope ---
            # Use defaultdict(list) to store scope_name -> list of code lines
            scope_to_missed_lines = collections.defaultdict(list)
            # Use a consistent fallback for lines potentially outside mapped scopes
            default_scope = "[module level]"

            for lineno in missed_line_numbers:
                # Line numbers are 1-based, source_lines is 0-based list
                if 0 < lineno <= len(source_lines):
                    # Find the scope associated with this line number
                    scope_name = line_to_scope.get(lineno, default_scope)
                    # Clean up the scope name string for better readability
                    # Remove redundant module prefix if it's the only scope element
                    if scope_name.startswith("[module level] / "):
                        scope_name = scope_name[len("[module level] / ") :]
                    elif scope_name == "[module level]":
                        pass  # Keep it as is

                    # Get the actual source code line, stripped of leading/trailing whitespace
                    code_line = source_lines[lineno - 1].strip()

                    # Add the non-empty code line to the list for its scope
                    if code_line:
                        scope_to_missed_lines[scope_name].append(code_line)
                # else: Can log error about unexpected line number, but usually safe to ignore

            # --- Format the output for this file ---
            if not scope_to_missed_lines:
                # This might happen if only empty lines were missed, or lines couldn't be read
                context_lines.append(
                    "  (No specific uncovered source lines identified for this file)"
                )
            else:
                # Sort the scopes alphabetically for consistent output order
                sorted_scopes = sorted(scope_to_missed_lines.keys())

                for scope in sorted_scopes:
                    # Add a scope heading. Add a blank line before it for separation, unless it's the first scope.
                    if (
                        scope != sorted_scopes[0] or len(context_lines) > 1
                    ):  # Check if not first line overall
                        context_lines.append("")  # Add blank line separator
                    context_lines.append(f"### {scope}")  # Scope name heading

                    # Add the missed code lines associated with this scope
                    for line in scope_to_missed_lines[scope]:
                        # Indent code lines for readability under the scope heading
                        context_lines.append(f"    {line}")

        except FileNotFoundError:
            context_lines.append(
                f"  [Error: File not found at {resolved_fpath} during context generation]"
            )
        except Exception as e:
            # Catch other errors during file reading or processing for this specific file
            context_lines.append(
                f"  [Error processing file {relative_fpath} for context: {type(e).__name__}: {e}]"
            )
            # traceback.print_exc() # Optionally add full traceback for debugging

        # Ensure there's a blank line separating file sections in the final output
        context_lines.append("")

    # Join all collected lines (file headers, scope headers, code lines, errors) into the final string
    # Use strip() to remove leading/trailing whitespace, especially the final blank line.
    return "\n".join(context_lines).strip()


# --- Main Execution ---


def main() -> int:
    """
    Main function to orchestrate the coverage process.

    Returns:
        Exit code (0 for success, 1 for failure).
    """
    # Store executable lines and instrumented source per file (using resolved path)
    all_executable_lines: Dict[str, Set[int]] = {}
    instrumented_sources: Dict[str, str] = {}
    tracker: CoverageTracker = __coverage_tracker__  # Use the global instance

    print("Starting Coverage Tool...")

    # 1. Find and process target files
    # Use current directory '.' as the default root
    target_files = find_target_files(".")
    if not target_files:
        print(
            "No target Python files found to instrument (check exclusions and paths)."
        )
        # No files means nothing to cover, technically not a failure if no source exists.
        return 0

    print(f"Found {len(target_files)} potential target files.")

    processed_count = 0
    for fpath in target_files:
        # process_file expects resolved paths, fpath from find_target_files is already resolved
        exec_lines, instrumented_src = process_file(fpath)

        # Store results ONLY if instrumentation was successful (instrumented_src is not None)
        # exec_lines might be non-empty even if instrumentation fails, record those for potential reporting
        if exec_lines or instrumented_src is not None:
            all_executable_lines[fpath] = (
                exec_lines  # Store lines even if instrumentation failed
            )

        if instrumented_src is not None:
            instrumented_sources[fpath] = instrumented_src
            processed_count += 1
        # If instrumented_src is None, process_file already printed an error.

    if not instrumented_sources:
        print("No source files could be successfully instrumented. Exiting.")
        # If processing failed for all files, treat as an error.
        # Check if there were files with executable lines found but failed instrumentation
        if any(lines for lines in all_executable_lines.values()):
            print(
                "Some files had executable lines but failed instrumentation (see errors above)."
            )
        return 1

    print(
        f"Successfully processed and prepared {processed_count} files for instrumentation."
    )

    # 2. Set up the import hook
    hook = CoverageImportHook(instrumented_sources, tracker)
    # Insert at the beginning of meta_path to ensure it runs before default importers
    sys.meta_path.insert(0, hook)
    print("Coverage import hook installed.")

    # 3. Run the tests
    tests_passed: bool = False
    tests_run_count: int = 0
    try:
        tests_passed, tests_run_count = run_tests(TEST_DIR, TEST_FILE_PATTERN)
    finally:
        # 4. VERY IMPORTANT: Remove the import hook regardless of test outcome
        # Use a loop and check instance to be safer if multiple hooks were added
        original_meta_path = sys.meta_path[:]
        sys.meta_path.clear()
        hook_removed = False
        for item in original_meta_path:
            if isinstance(item, CoverageImportHook):
                hook_removed = True  # Found our hook (or an instance of it)
                continue  # Don't add it back
            sys.meta_path.append(item)  # Add other hooks back

        if hook_removed:
            print("Coverage import hook removed.")
        else:
            print(
                "Warning: Coverage import hook was not found in sys.meta_path during cleanup.",
                file=sys.stderr,
            )

    # 5. Calculate and report coverage using only successfully instrumented files' lines
    # Filter all_executable_lines to only include those that were instrumented
    reportable_executable_lines = {
        fpath: lines
        for fpath, lines in all_executable_lines.items()
        if fpath in instrumented_sources
    }
    total_hit, total_executable = generate_report(tracker, reportable_executable_lines)

    # 6. Determine final exit status
    if not tests_passed:
        print("\nCoverage run finished with test failures.")
        return 1  # Test failures mean the run failed

    # If tests passed (or no tests found), check coverage
    if total_executable > 0 and total_hit == 0 and tests_run_count > 0:
        # Only warn about 0% coverage if tests were actually run AND executable lines existed
        print("\nWarning: Tests passed, but no lines were covered by the tests.")
        # Decide if 0% coverage should be a failure. Let's make it a non-zero exit code.
        return 1  # Treat 0% coverage (with tests run) as failure
        # return 0 # Or treat 0% coverage as success if tests passed

    print("\nCoverage run finished successfully.")
    return 0  # Success


if __name__ == "__main__":
    # Ensure the script's directory isn't interfering with imports if possible
    script_dir = str(_TOOL_SCRIPT_PATH.parent)
    if script_dir in sys.path:
        try:
            sys.path.remove(script_dir)
        except ValueError:
            pass  # Should not happen based on check, but be safe

    print(">>>>" + get_uncovered_code_context())

    # sys.exit(main())
