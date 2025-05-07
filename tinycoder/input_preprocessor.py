import logging
import re
import ast
from pathlib import Path
from typing import Optional, Set, List, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from tinycoder.git_manager import GitManager
    from tinycoder.repo_map import RepoMap
    from tinycoder.file_manager import FileManager


class InputPreprocessor:
    """Handles preprocessing of user input, including @-mentions and other transformations."""

    def __init__(self, logger: logging.Logger, file_manager: 'FileManager', git_manager: 'GitManager', repo_map: 'RepoMap'):
        """
        Initializes the InputPreprocessor.

        Args:
            logger: The logger instance for logging messages.
            file_manager: FileManager instance for accessing file content and paths.
            git_manager: GitManager instance for accessing Git repository information.
            repo_map: RepoMap instance for project structure information.
        """
        self.logger = logger
        self.file_manager = file_manager
        self.git_manager = git_manager
        self.repo_map = repo_map

    def _extract_code_snippet(self, file_path_str: str, entity_name: str) -> Optional[str]:
        """
        Extracts the source code of a function or class from a given file.
        file_path_str is expected to be a relative path.
        """
        # self.file_manager.get_abs_path() handles resolving relative to git_root or cwd
        abs_path = self.file_manager.get_abs_path(file_path_str)
        
        if not abs_path or not abs_path.exists():
            # This can happen if a file was listed by git/repomap but deleted since,
            # or if the path from git/repomap is somehow inconsistent.
            # self.logger.debug(f"File {file_path_str} (resolved to {abs_path}) not found for code extraction.")
            return None

        try:
            file_content = abs_path.read_text(encoding="utf-8")
            tree = ast.parse(file_content, filename=str(abs_path))

            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    if node.name == entity_name:
                        if hasattr(ast, 'get_source_segment'):
                            snippet = ast.get_source_segment(file_content, node)
                            if snippet:
                                self.logger.debug(f"Extracted snippet for '{entity_name}' from '{file_path_str}'.")
                                return snippet
                        else:
                            self.logger.warning(
                                "ast.get_source_segment not available (requires Python 3.8+). "
                                "Cannot accurately extract code snippet."
                            )
                            return None # Or implement a less accurate fallback
            # self.logger.debug(f"Entity '{entity_name}' not found in '{file_path_str}'.") # Can be too verbose
            return None
        except SyntaxError: # Don't log full trace for syntax errors in user files during scan
            self.logger.debug(f"SyntaxError parsing {file_path_str} for code extraction. Skipping this file for @{entity_name}.")
            return None
        except Exception as e:
            self.logger.error(f"Error extracting code for {entity_name} from {file_path_str}: {e}", exc_info=True)
            return None

    def check_for_file_mentions(self, inp: str):
        """Placeholder: Checks for file mentions in user input."""
        # TODO: Implement logic to find potential file paths in `inp`
        # and maybe suggest adding them or print a warning.
        pass  # Currently does nothing

    def check_for_urls(self, inp: str) -> str:
        """Placeholder: Checks for URLs in user input."""
        # TODO: Implement logic to find URLs. Could potentially fetch content
        # or just return the input string unchanged.
        return inp  # Currently returns input unchanged

    def process(self, inp: str) -> str:
        """
        Processes user input: checks for file mentions, URLs, and @entity mentions.
        For @entity, searches project Python files and injects code snippets.
        """
        original_inp = inp
        modified_inp = inp # Start with original, append snippets later
        
        # 1. @entity mentions
        entity_mentions = re.findall(r'@([a-zA-Z_]\w*)', original_inp)
        
        extracted_snippets_text = []

        if entity_mentions:
            self.logger.debug(f"Found entity mentions: {entity_mentions}")

            all_project_py_files: Set[str] = set()
            source_description = ""

            # Prioritize Git for file listing if available and it's a repo
            if self.git_manager and self.git_manager.is_repo():
                try:
                    tracked_files = self.git_manager.get_tracked_files_relative()
                    all_project_py_files.update(f for f in tracked_files if f.endswith(".py"))
                    source_description = "tracked Git Python files"
                    self.logger.debug(f"Gathered {len(all_project_py_files)} Python files from Git for @-mention search.")
                except Exception as e:
                    self.logger.warning(f"Error getting tracked files from Git: {e}. Falling back to RepoMap.")
                    all_project_py_files.clear() # Clear in case of partial success before error

            # Fallback to RepoMap if Git didn't yield files or isn't applicable
            if not all_project_py_files and self.repo_map: # No need to check self.repo_map.root, get_py_files handles it
                try:
                    repo_map_root_for_rel = self.repo_map.root if self.repo_map.root else Path.cwd()
                    for abs_py_file_path in self.repo_map.get_py_files(): # get_py_files yields absolute Path objects
                        try:
                            # Convert absolute Path to string relative to the root RepoMap used
                            rel_path_str = str(abs_py_file_path.relative_to(repo_map_root_for_rel))
                            all_project_py_files.add(rel_path_str.replace('\\', '/')) # Normalize slashes
                        except ValueError:
                            self.logger.warning(f"Could not make path {abs_py_file_path} relative to {repo_map_root_for_rel}")
                    source_description = "Python files from RepoMap"
                    self.logger.debug(f"Gathered {len(all_project_py_files)} Python files from RepoMap for @-mention search.")
                except Exception as e:
                    self.logger.warning(f"Error getting Python files from RepoMap: {e}")
            
            if not all_project_py_files:
                self.logger.info("No project Python files found (via Git or RepoMap) to search for @-mentions.")
            
            sorted_project_files = sorted(list(all_project_py_files))

            for entity_name in set(entity_mentions): # Process each unique @-mention
                found_details: Optional[Tuple[str, str]] = None # (file_path_str, snippet_content)
                conflicting_files: List[str] = []

                for file_path_str in sorted_project_files:
                    snippet = self._extract_code_snippet(file_path_str, entity_name)
                    if snippet:
                        if found_details is None: 
                            found_details = (file_path_str, snippet)
                        else: 
                            conflicting_files.append(file_path_str)
                
                if found_details:
                    file_path_of_snippet, snippet_content = found_details
                    header = f"\n\n--- Code for @{entity_name} from {file_path_of_snippet} ---\n"
                    footer = f"\n--- End code for @{entity_name} ---\n"
                    extracted_snippets_text.append(header + snippet_content + footer)
                    self.logger.info(f"Successfully injected code for @{entity_name} from {file_path_of_snippet}.")

                    if conflicting_files:
                        self.logger.warning(
                            f"Entity @{entity_name} was also found in other files: {', '.join(conflicting_files)}. "
                            f"Using the version from '{file_path_of_snippet}'."
                        )
                elif sorted_project_files: 
                    self.logger.warning(f"Could not find code for @{entity_name} in any of the {len(sorted_project_files)} project {source_description}.")

        if extracted_snippets_text:
            modified_inp += "".join(extracted_snippets_text)
        
        # Existing file mentions and URLs checks
        self.check_for_file_mentions(modified_inp) 
        modified_inp = self.check_for_urls(modified_inp)

        if modified_inp != original_inp and extracted_snippets_text:
             self.logger.info("Input preprocessed: @-mentions found and code injected.")
        
        return modified_inp