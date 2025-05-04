import ast
import sys
import logging
from html.parser import HTMLParser

# Try importing unparse for argument formatting (Python 3.9+)
try:
    from ast import unparse
except ImportError:
    unparse = None  # Fallback if unparse is not available

from pathlib import Path
from typing import Optional, Generator, List, Tuple, Set, Union, Dict

# Import the function to analyze local imports
from .local_import import find_local_imports_with_entities


class RepoMap:
    """Generates a simple repository map for Python files using AST."""

    def __init__(self, root: Optional[str]):
        self.root = Path(root) if root else Path.cwd()
        self.logger = logging.getLogger(__name__)
        # Shared exclude dirs for file discovery
        self.exclude_dirs = {
            ".venv",
            "venv",
            "env",
            "node_modules",
            ".git",
            "__pycache__",
            "build",
            "dist",
            ".tox",
            ".mypy_cache",
            "migrations",
        }

    def get_py_files(self) -> Generator[Path, None, None]:
        """Yields all .py files in the repository root, excluding common folders."""
        for path in self.root.rglob("*.py"):
            # Check against self.exclude_dirs
            if any(part in self.exclude_dirs for part in path.parts):
                continue
            if path.is_file():
                yield path

    def get_html_files(self) -> Generator[Path, None, None]:
        """Yields all .html files in the repository root, excluding common folders."""
        for path in self.root.rglob("*.html"):
            # Check against self.exclude_dirs
            if any(part in self.exclude_dirs for part in path.parts):
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
                arg_str += "=..."  # Indicate default exists
            parts.append(arg_str)
            if args_node.posonlyargs and i == len(args_node.posonlyargs) - 1:
                parts.append("/")  # Positional-only separator

        if args_node.vararg:
            parts.append("*" + args_node.vararg.arg)

        if args_node.kwonlyargs:
            if not args_node.vararg:
                parts.append("*")  # Keyword-only separator if no *args
            kw_defaults_dict = {
                arg.arg: i
                for i, arg in enumerate(args_node.kwonlyargs)
                if i < len(args_node.kw_defaults)
                and args_node.kw_defaults[i] is not None
            }
            for i, arg in enumerate(args_node.kwonlyargs):
                arg_str = arg.arg
                if arg.arg in kw_defaults_dict:
                    arg_str += "=..."  # Indicate default exists
                parts.append(arg_str)

        if args_node.kwarg:
            parts.append("**" + args_node.kwarg.arg)

        return ", ".join(parts)

    def get_definitions(self, file_path: Path) -> List[
        Union[
            Tuple[str, str, int, str],
            Tuple[str, str, int, List[Tuple[str, str, int, str]]],
        ]
    ]:
        """
        Extracts top-level functions and classes (with methods) from a Python file.
        Returns a list of tuples:
        - ("Function", name, lineno, args_string)
        - ("Class", name, lineno, [method_definitions])
          - where method_definitions is list of ("Method", name, lineno, args_string)
        """
        definitions = []
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
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
                            methods.append(
                                ("Method", item.name, item.lineno, method_args_str)
                            )
                    # Sort methods by line number
                    methods.sort(key=lambda x: x[2])
                    definitions.append(("Class", node.name, node.lineno, methods))
        except SyntaxError:
            # Ignore files with Python syntax errors for the definition map
            pass
        except Exception as e:
            self.logger.error(
                f"Error parsing Python definitions for {file_path}: {e}"
            )
        return definitions

    def get_html_structure(self, file_path: Path) -> List[str]:
        """
        Extracts a simplified structure from an HTML file.
        Focuses on key tags, IDs, title, links, and scripts.
        Returns a list of strings representing the structure.
        """
        structure_lines = []
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
            parser = self._HTMLStructureParser()
            parser.feed(content)
            structure_lines = parser.get_structure()
        except Exception as e:
            self.logger.error(f"Error parsing HTML file {file_path}: {e}")
        return structure_lines

    # --- Nested HTML Parser Class ---
    # Using nested class to keep it contained within RepoMap
    class _HTMLStructureParser(HTMLParser):
        def __init__(self, max_depth=5, max_lines=50):
            super().__init__()
            self.structure = []
            self.current_indent = 0
            self.max_depth = max_depth  # Limit nesting depth shown
            self.max_lines = max_lines  # Limit total lines per file
            self.line_count = 0
            # Focus on structurally significant tags + links/scripts
            self.capture_tags = {
                "html",
                "head",
                "body",
                "title",
                "nav",
                "main",
                "section",
                "article",
                "header",
                "footer",
                "form",
                "table",
                "div",
                "span",
                "img",
                "h1",
                "h2",
                "h3",
                "h4",
                "h5",
                "h6",
                "script",
                "link",
            }
            self.tag_stack = []  # Track open tags for indenting

        def handle_starttag(self, tag, attrs):
            if (
                tag in self.capture_tags
                and self.current_indent < self.max_depth
                and self.line_count < self.max_lines
            ):
                attrs_dict = dict(attrs)
                tag_info = f"{'  ' * self.current_indent}<{tag}"
                # Add key attributes
                if "id" in attrs_dict:
                    tag_info += f" id={attrs_dict['id']!r}"
                if (
                    tag == "link"
                    and attrs_dict.get("rel") == "stylesheet"
                    and "href" in attrs_dict
                ):
                    tag_info += f" rel=stylesheet href={attrs_dict['href']!r}"
                elif tag == "script" and "src" in attrs_dict:
                    tag_info += f" src={attrs_dict['src']!r}"
                # elif tag == 'img' and 'src' in attrs_dict: # Optional: include images
                #     tag_info += f" src={attrs_dict['src']!r}"
                elif tag == "form" and "action" in attrs_dict:
                    tag_info += f" action={attrs_dict['action']!r}"

                tag_info += ">"
                self.structure.append(tag_info)
                self.line_count += 1
                self.current_indent += 1
                self.tag_stack.append(tag)

        def handle_endtag(self, tag):
            # Adjust indent based on tag stack
            if self.tag_stack and self.tag_stack[-1] == tag:
                self.tag_stack.pop()
                self.current_indent -= 1

        def handle_data(self, data):
            # Capture title content specifically
            if self.tag_stack and self.tag_stack[-1] == "title":
                title_content = data.strip()
                if title_content and self.line_count < self.max_lines:
                    # Find the opening <title...> tag and append content if possible
                    for i in range(len(self.structure) - 1, -1, -1):
                        # Check if the line starts with <title> or <title id=...> etc.
                        if self.structure[i].strip().startswith("<title"):
                            # Avoid adding duplicate content if parser calls handle_data multiple times
                            if "</title>" not in self.structure[i]:
                                self.structure[i] = (
                                    self.structure[i][:-1] + f">{title_content}</title>"
                                )
                                break
                    # If not appended (e.g., no opening tag captured due to depth), add separately
                    else:
                        self.structure.append(
                            f"{'  ' * self.current_indent}{title_content} (within <title>)"
                        )
                        self.line_count += 1

        def get_structure(self) -> List[str]:
            if self.line_count >= self.max_lines:
                self.structure.append("... (HTML structure truncated)")
            return self.structure

        def feed(self, data: str):
            # Reset state before feeding new data
            self.structure = []
            self.current_indent = 0
            self.tag_stack = []
            self.line_count = 0
            super().feed(data)
            # Handle potential errors during parsing if needed, though base class handles some

    def generate_map(self, chat_files_rel: Set[str]) -> str:
        """Generates the repository map string including Python and HTML."""
        map_sections: Dict[str, List[str]] = {
            "Python Files": [],
            "HTML Files": [],
            # Add more sections later (e.g., "CSS Files")
        }
        processed_py_files = 0
        processed_html_files = 0

        # --- Process Python Files ---
        for file_path in self.get_py_files():
            try:
                rel_path_str = str(file_path.relative_to(self.root))
            except ValueError:
                rel_path_str = str(file_path)  # Keep absolute if not relative

            if rel_path_str in chat_files_rel:
                continue  # Skip files already in chat

            definitions = self.get_definitions(file_path)
            if definitions:
                file_map_lines = []
                # Sort top-level items by line number
                definitions.sort(key=lambda x: x[2])
                file_map_lines.append(f"\n`{rel_path_str}`:")
                for definition in definitions:
                    kind = definition[0]
                    name = definition[1]
                    if kind == "Function":
                        args_str = definition[3]
                        file_map_lines.append(f"  - def {name}({args_str})")
                    elif kind == "Class":
                        methods = definition[3]
                        file_map_lines.append(f"  - class {name}")
                        for (
                            method_kind,
                            method_name,
                            method_lineno,
                            method_args_str,
                        ) in methods:
                            file_map_lines.append(
                                f"    - def {method_name}({method_args_str})"
                            )

                # --- Add Local Import Information ---
                local_imports = []
                try:
                    # Pass self.root as the project_root for relative path calculation
                    local_imports = find_local_imports_with_entities(
                        file_path, project_root=str(self.root)
                    )
                except Exception as e:
                    self.logger.warning(
                        f"Warning: Could not analyze local imports for {rel_path_str}: {e}",
                    )

                if local_imports:
                    file_map_lines.append("  - Imports:")
                    for imp_statement in local_imports:
                        file_map_lines.append(f"    - {imp_statement}")
                # --- End Local Import Information ---

                map_sections["Python Files"].extend(file_map_lines)
                processed_py_files += 1

        # --- Process HTML Files ---
        for file_path in self.get_html_files():
            try:
                rel_path_str = str(file_path.relative_to(self.root))
            except ValueError:
                rel_path_str = str(file_path)

            if rel_path_str in chat_files_rel:
                continue

            structure = self.get_html_structure(file_path)
            if structure:
                file_map_lines = [f"\n`{rel_path_str}`:"] + structure
                # map_sections["HTML Files"].extend(file_map_lines) TODO FIX
                processed_html_files += 1

        # --- Combine Sections ---
        final_map_lines = []
        total_lines = 0
        # Basic token limiting (very approximate)
        # TODO: Implement a more accurate token counter if needed
        MAX_MAP_LINES = 1000  # Limit the number of lines in the map

        # Add header only if there's content
        if processed_py_files > 0 or processed_html_files > 0:
            final_map_lines.append("\nRepository Map (other files):")
        else:
            # If no files were found or processed in any category, return empty string
            return ""

        for section_name, section_lines in map_sections.items():
            if not section_lines:
                continue

            # Add section header only if it has content
            section_header = f"\n--- {section_name} ---"
            if total_lines + 1 < MAX_MAP_LINES:
                final_map_lines.append(section_header)
                total_lines += 1
            else:
                break  # Stop adding sections if map limit is reached

            for line in section_lines:
                if total_lines < MAX_MAP_LINES:
                    final_map_lines.append(line)
                    total_lines += 1
                else:
                    break  # Stop adding lines within a section if map limit is reached
            if total_lines >= MAX_MAP_LINES:
                break  # Stop processing sections

        if total_lines >= MAX_MAP_LINES:
            final_map_lines.append("\n... (repository map truncated)")

        self.logger.info("Repo map: " + str(len("\n".join(final_map_lines)) / 4) + " tokens")

        return "\n".join(final_map_lines)
