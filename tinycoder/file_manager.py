import logging
from pathlib import Path
from typing import Optional, Set, Callable

from tinycoder.ui.console_interface import ring_bell

class FileManager:
    """Manages the set of files in the chat context and file operations."""

    def __init__(self, root: Optional[str], io_input: Callable[[str], str]):
        """
        Initializes the FileManager.

        Args:
            root: The root directory of the project (usually git root).
            io_input: A callable for getting user input (e.g., for confirmations).
            logger_instance: An optional custom logger instance. If None, uses the module logger.
        """
        self.root: Optional[Path] = Path(root) if root else None
        self.fnames: Set[str] = set()  # Stores relative paths
        self.io_input: Callable[[str], str] = io_input  # For creation confirmation
        self.logger = logging.getLogger(__name__)

    def get_abs_path(self, fname: str) -> Optional[Path]:
        """Converts a relative or absolute path string to an absolute Path object,
        validating it's within the project scope (git root or cwd)."""
        path = Path(fname)
        base_path = self.root if self.root else Path.cwd()

        if path.is_absolute():
            abs_path = path.resolve()
            # Check if it's within the root directory
            try:
                abs_path.relative_to(base_path)
                return abs_path
            except ValueError:
                self.logger.error(
                    f"Absolute path is outside the project root ({base_path}): {fname}"
                )
                return None
        else:
            # Relative path
            abs_path = (base_path / path).resolve()
            # Double-check it's under the base path after resolving symlinks etc.
            try:
                abs_path.relative_to(base_path)
                return abs_path
            except ValueError:
                self.logger.error(
                    f"Path resolves outside the project root ({base_path}): {fname}"
                )
                return None

    def _get_rel_path(self, abs_path: Path) -> str:
        """Gets the path relative to the git root or cwd."""
        base_path = self.root if self.root else Path.cwd()
        try:
            return str(abs_path.relative_to(base_path))
        except ValueError:
            # Should not happen if get_abs_path validation is correct, but handle defensively
            return str(abs_path)

    def add_file(self, fname: str) -> bool:
        """
        Adds a file to the chat context by its relative or absolute path.
        Returns True if the file was successfully added or already existed, False otherwise.
        """
        abs_path = self.get_abs_path(fname)
        if not abs_path:
            return False  # Error printed by get_abs_path

        rel_path = self._get_rel_path(abs_path)

        # Check if file exists before adding
        if not abs_path.exists():
            # Ask user if they want to create the file
            ring_bell()
            create = self.io_input(
                f"FILE: '{rel_path}' does not exist. Create it? (y/N): "
            )
            if create.lower() == "y":
                if not self.create_file(abs_path):
                    return False  # Error logged by create_file
                # File created successfully, proceed to add it to fnames
            else:
                self.logger.info(f"File creation declined by user: {rel_path}")
                return False  # User declined creation

        if rel_path in self.fnames:
            self.logger.info(f"File {rel_path} is already in the chat context.")
            return True  # Already added counts as success for the caller
        else:
            self.fnames.add(rel_path)
            self.logger.info(f"Added {rel_path} to the chat context.")
            # Note: History writing is handled by the caller (tinycoder)
            return True  # Successfully added

    def drop_file(self, fname: str) -> bool:
        """
        Removes a file from the chat context by its relative or absolute path.
        Returns True if successfully removed, False otherwise.
        """
        path_to_remove = None
        # Check if the exact string provided is in fnames (could be relative or absolute if outside root)
        if fname in self.fnames:
            path_to_remove = fname
        else:
            # If not found directly, resolve it and check again using the relative path
            abs_path = self.get_abs_path(fname)
            if abs_path:
                rel_path = self._get_rel_path(abs_path)
                if rel_path in self.fnames:
                    path_to_remove = rel_path

        if path_to_remove:
            self.fnames.remove(path_to_remove)
            self.logger.info(f"Removed {path_to_remove} from the chat context.")
            # Note: History writing is handled by the caller (tinycoder)
            return True # Successfully removed
        else:
            self.logger.error(f"File {fname} not found in chat context for removal.")
            return False # Not found or other error

    def get_files(self) -> Set[str]:
        """Returns the set of relative file paths currently in the chat."""
        return self.fnames

    def read_file(self, abs_path: Path) -> Optional[str]:
        """Reads the content of a file given its absolute path."""
        try:
            return abs_path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            self.logger.error(f"Error reading file {abs_path}: {e}")
            return None

    def write_file(self, abs_path: Path, content: str) -> bool:
        """Writes content to a file given its absolute path. Handles line endings."""
        try:
            # Check original line endings if file exists
            original_content = ""
            if abs_path.exists():
                try:
                    # Read bytes to detect line endings reliably
                    with open(abs_path, "rb") as f:
                        original_bytes = f.read()
                    if b"\r\n" in original_bytes:
                        content = content.replace("\n", "\r\n")
                except Exception:
                    # Fallback if reading bytes fails, use normalized content
                    pass  # content remains with \n

            abs_path.parent.mkdir(parents=True, exist_ok=True)
            abs_path.write_text(content, encoding="utf-8")
            return True
        except Exception as e:
            self.logger.error(f"Error writing file {abs_path}: {e}")
            return False

    def create_file(self, abs_path: Path) -> bool:
        """Creates an empty file if it doesn't exist."""
        try:
            if not abs_path.exists():
                abs_path.parent.mkdir(parents=True, exist_ok=True)
                abs_path.touch()
                self.logger.info(
                    f"Created empty file: {self._get_rel_path(abs_path)}"
                )
            return True
        except Exception as e:
            self.logger.error(f"Could not create file {abs_path}: {e}")
            return False

    def get_content_for_llm(self) -> str:
        """
        Reads content of all files currently in the chat, formatted for the LLM.
        Handles errors gracefully.
        """
        all_content = []
        current_fnames = sorted(list(self.get_files()))

        if not current_fnames:
            return "No files are currently added to the chat."

        all_content.append("Here is the current content of the files:\n")

        for fname in current_fnames:  # fname is relative path
            abs_path = self.get_abs_path(fname)
            file_prefix = f"{fname}\n```\n"  # Use simple backticks for LLM
            file_suffix = "\n```\n"
            if abs_path and abs_path.exists() and abs_path.is_file():
                try:
                    # Read a small chunk first to check for binary content
                    with open(abs_path, "rb") as f_bin:
                        chunk = f_bin.read(1024)
                    if b"\0" in chunk:
                        self.logger.warning(
                            f"File {fname} appears to be binary, omitting content for LLM."
                        )
                        all_content.append(
                            file_prefix + "(Binary file content omitted)" + file_suffix
                        )
                        continue  # Skip to the next file

                    # If not binary-like, read as text
                    content = self.read_file(
                        abs_path
                    )  # read_file handles potential UnicodeDecodeError
                    if content is not None:
                        all_content.append(file_prefix + content + file_suffix)
                    else:
                        # Error message already logged by read_file
                        error_msg = f"(Error reading file, check logs)"
                        all_content.append(file_prefix + error_msg + file_suffix)
                except Exception as e:
                    # Catch potential errors during the binary check read itself
                    self.logger.error(
                        f"Error checking file {fname} for binary content: {e}"
                    )
                    error_msg = f"(Error reading file, check logs)"
                    all_content.append(file_prefix + error_msg + file_suffix)

            else:
                not_found_msg = "File not found or is not a regular file."
                # Check if it was just created and empty
                if abs_path and not abs_path.exists():
                    not_found_msg = "[New file, created empty]"
                elif abs_path and abs_path.is_file() and abs_path.stat().st_size == 0:
                    not_found_msg = "[File is empty]"

                all_content.append(file_prefix + not_found_msg + file_suffix)

        return "\n".join(all_content)
