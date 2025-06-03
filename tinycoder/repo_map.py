import ast
import logging
import json # Added for loading/saving exclusions
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

    _EXCLUSIONS_DIR_NAME = ".tinycoder"
    _EXCLUSIONS_FILE_NAME = "repomap_exclusions.json"

    def __init__(self, root: Optional[str]):
        self.root = Path(root) if root else Path.cwd()
        self.logger = logging.getLogger(__name__)

        self.exclusions_config_path = self.root / self._EXCLUSIONS_DIR_NAME / self._EXCLUSIONS_FILE_NAME
        self.user_exclusions: Set[str] = set()
        self._load_user_exclusions()

        # Shared exclude dirs for file discovery (built-in global ignores)
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
            # Check against self.exclude_dirs (built-in global ignores)
            if any(part in self.exclude_dirs for part in path.parts):
                continue

            # Check against user-defined exclusions
            try:
                rel_path = path.relative_to(self.root)
                if self._is_path_excluded_by_user_config(rel_path):
                    continue
            except ValueError:
                # Should not happen for paths from rglob under self.root
                self.logger.debug(f"Path {path} could not be made relative to {self.root}, skipping user exclusion check.")
                continue
            
            if path.is_file():
                yield path

    def get_html_files(self) -> Generator[Path, None, None]:
        """Yields all .html files in the repository root, excluding common folders."""
        for path in self.root.rglob("*.html"):
            # Check against self.exclude_dirs (built-in global ignores)
            if any(part in self.exclude_dirs for part in path.parts):
                continue

            # Check against user-defined exclusions
            try:
                rel_path = path.relative_to(self.root)
                if self._is_path_excluded_by_user_config(rel_path):
                    continue
            except ValueError:
                self.logger.debug(f"Path {path} could not be made relative to {self.root}, skipping user exclusion check.")
                continue

            if path.is_file():
                yield path

    def _normalize_exclusion_pattern(self, pattern: str) -> str:
        """Normalizes an exclusion pattern string."""
        # Replace backslashes with forward slashes and strip whitespace
        normalized = pattern.replace('\\', '/').strip()
        # Ensure no leading slash for comparison with relative_to results
        if normalized.startswith('/'):
            normalized = normalized[1:]
        # Trailing slash for directories is significant and should be preserved if user provides it.
        return normalized

    def _load_user_exclusions(self) -> None:
        """Loads user-defined exclusions from the project-specific config file."""
        if self.exclusions_config_path.exists():
            try:
                with open(self.exclusions_config_path, "r", encoding="utf-8") as f:
                    exclusions_list = json.load(f)
                if isinstance(exclusions_list, list):
                    self.user_exclusions = {self._normalize_exclusion_pattern(p) for p in exclusions_list if isinstance(p, str)}
                    self.logger.debug(f"Loaded {len(self.user_exclusions)} repomap exclusions from {self.exclusions_config_path}")
                else:
                    self.logger.warning(f"Invalid format in {self.exclusions_config_path}. Expected a JSON list. Ignoring.")
            except FileNotFoundError:
                # This case should be covered by .exists(), but good practice.
                self.logger.debug(f"Repomap exclusions file not found at {self.exclusions_config_path}. No user exclusions loaded.")
            except json.JSONDecodeError:
                self.logger.error(f"Error decoding JSON from {self.exclusions_config_path}. Ignoring user exclusions.")
            except Exception as e:
                self.logger.error(f"Failed to load repomap exclusions from {self.exclusions_config_path}: {e}")
        else:
            self.logger.debug(f"Repomap exclusions file {self.exclusions_config_path} does not exist. No user exclusions loaded.")

    def _save_user_exclusions(self) -> None:
        """Saves the current user-defined exclusions to the project-specific config file."""
        try:
            self.exclusions_config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.exclusions_config_path, "w", encoding="utf-8") as f:
                json.dump(sorted(list(self.user_exclusions)), f, indent=2)
            self.logger.debug(f"Saved {len(self.user_exclusions)} repomap exclusions to {self.exclusions_config_path}")
        except Exception as e:
            self.logger.error(f"Failed to save repomap exclusions to {self.exclusions_config_path}: {e}")

    def add_user_exclusion(self, pattern: str) -> bool:
        """Adds a pattern to user exclusions and saves. Returns True if added, False if already present."""
        normalized_pattern = self._normalize_exclusion_pattern(pattern)
        if not normalized_pattern:
            self.logger.warning("Attempted to add an empty exclusion pattern. Ignoring.")
            return False
        if normalized_pattern in self.user_exclusions:
            return False
        self.user_exclusions.add(normalized_pattern)
        self._save_user_exclusions()
        return True

    def remove_user_exclusion(self, pattern: str) -> bool:
        """Removes a pattern from user exclusions and saves. Returns True if removed, False if not found."""
        normalized_pattern = self._normalize_exclusion_pattern(pattern)
        if not normalized_pattern:
            self.logger.warning("Attempted to remove an empty exclusion pattern. Ignoring.")
            return False
        if normalized_pattern in self.user_exclusions:
            self.user_exclusions.remove(normalized_pattern)
            self._save_user_exclusions()
            return True
        return False

    def get_user_exclusions(self) -> List[str]:
        """Returns a sorted list of current user-defined exclusion patterns."""
        return sorted(list(self.user_exclusions))

    def _is_path_excluded_by_user_config(self, rel_path: Path) -> bool:
        """Checks if a relative path matches any user-defined exclusion pattern."""
        # Convert rel_path to a normalized string (forward slashes, no leading slash)
        # Path.as_posix() ensures forward slashes.
        normalized_rel_path_str = rel_path.as_posix()

        for pattern in self.user_exclusions:
            if pattern.endswith('/'):  # Directory pattern (e.g., "docs/", "tests/fixtures/")
                if normalized_rel_path_str.startswith(pattern):
                    return True
            else:  # File pattern (e.g., "src/main.py", "config.ini")
                if normalized_rel_path_str == pattern:
                    return True
        return False

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
            Tuple[str, str, int, Optional[str]],  # Module definition (kind, name, lineno, doc)
            Tuple[str, str, int, str, Optional[str]],  # Function definition (kind, name, lineno, args, doc)
            Tuple[str, str, int, Optional[str], List[Tuple[str, str, int, str, Optional[str]]]], # Class definition (kind, name, lineno, doc, methods list)
        ]
    ]:
        """
        Extracts module docstring, top-level functions and classes (with methods) from a Python file.
        Returns a list of tuples:
        - ("Module", filename, 0, first_docstring_line)
        - ("Function", name, lineno, args_string, first_docstring_line)
        - ("Class", name, lineno, first_docstring_line, [method_definitions])
          - where method_definitions is list of ("Method", name, lineno, args_string, first_docstring_line)
        """
        definitions = []
        try:
            content = file_path.read_text(encoding="utf-8", errors="replace")
            tree = ast.parse(content, filename=str(file_path))

            # Module docstring
            module_docstring_full = ast.get_docstring(tree, clean=True)
            module_docstring_first_line = self._get_first_docstring_line(module_docstring_full)
            # Only add module entry if it has a docstring to avoid clutter
            if module_docstring_first_line:
                 definitions.append(("Module", file_path.name, 0, module_docstring_first_line))

            for node in ast.iter_child_nodes(tree):
                if isinstance(node, ast.FunctionDef):
                    args_str = self._format_args(node.args)
                    docstring_full = ast.get_docstring(node, clean=True)
                    docstring_first_line = self._get_first_docstring_line(docstring_full)
                    definitions.append(("Function", node.name, node.lineno, args_str, docstring_first_line))
                elif isinstance(node, ast.ClassDef):
                    class_docstring_full = ast.get_docstring(node, clean=True)
                    class_docstring_first_line = self._get_first_docstring_line(class_docstring_full)
                    
                    methods = []
                    for item in node.body:
                        if isinstance(item, ast.FunctionDef): # Methods
                            method_args_str = self._format_args(item.args)
                            method_docstring_full = ast.get_docstring(item, clean=True)
                            method_docstring_first_line = self._get_first_docstring_line(method_docstring_full)
                            methods.append(
                                ("Method", item.name, item.lineno, method_args_str, method_docstring_first_line)
                            )
                    # Sort methods by line number
                    methods.sort(key=lambda x: x[2])
                    definitions.append(("Class", node.name, node.lineno, class_docstring_first_line, methods))
        except SyntaxError:
            # Ignore files with Python syntax errors for the definition map
            pass
        except Exception as e:
            self.logger.error(
                f"Error parsing Python definitions for {file_path}: {e}"
            )
        return definitions

    def _get_first_docstring_line(self, docstring: Optional[str]) -> Optional[str]:
        """Extracts the first non-empty line from the first paragraph of a docstring."""
        if not docstring: # docstring is after ast.get_docstring(clean=True)
            return None
        
        # Split by \n\n to get the first paragraph/summary block.
        first_paragraph = docstring.split("\n\n", 1)[0]
        
        # Take the first line of this paragraph.
        lines_in_first_paragraph = first_paragraph.splitlines()
        if lines_in_first_paragraph:
            # Return the first line, stripped of any leading/trailing whitespace from that line itself.
            return lines_in_first_paragraph[0].strip()
        return None # Should be unreachable if first_paragraph was non-empty

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
        """Generates the repository map string for Python files."""
        map_sections: Dict[str, List[str]] = {
            "Python Files": [],
            # Add more sections later (e.g., "CSS Files")
        }
        processed_py_files = 0
        # processed_html_files = 0 # Removed HTML counter

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
                
                module_docstring_line_str = ""
                # Check if the first definition is a module docstring
                if definitions and definitions[0][0] == "Module":
                    module_entry = definitions.pop(0) # ("Module", filename, 0, docstring)
                    if len(module_entry) > 3 and module_entry[3]: # Check if docstring exists
                        module_docstring_line_str = f" # {module_entry[3]}"
                
                file_map_lines.append(f"\n`{rel_path_str}`:{module_docstring_line_str}")

                # Sort remaining top-level items (functions, classes) by line number
                definitions.sort(key=lambda x: x[2])

                for definition in definitions:
                    kind = definition[0]
                    name = definition[1]
                    # Function: (kind, name, lineno, args_str, docstring_first_line)
                    # Class:    (kind, name, lineno, docstring_first_line, methods)
                    
                    docstring_display_str = ""
                    if kind == "Function":
                        args_str = definition[3]
                        docstring_first_line = definition[4]
                        if docstring_first_line:
                            docstring_display_str = f" # {docstring_first_line}"
                        file_map_lines.append(f"  - def {name}({args_str}){docstring_display_str}")
                    elif kind == "Class":
                        class_docstring_first_line = definition[3]
                        methods = definition[4] # List of method tuples
                        if class_docstring_first_line:
                            docstring_display_str = f" # {class_docstring_first_line}"
                        file_map_lines.append(f"  - class {name}{docstring_display_str}")
                        
                        # Methods list contains: ("Method", name, lineno, args_str, docstring_first_line)
                        for method_tuple in methods:
                            method_name = method_tuple[1]
                            method_args_str = method_tuple[3]
                            method_docstring_first_line = method_tuple[4]
                            
                            method_doc_str = ""
                            if method_docstring_first_line:
                                method_doc_str = f" # {method_docstring_first_line}"
                            file_map_lines.append(
                                f"    - def {method_name}({method_args_str}){method_doc_str}"
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

        # --- HTML Files Processing Removed ---
        # The entire block for processing HTML files has been removed.

        # --- Combine Sections ---
        final_map_lines = []
        total_lines = 0
        # Basic token limiting (very approximate)
        # TODO: Implement a more accurate token counter if needed
        MAX_MAP_LINES = 1000  # Limit the number of lines in the map

        # Add header only if there's content
        if processed_py_files > 0: # Condition updated to only check Python files
            final_map_lines.append("\nRepository Map (other files):")
        else:
            # If no Python files were found or processed, return empty string
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
