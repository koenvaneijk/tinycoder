import logging
from pathlib import Path
from typing import List, Set, Optional

# readline is not available on all platforms (e.g., standard Windows cmd)
try:
    import readline
    READLINE_AVAILABLE = True
except ImportError:
    READLINE_AVAILABLE = False

if READLINE_AVAILABLE: # Guard readline-specific parts
    # The following import is only needed if READLINE_AVAILABLE is True,
    # but type checkers might complain if 'readline' is used conditionally without a type.
    # However, we only call readline methods if READLINE_AVAILABLE is True.
    pass


# Forward declarations for type hinting
if False:
    from tinycoder.file_manager import FileManager
    from tinycoder.git_manager import GitManager


class CommandCompleter:
    """A readline completer class specifically for TinyCoder commands."""
    def __init__(self, file_manager: 'FileManager', git_manager: 'GitManager'):
        self.file_manager = file_manager
        self.file_options: List[str] = []
        self.matches: List[str] = []
        self.logger = logging.getLogger(__name__)
        self.git_manager = git_manager
        
        self._refresh_file_options()

    def _refresh_file_options(self):
        """Fetches the list of relative file paths from the FileManager."""
        try:
            base_path = self.file_manager.root if self.file_manager.root else Path.cwd()
            repo_files: Set[str] = set()
            self.logger.debug(f"Refreshing file options for completion based on: {base_path}")

            if self.git_manager and self.git_manager.is_repo():
                tracked_files = self.git_manager.get_tracked_files_relative()
                repo_files.update(tracked_files)
                self.logger.debug(f"Found {len(tracked_files)} tracked files via Git.")
            else:
                # Fallback: Walk the directory if not a git repo or git failed
                self.logger.debug("Not a Git repo or Git unavailable, walking the directory...")
                excluded_dirs = {'.git', '__pycache__', 'node_modules', '.venv', 'venv', '.tox', 'dist', 'build', 'eggs', '*.egg-info'}
                for item in base_path.rglob('*'):
                    if any(excluded_dir in item.parts for excluded_dir in excluded_dirs):
                        continue
                    if item.is_file():
                        try:
                            rel_path = item.relative_to(base_path)
                            repo_files.add(str(rel_path).replace('\\', '/'))
                        except ValueError:
                            self.logger.warning(f"Could not make path relative: {item}")
                        except Exception as walk_err:
                            self.logger.warning(f"Error processing path during walk: {item} - {walk_err}")
                self.logger.debug(f"Found {len(repo_files)} files via directory walk.")

            context_files = self.file_manager.get_files()
            repo_files.update(context_files)
            if context_files:
                 self.logger.debug(f"Added {len(context_files)} files from current chat context.")

            self.file_options = sorted(list(repo_files))
            self.logger.debug(f"Total unique file options for completion: {len(self.file_options)}")

        except Exception as e:
            self.logger.error(f"Error refreshing file options for completion: {e}", exc_info=True)
            self.file_options = sorted(list(self.file_manager.get_files()))


    def complete(self, text: str, state: int) -> Optional[str]:
        """Readline completion handler."""
        if not READLINE_AVAILABLE:
            return None

        if state == 0:
             self._refresh_file_options()

        line = readline.get_line_buffer()
        self.logger.debug(f"Readline complete called. Line: '{line}', Text: '{text}', State: {state}")

        add_prefix = "/add "
        if line.startswith(add_prefix):
            path_text = line[len(add_prefix):]

            if state == 0:
                self.matches = sorted([
                    p for p in self.file_options
                    if p.startswith(path_text)
                ])
                self.logger.debug(f"Path text: '{path_text}', Options: {len(self.file_options)}, Matches found: {len(self.matches)}")
                self.logger.debug(f"Matches: {self.matches[:5]}...")

            try:
                match = self.matches[state]
                self.logger.debug(f"Returning match {state}: '{match}' (relative to path_text: '{path_text}')")
                return match
            except IndexError:
                self.logger.debug(f"No more matches for state {state}")
                return None

        self.matches = []
        return None