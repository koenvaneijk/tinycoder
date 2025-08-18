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

        text_before_cursor_stripped = text_before_cursor.lstrip()
        words = text_before_cursor_stripped.split()

        # If we are completing the command itself
        if len(words) <= 1 and not text_before_cursor.endswith(' '):
            if text_before_cursor_stripped.startswith('/'):
                command_text = words[0] if words else ""
                for cmd in commands:
                    if cmd.startswith(command_text):
                        yield Completion(cmd, start_position=-len(command_text))
            return

        # If we are completing arguments
        if not words:
            return

        command = words[0]
        arg_text = words[-1] if len(words) > 1 and not text_before_cursor.endswith(' ') else ""

        # --- Argument Completion Logic ---

        # File path completion for /add, /drop, /edit
        if command in ("/add", "/drop", "/edit"):
            if complete_event.completion_requested:
                self._refresh_file_options()
            for p in self.file_options:
                if p.startswith(arg_text):
                    yield Completion(
                        p,
                        start_position=-len(arg_text),
                        display_meta='file'
                    )
        
        # Mode completion
        elif command == "/mode":
            modes = ["code", "ask"]
            for m in modes:
                if m.startswith(arg_text):
                    yield Completion(
                        m,
                        start_position=-len(arg_text),
                        display_meta='mode'
                    )