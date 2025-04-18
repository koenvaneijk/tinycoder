import ast

from pathlib import Path
from typing import Optional, Generator, List, Tuple, Set



# --- RepoMap Functionality ---
class RepoMap:
    """Generates a simple repository map for Python files using AST."""
    def __init__(self, root: Optional[str], io_print_error):
        self.root = Path(root) if root else Path.cwd()
        self.io_print_error = io_print_error

    def get_py_files(self) -> Generator[Path, None, None]:
        """Yields all .py files in the repository root."""
        for path in self.root.rglob('*.py'):
            # Basic check to exclude common virtual environment/dependency folders
            if '.venv' in path.parts or 'venv' in path.parts or 'node_modules' in path.parts or '.git' in path.parts:
                continue
            if path.is_file():
                yield path

    def get_definitions(self, file_path: Path) -> List[Tuple[str, str, int]]:
        """Extracts top-level function and class definitions from a Python file."""
        definitions = []
        try:
            content = file_path.read_text(encoding='utf-8', errors='replace')
            tree = ast.parse(content, filename=str(file_path))
            for node in ast.iter_child_nodes(tree):
                if isinstance(node, ast.FunctionDef):
                    definitions.append(("Function", node.name, node.lineno))
                elif isinstance(node, ast.ClassDef):
                    definitions.append(("Class", node.name, node.lineno))
        except SyntaxError as e:
            self.io_print_error(f"Syntax error parsing {file_path}: {e}")
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
                map_lines.append(f"\n`{rel_path_str}`:")
                for kind, name, lineno in sorted(definitions, key=lambda x: x[2]):
                    map_lines.append(f"  - {kind} {name} (line {lineno})")
                processed_files += 1

        if processed_files == 0:
            return "" # Return empty if no other python files with definitions found

        # Basic token limiting (very approximate)
        # TODO: Implement a more accurate token counter if needed
        MAX_MAP_LINES = 100 # Limit the number of lines in the map
        if len(map_lines) > MAX_MAP_LINES:
             map_lines = map_lines[:MAX_MAP_LINES]
             map_lines.append("\n... (repository map truncated)")


        return "\n".join(map_lines)
