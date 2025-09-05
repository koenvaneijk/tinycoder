import ast
import importlib.abc
import importlib.util
import os
import pathlib
import sys
import traceback
import types
import unittest
import collections
import io
from typing import Dict, List, Optional, Set, Tuple, Callable

import logging

TEST_DIR = "./tests"
TEST_FILE_PATTERN = "test_*.py"
TARGET_FILE_SUFFIX = ".py"

EXCLUDE_DIRS = {
    "venv",
    ".venv",
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
    "site-packages",
}
EXCLUDE_FILENAMES = {
    "setup.py",
    "conftest.py",
    "coverage_tool.py",
}

_TOOL_SCRIPT_PATH = pathlib.Path(__file__).resolve()
_CURRENT_WORKING_DIR = pathlib.Path(".").resolve()


class CoverageTracker:
    def __init__(self) -> None:
        self.hits: Set[Tuple[str, int]] = set()

    def hit(self, filepath: str, lineno: int) -> None:
        try:
            resolved_path = str(pathlib.Path(filepath).resolve())
            self.hits.add((resolved_path, lineno))
        except OSError as e:
            print(
                f"Warning: Could not resolve path '{filepath}' during hit: {e}",
                file=sys.stderr,
            )


__coverage_tracker__ = CoverageTracker()


# --- AST Helper ---


class ScopeFinder(ast.NodeVisitor):
    def __init__(self):
        self.line_to_scope: Dict[int, str] = {}
        self._scope_stack: List[str] = []

    def _get_current_scope_name(self) -> str:
        return " / ".join(self._scope_stack) if self._scope_stack else "[unknown]"

    def visit(self, node: ast.AST):
        if hasattr(node, "lineno"):
            current_scope = self._get_current_scope_name()
            start_line = node.lineno
            end_line = getattr(node, "end_lineno", start_line)
            if end_line is None:
                end_line = start_line
            for line_num in range(start_line, end_line + 1):
                self.line_to_scope[line_num] = current_scope
        super().visit(node)

    def visit_Module(self, node: ast.Module):
        self._scope_stack.append("[module level]")
        self.generic_visit(node)
        self._scope_stack.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef):
        scope_id = f"function {node.name}"
        self._scope_stack.append(scope_id)
        self.generic_visit(node)
        self._scope_stack.pop()

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        scope_id = f"async function {node.name}"
        self._scope_stack.append(scope_id)
        self.generic_visit(node)
        self._scope_stack.pop()

    def visit_ClassDef(self, node: ast.ClassDef):
        scope_id = f"class {node.name}"
        self._scope_stack.append(scope_id)
        self.generic_visit(node)
        self._scope_stack.pop()


def _is_docstring_or_bare_constant(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Expr)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, (str, bytes))
    )


# --- AST Analysis: Find Executable Lines ---


class ExecutableLineCollector(ast.NodeVisitor):
    def __init__(self) -> None:
        self.lines: Set[int] = set()

    def visit(self, node: ast.AST) -> None:
        if isinstance(node, ast.stmt) and hasattr(node, "lineno"):
            if not _is_docstring_or_bare_constant(node):
                self.lines.add(node.lineno)
        self.generic_visit(node)


# --- AST Transformation: Instrument Code ---


class InstrumentationTransformer(ast.NodeTransformer):
    def __init__(self, filename: str) -> None:
        self.filename: str = filename
        self._instrumented_in_current_block: Set[int] = set()

    def _create_tracking_call(self, lineno: int) -> ast.Expr:
        return ast.Expr(
            value=ast.Call(
                func=ast.Attribute(
                    value=ast.Name(id="__coverage_tracker__", ctx=ast.Load()),
                    attr="hit",
                    ctx=ast.Load(),
                ),
                args=[
                    ast.Constant(value=self.filename),
                    ast.Constant(value=lineno),
                ],
                keywords=[],
            )
        )

    def _process_statement_list(self, body: List[ast.stmt]) -> List[ast.stmt]:
        new_body: List[ast.stmt] = []
        self._instrumented_in_current_block = set()

        for node in body:
            if isinstance(node, ast.stmt) and hasattr(node, "lineno"):
                if (
                    not _is_docstring_or_bare_constant(node)
                    and node.lineno not in self._instrumented_in_current_block
                ):
                    new_body.append(self._create_tracking_call(node.lineno))
                    self._instrumented_in_current_block.add(node.lineno)

            visited_node = self.visit(node)

            if visited_node:
                if isinstance(visited_node, list):
                    new_body.extend(visited_node)
                elif isinstance(visited_node, ast.AST):
                    new_body.append(visited_node)

        return new_body

    def visit_Module(self, node: ast.Module) -> ast.Module:
        node.body = self._process_statement_list(node.body)
        return node

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.FunctionDef:
        outer_instrumented = self._instrumented_in_current_block
        node.decorator_list = [self.visit(d) for d in node.decorator_list]
        node.body = self._process_statement_list(node.body)
        self._instrumented_in_current_block = outer_instrumented
        return node

    def visit_AsyncFunctionDef(
        self, node: ast.AsyncFunctionDef
    ) -> ast.AsyncFunctionDef:
        outer_instrumented = self._instrumented_in_current_block
        node.decorator_list = [self.visit(d) for d in node.decorator_list]
        node.body = self._process_statement_list(node.body)
        self._instrumented_in_current_block = outer_instrumented
        return node

    def visit_ClassDef(self, node: ast.ClassDef) -> ast.ClassDef:
        outer_instrumented = self._instrumented_in_current_block
        node.decorator_list = [self.visit(d) for d in node.decorator_list]
        node.body = self._process_statement_list(node.body)
        self._instrumented_in_current_block = outer_instrumented
        return node

    def visit_With(self, node: ast.With) -> ast.With:
        outer_instrumented = self._instrumented_in_current_block
        node.items = [self.visit(item) for item in node.items]
        node.body = self._process_statement_list(node.body)
        self._instrumented_in_current_block = outer_instrumented
        return node

    def visit_AsyncWith(self, node: ast.AsyncWith) -> ast.AsyncWith:
        outer_instrumented = self._instrumented_in_current_block
        node.items = [self.visit(item) for item in node.items]
        node.body = self._process_statement_list(node.body)
        self._instrumented_in_current_block = outer_instrumented
        return node

    def visit_If(self, node: ast.If) -> ast.If:
        outer_instrumented = self._instrumented_in_current_block
        node.test = self.visit(node.test)
        node.body = self._process_statement_list(node.body)
        if node.orelse:
            new_orelse = []
            current_orelse_instrumented = set()
            self._instrumented_in_current_block = current_orelse_instrumented
            for item in node.orelse:
                if isinstance(item, ast.stmt) and hasattr(item, "lineno"):
                    if (
                        not _is_docstring_or_bare_constant(item)
                        and item.lineno not in self._instrumented_in_current_block
                    ):
                        new_orelse.append(self._create_tracking_call(item.lineno))
                        self._instrumented_in_current_block.add(item.lineno)
                visited_item = self.visit(item)
                if visited_item:
                    if isinstance(visited_item, list):
                        new_orelse.extend(visited_item)
                    elif isinstance(visited_item, ast.AST):
                        new_orelse.append(visited_item)
            node.orelse = new_orelse
        self._instrumented_in_current_block = outer_instrumented
        return node

    def visit_For(self, node: ast.For) -> ast.For:
        outer_instrumented = self._instrumented_in_current_block
        node.target = self.visit(node.target)
        node.iter = self.visit(node.iter)
        node.body = self._process_statement_list(node.body)
        if node.orelse:
            node.orelse = self._process_statement_list(node.orelse)
        self._instrumented_in_current_block = outer_instrumented
        return node

    def visit_AsyncFor(self, node: ast.AsyncFor) -> ast.AsyncFor:
        outer_instrumented = self._instrumented_in_current_block
        node.target = self.visit(node.target)
        node.iter = self.visit(node.iter)
        node.body = self._process_statement_list(node.body)
        if node.orelse:
            node.orelse = self._process_statement_list(node.orelse)
        self._instrumented_in_current_block = outer_instrumented
        return node

    def visit_While(self, node: ast.While) -> ast.While:
        outer_instrumented = self._instrumented_in_current_block
        node.test = self.visit(node.test)
        node.body = self._process_statement_list(node.body)
        if node.orelse:
            node.orelse = self._process_statement_list(node.orelse)
        self._instrumented_in_current_block = outer_instrumented
        return node

    def visit_Try(self, node: ast.Try) -> ast.Try:
        outer_instrumented = self._instrumented_in_current_block
        node.body = self._process_statement_list(node.body)
        new_handlers = []
        for handler in node.handlers:
            handler_outer_instrumented = self._instrumented_in_current_block
            handler.body = self._process_statement_list(handler.body)
            self._instrumented_in_current_block = handler_outer_instrumented
            new_handlers.append(handler)
        node.handlers = new_handlers
        if node.orelse:
            node.orelse = self._process_statement_list(node.orelse)
        if node.finalbody:
            node.finalbody = self._process_statement_list(node.finalbody)
        self._instrumented_in_current_block = outer_instrumented
        return node


# --- Import Hook ---


class CoverageImportHook(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    def __init__(
        self, instrumented_sources: Dict[str, str], tracker: CoverageTracker
    ) -> None:
        self._instrumented_sources: Dict[str, str] = instrumented_sources
        self._tracker: CoverageTracker = tracker
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
        if module.__spec__ is None or module.__spec__.origin is None:
            raise ImportError(f"Module spec or origin missing for {module.__name__}")

        module_path = module.__spec__.origin

        if module_path in self._modules_in_exec:
            return

        instrumented_source = self._instrumented_sources.get(module_path)
        if instrumented_source is None:
            raise ImportError(
                f"Internal Error: Instrumented source not found for {module_path} "
                f"during exec_module for module {module.__name__}"
            )

        module.__name__ = module.__spec__.name
        module.__file__ = module.__spec__.origin
        module.__loader__ = self
        module.__package__ = module.__spec__.parent
        module.__spec__ = module.__spec__

        module.__dict__["__coverage_tracker__"] = self._tracker

        self._modules_in_exec.add(module_path)
        try:
            code = compile(instrumented_source, module_path, "exec", dont_inherit=True)
            exec(code, module.__dict__)
        except Exception as e:
            print(
                f"\n--- Error during execution of instrumented module: {module_path} ---",
                file=sys.stderr,
            )
            traceback.print_exc()
            print(
                f"--- Module Dict Keys: {list(module.__dict__.keys())} ---",
                file=sys.stderr,
            )
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

    logging.debug(f"Scanning for Python files in: {root_path}")
    logging.debug(f"Excluding directories (during walk): {EXCLUDE_DIRS}")
    logging.debug(f"Excluding filenames (during check): {EXCLUDE_FILENAMES}")

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

    # Build directory tree structure
    dir_tree = {}
    file_info_map: Dict[str, Dict] = {}
    
    for relative_fpath, resolved_fpath in file_paths_for_report:
        executable_lines = all_executable_lines.get(
            resolved_fpath, set()
        )
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
            
            # Build directory tree
            path_parts = pathlib.Path(relative_fpath).parts
            current = dir_tree
            for part in path_parts[:-1]:
                current = current.setdefault(part, {})
            current[path_parts[-1]] = {
                'path': relative_fpath,
                'coverage': coverage_percentage,
                'hit': num_hit,
                'total': num_executable,
                'missing': sorted(list(executable_lines - hit_lines)) if executable_lines - hit_lines else []
            }

    # ANSI colour helpers
    def _colour_for(pct: float) -> str:
        """Return ANSI colour code for coverage percentage."""
        if pct >= 80.0:
            return "\033[32m"     # green
        if pct >= 50.0:
            return "\033[33m"     # yellow/orange
        return "\033[31m"         # red

    _RESET = "\033[0m"

    # Pretty tree + table printer
    def _bar(percentage: float, width: int = 15) -> str:
        filled = int(width * percentage / 100)
        return "█" * filled + "░" * (width - filled)

    def _print_coverage_tree(tree: dict, indent: int = 0) -> None:
        for name, content in sorted(tree.items()):
            prefix = "  " * indent
            if isinstance(content, dict) and "path" in content:
                # It's a file
                file_data = content
                pct = file_data["coverage"]
                col = _colour_for(pct)
                bar = _bar(pct)
                line = (f"{prefix}{name:<30} "
                        f"{col}{bar}\033[0m "
                        f"{col}{pct:>5.1f}%{_RESET} "
                        f"({file_data['hit']}/{file_data['total']})")
                print(line)

                # Show missing lines if any
                if file_data['missing']:
                    missing_str = ", ".join(map(str, file_data['missing'][:10]))
                    if len(file_data['missing']) > 10:
                        missing_str += f" …({len(file_data['missing'])})"
                    print(f"{prefix}  Missing: {missing_str}")
            else:
                # It's a directory
                print(f"{prefix}📁 {name}/")
                _print_coverage_tree(content, indent + 1)

    # Print the tree
    _print_coverage_tree(dir_tree)

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


def run_coverage_summary(
    write_history_func: Callable[[str, str], None],
    git_manager: Optional[object],
    logger
) -> None:
    """
    Run coverage using unittest discovery from unittest_runner, and print a concise summary:
      - One line per source file: percent, covered/total, and missing count.
      - Final total across all files.
    """
    # Resolve project root (prefer Git root)
    if git_manager and hasattr(git_manager, "is_repo") and git_manager.is_repo():
        root_dir_str = getattr(git_manager, "get_root", lambda: None)()
        root_dir = pathlib.Path(root_dir_str) if root_dir_str else pathlib.Path.cwd()
        if not root_dir_str:
            logger.info(f"Falling back to current working directory: {root_dir}")
    else:
        root_dir = pathlib.Path.cwd()
        logger.info(f"Not in a Git repository. Using current working directory as project root: {root_dir}")

    # Discover source files to instrument (tests are excluded by EXCLUDE_DIRS)
    target_files = find_target_files(str(root_dir))
    if not target_files:
        logger.info("Coverage: No source files found to instrument.")
        write_history_func("tool", "Coverage: No source files found.")
        return

    # Process files to get executable lines and instrumented source
    all_executable_lines: Dict[str, Set[int]] = {}
    instrumented_sources: Dict[str, str] = {}
    for fpath in target_files:
        exec_lines, instrumented_src = process_file(fpath)
        if exec_lines or instrumented_src is not None:
            all_executable_lines[fpath] = exec_lines
        if instrumented_src is not None:
            instrumented_sources[fpath] = instrumented_src

    if not instrumented_sources:
        logger.error("Coverage: No source files could be successfully instrumented.")
        write_history_func("tool", "Coverage: Instrumentation failed for all files.")
        return

    tracker = CoverageTracker()
    hook = CoverageImportHook(instrumented_sources, tracker)

    # Install import hook
    sys.meta_path.insert(0, hook)

    # Build unittest suite using shared discovery logic
    from tinycoder.unittest_runner import _find_test_start_dirs  # local import to avoid cycles
    loader = unittest.TestLoader()
    master_suite = unittest.TestSuite()

    original_sys_path = list(sys.path)
    try:
        if str(root_dir) not in sys.path:
            sys.path.insert(0, str(root_dir))

        start_dirs = _find_test_start_dirs(root_dir)
        if not start_dirs:
            logger.info("Coverage: No test_*.py files found (will report 0% coverage).")

        for start_dir in start_dirs:
            try:
                suite = loader.discover(
                    start_dir=str(start_dir),
                    pattern="test_*.py",
                    top_level_dir=str(root_dir),
                )
                master_suite.addTests(suite)
            except Exception:
                logger.exception(f"Coverage: Error during test discovery in '{start_dir}'. Continuing.")
    finally:
        # Restore sys.path
        sys.path = original_sys_path

    # Run tests (buffered to suppress normal output)
    stream = io.StringIO()
    runner = unittest.TextTestRunner(stream=stream, verbosity=0, buffer=True)
    try:
        runner.run(master_suite)
    finally:
        # Remove import hook
        sys.meta_path = [m for m in sys.meta_path if m is not hook]

    # Compute per-file and overall coverage
    rows: List[Tuple[str, float, int, int, int]] = []
    total_exec = 0
    total_cov = 0

    for f in sorted(instrumented_sources.keys()):
        exec_lines = all_executable_lines.get(f, set())
        if not exec_lines:
            continue
        covered_lines = {lineno for (fpath, lineno) in tracker.hits if fpath == f}
        covered = len(exec_lines & covered_lines)
        total = len(exec_lines)
        missing = total - covered
        pct = (100.0 * covered / total) if total else 100.0
        total_exec += total
        total_cov += covered
        rows.append((f, pct, covered, total, missing))

    # ANSI colour helpers
    def _colour_for(pct: float) -> str:
        """Return ANSI colour code for coverage percentage."""
        if pct >= 80.0:
            return "\033[32m"     # green
        if pct >= 50.0:
            return "\033[33m"     # yellow/orange
        return "\033[31m"         # red

    _RESET = "\033[0m"

    def _bar(percentage: float, width: int = 15) -> str:
        filled = int(width * percentage / 100)
        return "█" * filled + "░" * (width - filled)

    # Log summary
    logger.info("--- Coverage Summary ---")
    for f, pct, covered, total, missing in rows:
        try:
            rel = str(pathlib.Path(f).resolve().relative_to(root_dir.resolve()))
        except Exception:
            rel = f
        col = _colour_for(pct)
        bar = _bar(pct)
        logger.info(f"{col}{bar}\033[0m {rel}: {col}{pct:.1f}%{_RESET} ({covered}/{total}, missing {missing})")

    overall_pct = (100.0 * total_cov / total_exec) if total_exec else 100.0
    logger.info("-" * 60)
    logger.info(f"Total: {overall_pct:.1f}% ({total_cov}/{total_exec}, missing {total_exec - total_cov if total_exec else 0})")

    # Write a compact summary to chat history
    write_history_func(
        "tool",
        f"Coverage: {overall_pct:.1f}% ({total_cov}/{total_exec} lines covered across {len(rows)} file(s))"
    )


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
