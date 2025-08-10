import logging
from pathlib import Path
from typing import List, Set, Iterable, TYPE_CHECKING

from prompt_toolkit.completion import Completer, Completion
from prompt_toolkit.document import Document

if TYPE_CHECKING:
    from tinycoder.file_manager import FileManager
    from tinycoder.git_manager import GitManager


class PTKCommandCompleter(Completer):
    """A prompt_toolkit completer for TinyCoder commands."""

    def __init__(self, file_manager: 'FileManager', git_manager: 'GitManager'):
        self.file_manager = file_manager
        self.git_manager = git_manager
        self.file_options: List[str] = []
        self.logger = logging.getLogger(__name__)
        self._refresh_file_options()

    def _refresh_file_options(self):
        """Fetches the list of relative file paths from the filesystem."""
        try:
            base_path = self.file_manager.root if self.file_manager.root else Path.cwd()
            repo_files: Set[str] = set()
            self.logger.debug(f"Refreshing file options for completion based on: {base_path}")

            # Always scan the filesystem for all available files
            from tinycoder.repo_map import RepoMap
            repo_map = RepoMap(str(base_path))

            # Add Python, HTML, and other common file types
            for py_file in repo_map.get_py_files():
                repo_files.add(str(py_file.relative_to(base_path)).replace('\\', '/'))
            for html_file in repo_map.get_html_files():
                repo_files.add(str(html_file.relative_to(base_path)).replace('\\', '/'))
            
            # Include git-tracked files for completeness
            if self.git_manager and self.git_manager.is_repo():
                tracked_files = self.git_manager.get_tracked_files_relative()
                repo_files.update(tracked_files)

            # Always include current context files
            context_files = self.file_manager.get_files()
            repo_files.update(context_files)
            
            self.file_options = sorted(list(repo_files))
            self.logger.debug(f"Total unique file options for completion: {len(self.file_options)}")

        except Exception as e:
            self.logger.error(f"Error refreshing file options for completion: {e}", exc_info=self.logger.isEnabledFor(logging.DEBUG))
            self.file_options = sorted(list(self.file_manager.get_files()))

    def get_completions(self, document: Document, complete_event) -> Iterable[Completion]:
        """Yields completions for the current input."""
        text_before_cursor = document.text_before_cursor
        
        # Exhaustive list of all available slash commands.
        # Commands expecting an argument have a trailing space.
        commands = [
            "/add ",
            "/clear",
            "/commit",
            "/disable_rule ",
            "/drop ",
            "/edit ",
            "/enable_rule ",
            "/exclude_from_repomap ",
            "/exit",
            "/help",
            "/include_in_repomap ",
            "/lint",
            "/list_exclusions",
            "/log ",
            "/mode ",
            "/quit",
            "/repomap",
            "/rules",
            "/run",
            "/suggest_files",
            "/test",
            "/undo",
        ]

        if ' ' not in text_before_cursor:
             # If we are completing the command itself
            if text_before_cursor.startswith('/'):
                for cmd in commands:
                    if cmd.startswith(text_before_cursor):
                        yield Completion(cmd, start_position=-len(text_before_cursor))
            return

        # Completion for commands with arguments
        words = text_before_cursor.split()
        if not words:
            return

        # File path completion for /add, /drop, /edit
        if words[0] in ("/add", "/drop", "/edit"):
            # Refresh options if user has been idle
            # This is a simple heuristic. A more robust way could use a timer.
            if complete_event.completion_requested:
                self._refresh_file_options()

            path_text = words[1] if len(words) > 1 else ""
            for p in self.file_options:
                if p.startswith(path_text):
                    yield Completion(
                        p,
                        start_position=-len(path_text),
                        display_meta='file'
                    )