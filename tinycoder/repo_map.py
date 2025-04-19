import ast

# Try importing unparse for argument formatting (Python 3.9+)
try:
    from ast import unparse
except ImportError:
    unparse = None # Fallback if unparse is not available

from pathlib import Path
from typing import Optional, Generator, List, Tuple, Set, Union

class RepoMap:
    """Generates a simple repository map for Python files using AST."""
    def __init__(self, root: Optional[str], io_print_error):
        self.root = Path(root) if root else Path.cwd()
        self.io_print_error = io_print_error

    def get_py_files(self) -> Generator[Path, None, None]:
        """Yields all .py files in the repository root, excluding common virtual env/build/git folders."""
        exclude_dirs = {'.venv', 'venv', 'node_modules', '.git', '__pycache__', 'build', 'dist', '.tox', '.mypy_cache'}
        for path in self.root.rglob('*.py'):
            if any(part in exclude_dirs for part in path.parts):
                continue
            if path.is_file():
                yield path

    def _format_args(self, args_node: ast.arguments) -> str:
        """Formats ast.arguments into a string."""
        if unparse:
            try:
                # Use ast.unparse if available (Python 3.9+)
                return unparse(args_node)
            except Exception:
                # Fallback if unparse fails for some reason
                pass

        # Manual formatting as a fallback or for older Python versions
        parts = []
        # Combine posonlyargs and args, tracking defaults
        all_args = args_node.posonlyargs + args_node.args
        defaults_start = len(all_args) - len(args_node.defaults)
        for i, arg in enumerate(all_args):
            arg_str = arg.arg
            if i >= defaults_start:
                # Cannot easily represent the default value without unparse
                 arg_str += "=..." # Indicate default exists
            parts.append(arg_str)
            if args_node.posonlyargs and i == len(args_node.posonlyargs) - 1:
                parts.append('/') # Positional-only separator

        if args_node.vararg:
            parts.append("*" + args_node.vararg.arg)

        if args_node.kwonlyargs:
            if not args_node.vararg:
                 parts.append('*') # Keyword-only separator if no *args
            kw_defaults_dict = {arg.arg: i for i, arg in enumerate(args_node.kwonlyargs) if i < len(args_node.kw_defaults) and args_node.kw_defaults[i] is not None}
            for i, arg in enumerate(args_node.kwonlyargs):
                arg_str = arg.arg
                if arg.arg in kw_defaults_dict:
                   arg_str += "=..." # Indicate default exists
                parts.append(arg_str)

        if args_node.kwarg:
            parts.append("**" + args_node.kwarg.arg)

        return ", ".join(parts)


    def get_definitions(self, file_path: Path) -> List[Union[Tuple[str, str, int, str], Tuple[str, str, int, List[Tuple[str, str, int, str]]]]]:
        """
        Extracts top-level functions and classes (with methods) from a Python file.
        Returns a list of tuples:
        - ("Function", name, lineno, args_string)
        - ("Class", name, lineno, [method_definitions])
          - where method_definitions is list of ("Method", name, lineno, args_string)
        """
        definitions = []
        try:
            content = file_path.read_text(encoding='utf-8', errors='replace')
            tree = ast.parse(content, filename=str(file_path))
            for node in ast.iter_child_nodes(tree):
                if isinstance(node, ast.FunctionDef):
                    args_str = self._format_args(node.args)
                    definitions.append(("Function", node.name, node.lineno, args_str))
                elif isinstance(node, ast.ClassDef):
                    methods = []
                    for item in node.body:
                        if isinstance(item, ast.FunctionDef):
                            method_args_str = self._format_args(item.args)
                            methods.append(("Method", item.name, item.lineno, method_args_str))
                    # Sort methods by line number
                    methods.sort(key=lambda x: x[2])
                    definitions.append(("Class", node.name, node.lineno, methods))
        except SyntaxError as e:
            # Don't print error here, let caller handle if needed
            # self.io_print_error(f"Syntax error parsing {file_path}: {e}")
            pass # Ignore files with syntax errors for the map
        except Exception as e:
            self.io_print_error(f"Error parsing {file_path}: {e}")
        return definitions

    def generate_map(self, chat_files_rel: Set[str]) -> str:
        """Generates the repository map string."""
        map_lines = []
        map_lines.append("\nRepository Map (other Python files):")

        processed_files = 0
        for file_path in self.get_py_files():
            try:
                rel_path_str = str(file_path.relative_to(self.root))
            except ValueError:
                rel_path_str = str(file_path) # Keep absolute if not relative

            if rel_path_str in chat_files_rel:
                continue # Skip files already in chat

            definitions = self.get_definitions(file_path)
            if definitions:
                # Sort top-level items by line number
                definitions.sort(key=lambda x: x[2])
                map_lines.append(f"\n`{rel_path_str}`:")
                for definition in definitions:
                    kind = definition[0]
                    name = definition[1]
                    if kind == "Function":
                        args_str = definition[3]
                        map_lines.append(f"  - def {name}({args_str})")
                    elif kind == "Class":
                        methods = definition[3]
                        map_lines.append(f"  - class {name}")
                        for method_kind, method_name, method_lineno, method_args_str in methods:
                             map_lines.append(f"    - def {method_name}({method_args_str})")

                processed_files += 1

        if processed_files == 0 and not any(self.get_py_files()):
             # Only return empty if there were truly no python files found (excluding skipped ones)
             # or if none of the found files had definitions *and* no parsing errors occurred.
             # If parsing errors occurred, it's better to return the partial map or just the header.
             pass # Let it return the header line if there were errors or skipped files

        if processed_files == 0 and not map_lines: # Should only happen if no files found at all
            return "" # Return empty if no other python files with definitions found

        # Basic token limiting (very approximate)
        # TODO: Implement a more accurate token counter if needed
        MAX_MAP_LINES = 1000 # Limit the number of lines in the map
        if len(map_lines) > MAX_MAP_LINES:
             map_lines = map_lines[:MAX_MAP_LINES]
             map_lines.append("\n... (repository map truncated)")


        return "\n".join(map_lines)
