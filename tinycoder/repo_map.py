import ast
import logging
import json # Added for loading/saving exclusions
from html.parser import HTMLParser
from collections import Counter

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

    # --- Nested HTML Parser Classes ---
    # Using nested classes to keep them contained within RepoMap

    class _MiniHTMLSummary(HTMLParser):
        """
        Lightweight HTML summarizer focused on:
        - Title and html[lang]
        - Landmarks (header, nav, main, section, article, aside, footer)
        - Headings: H1, first few H2
        - Assets: stylesheets hrefs, scripts srcs, inline counts
        - Hooks: first few IDs, duplicate IDs, top classes
        - Framework hints via attributes/classes
        - Forms: method, action, and first few inputs (type/name)
        """
        def __init__(self):
            super().__init__(convert_charrefs=True)
            self.in_title = False
            self.title = ""
            self.lang: Optional[str] = None

            self.landmarks: Set[str] = set()
            self.h1: Optional[str] = None
            self.h2: List[str] = []

            self.styles: List[str] = []
            self.inline_style_count = 0
            self.scripts: List[str] = []
            self.inline_script_count = 0

            self.ids: List[str] = []
            self._id_seen: Set[str] = set()
            self.dup_ids: Set[str] = set()
            self.class_counter: Counter[str] = Counter()

            self.forms: List[Dict[str, Union[str, List[Dict[str, str]]]]] = []
            self._current_form: Optional[Dict[str, Union[str, List[Dict[str, str]]]]] = None

            self.attr_flags: Dict[str, bool] = {"alpine": False, "htmx": False, "stimulus": False}

        def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]):
            a = dict(attrs)
            if tag == "html":
                self.lang = a.get("lang") or self.lang

            if tag in {"header", "nav", "main", "section", "article", "aside", "footer"}:
                self.landmarks.add(tag)

            if tag == "title":
                self.in_title = True

            if tag == "link":
                rel = a.get("rel") or ""
                if ("stylesheet" in rel) and ("href" in a):
                    self.styles.append(a["href"])

            if tag == "style":
                self.inline_style_count += 1

            if tag == "script":
                src = a.get("src")
                if src:
                    self.scripts.append(src)
                    if "htmx" in src:
                        self.attr_flags["htmx"] = True
                else:
                    self.inline_script_count += 1

            # IDs and duplicate detection
            if "id" in a:
                i = a["id"]
                if i in self._id_seen:
                    self.dup_ids.add(i)
                else:
                    self._id_seen.add(i)
                    self.ids.append(i)

            # Classes
            cls = a.get("class")
            if cls:
                for c in cls.split():
                    self.class_counter[c] += 1

            # Framework attribute hints
            if any(k.startswith("hx-") for k in a.keys()):
                self.attr_flags["htmx"] = True
            if any(k.startswith("x-") for k in a.keys()):
                self.attr_flags["alpine"] = True
            if "data-controller" in a:
                self.attr_flags["stimulus"] = True

            # Forms and inputs
            if tag == "form":
                self._current_form = {
                    "method": (a.get("method", "GET") or "GET").upper(),
                    "action": a.get("action", "") or "",
                    "inputs": [],
                }
                self.forms.append(self._current_form)
            if tag in {"input", "select", "textarea"} and self._current_form is not None:
                self._current_form["inputs"].append({
                    "type": a.get("type", tag) or tag,
                    "name": a.get("name") or a.get("id") or ""
                })

        def handle_endtag(self, tag: str):
            if tag == "title":
                self.in_title = False
            if tag == "form":
                self._current_form = None

        def handle_data(self, data: str):
            text = data.strip()
            if not text:
                return
            if self.in_title:
                # accumulate title text
                self.title += text
            # Headings
            if self.lasttag == "h1" and not self.h1:
                self.h1 = text
            elif self.lasttag == "h2":
                self.h2.append(text)

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
        """
        Generates a repository map that focuses on files likely to be edited.
        - Always includes Python (current behavior preserved).
        - Adds compact sections for HTML, CSS, JS/TS, JSON, YAML, Dockerfiles, Markdown, and TOML.
        - Applies strict per-section caps and aggregation to handle very large directories (e.g., thousands of HTML files).
        """
        import re
        from collections import defaultdict

        # Sections container
        map_sections: Dict[str, List[str]] = {
            "Python Files": [],
            "HTML Files": [],
            "JS/TS Files": [],
            "CSS Files": [],
            "JSON Files": [],
            "YAML Files": [],
            "Dockerfiles": [],
            "Markdown Files": [],
            "TOML Files": [],
        }

        # Global limits (approximate line budget, final global cap applied later)
        MAX_MAP_LINES = 1000

        # Per-section budgets and behavior
        LARGE_FILE_BYTES = 256 * 1024

        HTML_CFG = dict(max_files=60, max_lines_per_file=12, section_max_lines=200, dir_threshold=20, sample_per_dir=3)
        JS_CFG   = dict(max_files=50, max_lines_per_file=10, section_max_lines=150, dir_threshold=30, sample_per_dir=3)
        CSS_CFG  = dict(max_files=40, max_lines_per_file=8,  section_max_lines=100, dir_threshold=30, sample_per_dir=3)
        JSON_CFG = dict(max_files=20, max_lines_per_file=10, section_max_lines=80,  dir_threshold=50, sample_per_dir=2)
        YAML_CFG = dict(max_files=15, max_lines_per_file=8,  section_max_lines=80,  dir_threshold=30, sample_per_dir=2)
        DOCKER_CFG = dict(max_files=5, max_lines_per_file=10, section_max_lines=50, dir_threshold=10, sample_per_dir=1)
        MD_CFG   = dict(max_files=10, max_lines_per_file=8,  section_max_lines=60,  dir_threshold=50, sample_per_dir=2)
        TOML_CFG = dict(max_files=10, max_lines_per_file=8,  section_max_lines=60,  dir_threshold=50, sample_per_dir=2)

        # Preferred directories to prioritize per type
        HTML_PREF_DIRS = ["templates", "resources/views", "public", "static"]
        JS_PREF_DIRS   = ["src", "static", "assets", "public"]
        CSS_PREF_DIRS  = ["src", "static", "assets", "public"]
        JSON_PREF_DIRS = ["", "config"]
        YAML_PREF_DIRS = ["", "deploy", "docker", ".github/workflows"]
        MD_PREF_DIRS   = ["docs"]
        TOML_PREF_DIRS = ["", "config"]

        # Normalize chat file set to strings as-is (already relative in most cases)
        chat_rel = set(chat_files_rel or set())

        # Helper: get relative path string
        def _rel(path: Path) -> str:
            try:
                return str(path.relative_to(self.root))
            except Exception:
                return str(path)

        # Helper: user/builtin exclusions
        def _is_included(path: Path) -> bool:
            if any(part in self.exclude_dirs for part in path.parts):
                return False
            try:
                rel_path = path.relative_to(self.root)
                if self._is_path_excluded_by_user_config(rel_path):
                    return False
            except ValueError:
                return False
            return path.is_file()

        # Helper: discovery by glob patterns
        def _discover(patterns: List[str]) -> List[Path]:
            seen = set()
            results: List[Path] = []
            for pat in patterns:
                for p in self.root.rglob(pat):
                    if p in seen:
                        continue
                    seen.add(p)
                    if _is_included(p):
                        results.append(p)
            return results

        # Helper: priority key
        def _priority_key(path: Path, pref_dirs: List[str]) -> tuple:
            rel = _rel(path)
            pref = 1
            for d in pref_dirs:
                if not d:
                    continue
                if rel.startswith(d + "/") or f"/{d}/" in rel or rel.endswith("/" + d) or rel == d:
                    pref = 0
                    break
            try:
                mtime = -path.stat().st_mtime
            except Exception:
                mtime = 0
            return (pref, mtime, rel)

        # Helper: render a single file with summarizer and per-section caps.
        def _render_file(path: Path, summarize_fn, cfg: Dict[str, int], section_lines: List[str], used_counts: Dict[str, int]) -> None:
            if used_counts["files"] >= cfg["max_files"]:
                return
            if used_counts["lines"] >= cfg["section_max_lines"]:
                return

            rel = _rel(path)
            # Skip files already in chat
            if rel in chat_rel:
                return

            # Append file header
            section_lines.append(f"\n`{rel}`:")
            used_counts["lines"] += 1

            # Large file shortcut
            try:
                size = path.stat().st_size
            except Exception:
                size = 0
            if size > LARGE_FILE_BYTES:
                if used_counts["lines"] < cfg["section_max_lines"]:
                    section_lines.append("  - (skipped large file)")
                    used_counts["lines"] += 1
                    used_counts["files"] += 1
                return

            # Summarize details
            try:
                details = summarize_fn(path)
            except Exception as e:
                self.logger.debug(f"Summarizer error for {rel}: {e}")
                details = ["  - (error parsing file)"]

            # Limit per-file lines and remaining section budget
            remaining = cfg["section_max_lines"] - used_counts["lines"]
            if remaining <= 0:
                return
            for line in details[: min(cfg["max_lines_per_file"], remaining)]:
                section_lines.append(line)
                used_counts["lines"] += 1
                if used_counts["lines"] >= cfg["section_max_lines"]:
                    break

            used_counts["files"] += 1

        # Helper: build a section with aggregation by directory
        def _build_section(files: List[Path], summarize_fn, cfg: Dict[str, int], pref_dirs: List[str], skip_fn=None) -> List[str]:
            if not files:
                return []

            # Filter out chat files early and skipped patterns
            filtered = []
            for p in files:
                rel = _rel(p)
                if rel in chat_rel:
                    continue
                if skip_fn and skip_fn(p):
                    continue
                filtered.append(p)
            if not filtered:
                return []

            # Sort by priority
            filtered.sort(key=lambda p: _priority_key(p, pref_dirs))

            # Group by directory
            groups: Dict[str, List[Path]] = defaultdict(list)
            for p in filtered:
                try:
                    drel = str(p.parent.relative_to(self.root))
                except Exception:
                    drel = str(p.parent)
                groups[drel].append(p)

            # Sort directories by best priority of their files
            dirs_sorted = sorted(groups.keys(), key=lambda d: _priority_key(groups[d][0], pref_dirs))

            section_lines: List[str] = []
            used_counts = {"files": 0, "lines": 0}

            for d in dirs_sorted:
                if used_counts["files"] >= cfg["max_files"] or used_counts["lines"] >= cfg["section_max_lines"]:
                    break
                files_in_dir = groups[d]
                if len(files_in_dir) > cfg["dir_threshold"]:
                    # Render a few samples
                    for p in files_in_dir[: cfg["sample_per_dir"]]:
                        _render_file(p, summarize_fn, cfg, section_lines, used_counts)
                        if used_counts["files"] >= cfg["max_files"] or used_counts["lines"] >= cfg["section_max_lines"]:
                            break
                    if used_counts["lines"] < cfg["section_max_lines"]:
                        omitted = len(files_in_dir) - min(cfg["sample_per_dir"], len(files_in_dir))
                        section_lines.append(f"  - {d or '.'}/: {omitted} files (omitted)")
                        used_counts["lines"] += 1
                else:
                    for p in files_in_dir:
                        if used_counts["files"] >= cfg["max_files"] or used_counts["lines"] >= cfg["section_max_lines"]:
                            break
                        _render_file(p, summarize_fn, cfg, section_lines, used_counts)

            # If we truncated by file cap, append a truncation notice
            total_candidates = len(filtered)
            if used_counts["files"] < total_candidates and used_counts["lines"] < cfg["section_max_lines"]:
                omitted_total = total_candidates - used_counts["files"]
                section_lines.append(f"  - ... (section truncated; {omitted_total} files omitted)")
            return section_lines

        # Summarizers (cheap, dependency-free)
        def _summarize_html(path: Path) -> List[str]:
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                return ["  - (unreadable)"]

            # Template detection via regex
            TPL_EXTENDS = re.search(r'{%\s*extends\s+["\']([^"\']+)["\']\s*%}', content)
            TPL_INCLUDES = re.findall(r'{%\s*include\s+["\']([^"\']+)["\']\s*%}', content)
            TPL_BLOCKS = re.findall(r'{%\s*block\s+([a-zA-Z0-9_]+)\s*%}', content)
            HAS_INTERP = bool(re.search(r'{{.*?}}', content, re.S))

            # Parse HTML structure
            parser = self._MiniHTMLSummary()
            parser.feed(content)

            def trunc(s: str, max_len: int = 80) -> str:
                if s is None:
                    return ""
                s = str(s)
                return s if len(s) <= max_len else s[: max_len - 3] + "..."

            def detect_frameworks(class_counter: Counter, attr_flags: Dict[str, bool], scripts: List[str]) -> List[str]:
                frameworks = set()
                # Tailwind: utility-like classes or breakpoints
                if any(
                    c.startswith(("text-", "bg-", "mt-", "mb-", "ml-", "mr-", "px-", "py-", "grid", "flex"))
                    or ":" in c
                    for c in class_counter
                ):
                    frameworks.add("Tailwind")
                # Bootstrap
                if any(c.startswith(("container", "row", "col-")) for c in class_counter):
                    frameworks.add("Bootstrap")
                # Foundation
                if "grid-x" in class_counter or "cell" in class_counter:
                    frameworks.add("Foundation")
                # Alpine.js / HTMX / Stimulus
                if attr_flags.get("alpine"):
                    frameworks.add("Alpine")
                if attr_flags.get("htmx") or any("htmx" in (s or "") for s in scripts):
                    frameworks.add("HTMX")
                if attr_flags.get("stimulus"):
                    frameworks.add("Stimulus")
                return sorted(frameworks)

            lines: List[str] = []

            # Line: Title and lang
            title = parser.title.strip() if parser.title else ""
            lang = parser.lang or ""
            if title or lang:
                segs = []
                if title:
                    segs.append(f'Title: "{trunc(title)}"')
                if lang:
                    segs.append(f"lang={lang}")
                lines.append("  - " + ", ".join(segs))

            # Line: Landmarks
            if parser.landmarks:
                order = ["header", "nav", "main", "section", "article", "aside", "footer"]
                lm = [t for t in order if t in parser.landmarks]
                if lm:
                    lines.append("  - Landmarks: " + ", ".join(lm))

            # Line: Headings
            h_parts = []
            if parser.h1:
                h_parts.append(f'H1 "{trunc(parser.h1)}"')
            if parser.h2:
                h2_list = [f'"{trunc(t)}"' for t in parser.h2[:5]]
                h_parts.append(f"H2[{min(len(parser.h2),5)}]: " + ", ".join(h2_list))
            if h_parts:
                lines.append("  - Headings: " + "; ".join(h_parts))

            # Line: Styles
            if parser.styles or parser.inline_style_count:
                styles_list = [trunc(href) for href in parser.styles[:5]]
                style_seg = f"Styles({len(styles_list)}): " + ", ".join(styles_list) if styles_list else "Styles(0)"
                style_seg += f"; inline:{parser.inline_style_count}"
                lines.append("  - " + style_seg)

            # Line: Scripts
            if parser.scripts or parser.inline_script_count:
                scripts_list = [trunc(src) for src in parser.scripts[:5]]
                script_seg = f"Scripts({len(scripts_list)}): " + ", ".join(scripts_list) if scripts_list else "Scripts(0)"
                script_seg += f"; inline:{parser.inline_script_count}"
                lines.append("  - " + script_seg)

            # Line: Hooks (IDs and Classes)
            ids = parser.ids[:5]
            classes_top = parser.class_counter.most_common(5)
            parts = []
            if ids:
                parts.append("IDs[" + str(len(ids)) + "]: " + ", ".join(f"#{i}" for i in ids))
            if parser.dup_ids:
                dups = list(parser.dup_ids)[:3]
                parts.append("Duplicates: " + ", ".join(f"#{d}" for d in dups))
            if classes_top:
                parts.append(
                    "Classes top5: " + ", ".join(f"{name}({count})" for name, count in classes_top)
                )
            if parts:
                lines.append("  - Hooks: " + "; ".join(parts))

            # Line: Frameworks
            frameworks = detect_frameworks(parser.class_counter, parser.attr_flags, parser.scripts)
            if frameworks:
                lines.append("  - Frameworks: " + ", ".join(frameworks))

            # Line: Templates
            tpl_parts = []
            if TPL_EXTENDS:
                tpl_parts.append(f'extends {TPL_EXTENDS.group(1)}')
            if TPL_INCLUDES:
                inc = ", ".join(TPL_INCLUDES[:5]) + (" ..." if len(TPL_INCLUDES) > 5 else "")
                tpl_parts.append(f"includes: {inc}")
            if TPL_BLOCKS:
                blk = ", ".join(TPL_BLOCKS[:5]) + (" ..." if len(TPL_BLOCKS) > 5 else "")
                tpl_parts.append(f"blocks: {blk}")
            if not tpl_parts and HAS_INTERP:
                tpl_parts.append("{{ … }} present")
            if tpl_parts:
                lines.append("  - Templates: " + "; ".join(tpl_parts))

            # Line: Forms (compact)
            if parser.forms:
                form_summaries: List[str] = []
                for f in parser.forms[:2]:
                    method = f.get("method", "GET")
                    action = trunc(f.get("action", ""))
                    inputs = f.get("inputs", [])  # type: ignore
                    inp_parts = []
                    for inp in inputs[:5]:
                        t = inp.get("type", "")
                        n = inp.get("name", "")
                        if n:
                            inp_parts.append(f"{n}[{t}]")
                        else:
                            inp_parts.append(f"[{t}]")
                    form_summaries.append(f"{method} {action} inputs: " + ", ".join(inp_parts))
                lines.append(f"  - Forms({len(parser.forms)}): " + " | ".join(form_summaries))

            # Fall back if nothing captured
            if not lines:
                lines.append("  - (no summary)")
            return lines

        def _summarize_css(path: Path) -> List[str]:
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                return ["  - (unreadable)"]
            # Remove comments
            while "/*" in text and "*/" in text:
                s = text.find("/*")
                e = text.find("*/", s + 2)
                if e == -1:
                    break
                text = text[:s] + text[e + 2 :]
            rules = 0
            media = text.count("@media")
            imports = text.count("@import")
            lines = []
            for part in text.split("}"):
                if "{" not in part:
                    continue
                selector = part.split("{", 1)[0].strip()
                if selector:
                    rules += 1
                    if len(lines) < 10:
                        lines.append(f"  - {selector}")
            prefix = [f"  - rules={rules}, @media={media}, @import={imports}"]
            return prefix + lines

        def _summarize_js(path: Path) -> List[str]:
            try:
                content = path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                return ["  - (unreadable)"]
            funcs = re.findall(r"\\bfunction\\s+(\\w+)\\s*\\(", content)
            classes = re.findall(r"\\bclass\\s+(\\w+)\\b", content)
            exp_funcs = re.findall(r"\\bexport\\s+(?:default\\s+)?function\\s+(\\w+)", content)
            exp_classes = re.findall(r"\\bexport\\s+(?:default\\s+)?class\\s+(\\w+)", content)
            imports = re.findall(r"\\bimport\\b[^\\n]*?from\\s*[\\'\\\"]([^\\'\\\"]+)[\\'\\\"]", content)
            out: List[str] = []
            if funcs:
                s = ", ".join(funcs[:10]) + (" ..." if len(funcs) > 10 else "")
                out.append(f"  - functions: {s}")
            if classes:
                s = ", ".join(classes[:10]) + (" ..." if len(classes) > 10 else "")
                out.append(f"  - classes: {s}")
            if exp_funcs:
                s = ", ".join(exp_funcs[:10]) + (" ..." if len(exp_funcs) > 10 else "")
                out.append(f"  - exported functions: {s}")
            if exp_classes:
                s = ", ".join(exp_classes[:10]) + (" ..." if len(exp_classes) > 10 else "")
                out.append(f"  - exported classes: {s}")
            if imports:
                s = ", ".join(imports[:10]) + (" ..." if len(imports) > 10 else "")
                out.append(f"  - imports: {s}")
            if not out:
                out.append("  - (no top-level outline found)")
            return out

        def _summarize_json(path: Path) -> List[str]:
            try:
                raw = path.read_text(encoding="utf-8", errors="replace")
                data = json.loads(raw)
            except Exception:
                return ["  - (invalid or unreadable JSON)"]
            if not isinstance(data, dict):
                return ["  - (non-object JSON)"]
            
            lines: List[str] = []
            keys = list(data.keys())
            if keys:
                lines.append("  - keys: " + ", ".join(keys[:20]) + (" ..." if len(keys) > 20 else ""))
            
            # Helpers for structure-only schema (no values)
            def _type_name(v: object) -> str:
                if v is None:
                    return "null"
                if isinstance(v, bool):
                    return "boolean"
                # bool is a subclass of int; check bool before number
                if isinstance(v, (int, float)) and not isinstance(v, bool):
                    return "number"
                if isinstance(v, str):
                    return "string"
                if isinstance(v, dict):
                    return "object"
                if isinstance(v, list):
                    return "array"
                return type(v).__name__
            
            def _summarize_object(d: Dict[str, object], subkey_cap: int = 8) -> str:
                try:
                    subkeys = list(d.keys())
                except Exception:
                    return "object"
                if not subkeys:
                    return "object{keys: }"
                head = ", ".join(subkeys[:subkey_cap]) + (" ..." if len(subkeys) > subkey_cap else "")
                return f"object{{keys: {head}}}"
            
            def _summarize_array(a: List[object], sample_cap: int = 50, subkey_cap: int = 8) -> str:
                if not isinstance(a, list):
                    return "array"
                sample = a[:sample_cap]
                if not sample:
                    return "array<empty>"
                kinds = Counter(_type_name(x) for x in sample)
                if len(kinds) == 1:
                    k = next(iter(kinds))
                    if k == "object":
                        union_keys: Set[str] = set()
                        for x in sample:
                            if isinstance(x, dict):
                                union_keys.update(x.keys())
                        union_list = sorted(list(union_keys))
                        if union_list:
                            preview = ", ".join(union_list[:subkey_cap]) + (" ..." if len(union_list) > subkey_cap else "")
                            return f"array<object>{{keys: {preview}}}"
                        return "array<object>"
                    else:
                        return f"array<{k}>"
                else:
                    total = sum(kinds.values())
                    parts = []
                    for k, c in kinds.most_common(3):
                        pct = int(round(100 * c / total)) if total else 0
                        parts.append(f"{k}({pct}%)")
                    return "array<mixed: " + ", ".join(parts) + ">"
            
            def _summarize_top_value(v: object) -> str:
                tn = _type_name(v)
                if tn == "object":
                    return _summarize_object(v)  # type: ignore[arg-type]
                if tn == "array":
                    return _summarize_array(v)   # type: ignore[arg-type]
                return tn
            
            # Schema block: up to 8 top-level keys
            if keys:
                lines.append("  - schema:")
                SCHEMA_CAP = 8
                for k in keys[:SCHEMA_CAP]:
                    try:
                        desc = _summarize_top_value(data[k])
                    except Exception:
                        desc = "unknown"
                    lines.append(f"    - {k}: {desc}")
                if len(keys) > SCHEMA_CAP:
                    lines.append("    - ...")
            
            return lines or ["  - (no details)"]

        def _summarize_yaml(path: Path) -> List[str]:
            # very light line-based scan of top-level keys; detect docker-compose services
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                return ["  - (unreadable)"]
            lines: List[str] = []
            top_keys = []
            for ln in text.splitlines():
                if not ln.strip() or ln.lstrip().startswith("#"):
                    continue
                if ln == ln.lstrip() and ":" in ln:
                    key = ln.split(":", 1)[0].strip().strip('"').strip("'")
                    if key and key not in top_keys:
                        top_keys.append(key)
                if len(top_keys) >= 12:
                    break
            if top_keys:
                lines.append("  - keys: " + ", ".join(top_keys[:12]) + (" ..." if len(top_keys) > 12 else ""))

            if "docker-compose" in path.name or "compose" in path.name:
                # attempt to list services under 'services:'
                services: List[str] = []
                in_services = False
                base_indent = None
                for ln in text.splitlines():
                    if ln.strip().startswith("#"):
                        continue
                    if not in_services and ln.strip().startswith("services:"):
                        in_services = True
                        base_indent = len(ln) - len(ln.lstrip())
                        continue
                    if in_services:
                        if ln.strip() == "":
                            continue
                        indent = len(ln) - len(ln.lstrip())
                        if indent <= (base_indent or 0):
                            break
                        if ":" in ln:
                            svc = ln.split(":", 1)[0].strip()
                            if svc and svc not in services and not svc.startswith("#"):
                                services.append(svc)
                        if len(services) >= 12:
                            break
                if services:
                    lines.append("  - services: " + ", ".join(services[:12]) + (" ..." if len(services) > 12 else ""))
            return lines or ["  - (no details)"]

        def _summarize_dockerfile(path: Path) -> List[str]:
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                return ["  - (unreadable)"]
            lines: List[str] = []
            for ln in text.splitlines():
                s = ln.strip()
                if not s or s.startswith("#"):
                    continue
                up = s.upper()
                if any(up.startswith(k) for k in ["FROM", "WORKDIR", "COPY", "ADD", "EXPOSE", "CMD", "ENTRYPOINT"]):
                    # Keep argument portion short
                    lines.append("  - " + s[:200])
                if len(lines) >= 10:
                    break
            return lines or ["  - (no details)"]

        def _summarize_md(path: Path) -> List[str]:
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                return ["  - (unreadable)"]
            lines: List[str] = []
            for ln in text.splitlines():
                if ln.startswith("#"):
                    # normalize to at most 3 levels for brevity
                    hashes = len(ln) - len(ln.lstrip("#"))
                    title = ln.strip("#").strip()
                    lines.append(f"  - {'#' * min(hashes, 3)} {title}")
                if len(lines) >= 10:
                    break
            return lines or ["  - (no headings)"]

        def _summarize_toml(path: Path) -> List[str]:
            try:
                text = path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                return ["  - (unreadable)"]
            lines: List[str] = []
            tables: List[str] = []
            for ln in text.splitlines():
                s = ln.strip()
                if not s or s.startswith("#"):
                    continue
                if s.startswith("[") and s.endswith("]"):
                    t = s.strip("[]").strip()
                    if t and t not in tables:
                        tables.append(t)
                        if len(tables) >= 10:
                            break
            if tables:
                lines.append("  - tables: " + ", ".join(tables))
            # small special-case for pyproject.toml
            if path.name == "pyproject.toml":
                for ln in text.splitlines():
                    if ln.strip().startswith("name") and "=" in ln:
                        lines.append("  - " + ln.strip()[:200])
                        break
            return lines or ["  - (no details)"]

        # Skip helpers
        def _skip_js_css_minified(path: Path) -> bool:
            n = path.name.lower()
            return n.endswith(".min.js") or n.endswith(".min.css")

        # ------------------------
        # Process Python Files (existing behavior)
        # ------------------------
        processed_py_files = 0
        for file_path in self.get_py_files():
            rel_path_str = _rel(file_path)
            if rel_path_str in chat_rel:
                continue  # Skip files already in chat

            is_test_file = file_path.name.startswith("test_") and file_path.name.endswith(".py")
            all_file_definitions = self.get_definitions(file_path)

            current_file_map_lines_for_this_file = []
            module_docstring_line_str = ""
            definitions_to_process_further = all_file_definitions

            if all_file_definitions and all_file_definitions[0][0] == "Module":
                module_entry = all_file_definitions[0]
                if len(module_entry) > 3 and module_entry[3]:  # Check if docstring exists
                    module_docstring_line_str = f" # {module_entry[3]}"
                definitions_to_process_further = all_file_definitions[1:]

            file_path_display_line = f"\n`{rel_path_str}`:{module_docstring_line_str}"

            if is_test_file:
                file_path_display_line += " # (Test file, further details omitted)"
                current_file_map_lines_for_this_file.append(file_path_display_line)
            else:
                if not module_docstring_line_str and not definitions_to_process_further:
                    continue
                current_file_map_lines_for_this_file.append(file_path_display_line)

                definitions_to_process_further.sort(key=lambda x: x[2])

                for definition in definitions_to_process_further:
                    kind = definition[0]
                    name = definition[1]
                    docstring_display_str = ""
                    if kind == "Function":
                        args_str = definition[3]
                        docstring_first_line = definition[4]
                        if docstring_first_line:
                            docstring_display_str = f" # {docstring_first_line}"
                        current_file_map_lines_for_this_file.append(f"  - def {name}({args_str}){docstring_display_str}")
                    elif kind == "Class":
                        class_docstring_first_line = definition[3]
                        methods = definition[4]
                        if class_docstring_first_line:
                            docstring_display_str = f" # {class_docstring_first_line}"
                        current_file_map_lines_for_this_file.append(f"  - class {name}{docstring_display_str}")
                        for method_tuple in methods:
                            method_name = method_tuple[1]
                            method_args_str = method_tuple[3]
                            method_docstring_first_line = method_tuple[4]
                            method_doc_str = f" # {method_docstring_first_line}" if method_docstring_first_line else ""
                            current_file_map_lines_for_this_file.append(f"    - def {method_name}({method_args_str}){method_doc_str}")

                # Local import information
                local_imports = []
                try:
                    local_imports = find_local_imports_with_entities(file_path, project_root=str(self.root))
                except Exception as e:
                    self.logger.warning(f"Warning: Could not analyze local imports for {rel_path_str}: {e}")

                if local_imports:
                    current_file_map_lines_for_this_file.append("  - Imports:")
                    for imp_statement in local_imports:
                        current_file_map_lines_for_this_file.append(f"    - {imp_statement}")

            if current_file_map_lines_for_this_file:
                map_sections["Python Files"].extend(current_file_map_lines_for_this_file)
                processed_py_files += 1

        # ------------------------
        # Process HTML, JS/TS, CSS, JSON, YAML, Dockerfiles, Markdown, TOML
        # ------------------------
        # HTML files (reuse existing get_html_files)
        html_files = list(self.get_html_files())
        map_sections["HTML Files"] = _build_section(
            html_files, _summarize_html, HTML_CFG, HTML_PREF_DIRS, skip_fn=None
        )

        # JS/TS files
        js_files = _discover(["*.js", "*.jsx", "*.ts", "*.tsx"])
        map_sections["JS/TS Files"] = _build_section(
            js_files, _summarize_js, JS_CFG, JS_PREF_DIRS, skip_fn=_skip_js_css_minified
        )

        # CSS files
        css_files = _discover(["*.css", "*.scss"])
        map_sections["CSS Files"] = _build_section(
            css_files, _summarize_css, CSS_CFG, CSS_PREF_DIRS, skip_fn=_skip_js_css_minified
        )

        # JSON files (prioritize package.json naturally due to name sorting)
        json_files = _discover(["*.json"])
        map_sections["JSON Files"] = _build_section(
            json_files, _summarize_json, JSON_CFG, JSON_PREF_DIRS, skip_fn=None
        )

        # YAML files
        yaml_files = _discover(["*.yml", "*.yaml"])
        map_sections["YAML Files"] = _build_section(
            yaml_files, _summarize_yaml, YAML_CFG, YAML_PREF_DIRS, skip_fn=None
        )

        # Dockerfiles (common naming)
        docker_files = _discover(["Dockerfile", "dockerfile", "Dockerfile.*", "dockerfile.*"])
        map_sections["Dockerfiles"] = _build_section(
            docker_files, _summarize_dockerfile, DOCKER_CFG, ["", "docker"], skip_fn=None
        )

        # Markdown files
        md_files = _discover(["*.md", "*.markdown", "*.MD"])
        map_sections["Markdown Files"] = _build_section(
            md_files, _summarize_md, MD_CFG, MD_PREF_DIRS, skip_fn=None
        )

        # TOML files
        toml_files = _discover(["*.toml"])
        map_sections["TOML Files"] = _build_section(
            toml_files, _summarize_toml, TOML_CFG, TOML_PREF_DIRS, skip_fn=None
        )

        # --- Combine Sections ---
        final_map_lines = []
        total_lines = 0

        # Add header only if there's content anywhere
        has_any_content = any(len(lines) > 0 for lines in map_sections.values())
        if not has_any_content:
            return ""

        final_map_lines.append("\nRepository Map (other files):")

        for section_name in [
            "Python Files",
            "HTML Files",
            "JS/TS Files",
            "CSS Files",
            "JSON Files",
            "YAML Files",
            "Dockerfiles",
            "Markdown Files",
            "TOML Files",
        ]:
            section_lines = map_sections.get(section_name, [])
            if not section_lines:
                continue

            section_header = f"\n--- {section_name} ---"
            if total_lines + 1 < MAX_MAP_LINES:
                final_map_lines.append(section_header)
                total_lines += 1
            else:
                break

            for line in section_lines:
                if total_lines < MAX_MAP_LINES:
                    final_map_lines.append(line)
                    total_lines += 1
                else:
                    break

            if total_lines >= MAX_MAP_LINES:
                break

        if total_lines >= MAX_MAP_LINES:
            final_map_lines.append("\n... (repository map truncated)")

        return "\n".join(final_map_lines)
