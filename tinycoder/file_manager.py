

from pathlib import Path

from typing import Optional, Set

# --- File Manager Class ---
class FileManager:
    """Manages the set of files in the chat context and file operations."""
    def __init__(self, git_root: Optional[str], io_print_error, io_print_info, io_input):
        self.git_root = Path(git_root) if git_root else None
        self.fnames: Set[str] = set() # Stores relative paths
        self.io_print_error = io_print_error
        self.io_print_info = io_print_info
        self.io_input = io_input # For creation confirmation

    def get_abs_path(self, fname: str) -> Optional[Path]:
        """Converts a relative or absolute path string to an absolute Path object,
           validating it's within the project scope (git root or cwd)."""
        path = Path(fname)
        base_path = self.git_root if self.git_root else Path.cwd()

        if path.is_absolute():
            abs_path = path.resolve()
            # Check if it's within the root directory
            try:
                # This works even if self.git_root is None (checks against cwd)
                abs_path.relative_to(base_path)
                return abs_path
            except ValueError:
                 # Allow if it resolves to the same path as the original absolute path intention outside root
                 # This might be needed if the user explicitly provides an absolute path outside the project
                 # but we should be cautious. For now, let's strictly enforce containment.
                 # try:
                 #     if abs_path == Path(fname).resolve():
                 #          return abs_path
                 # except Exception:
                 #      pass
                 self.io_print_error(f"Absolute path is outside the project root ({base_path}): {fname}")
                 return None
        else:
            # Relative path
            abs_path = (base_path / path).resolve()
            # Double-check it's under the base path after resolving symlinks etc.
            try:
                abs_path.relative_to(base_path)
                return abs_path
            except ValueError:
                self.io_print_error(f"Path resolves outside the project root ({base_path}): {fname}")
                return None

    def _get_rel_path(self, abs_path: Path) -> str:
        """Gets the path relative to the git root or cwd."""
        base_path = self.git_root if self.git_root else Path.cwd()
        try:
            return str(abs_path.relative_to(base_path))
        except ValueError:
            # Should not happen if get_abs_path validation is correct, but handle defensively
            return str(abs_path)

    def add_file(self, fname: str):
        """Adds a file to the chat context by its relative or absolute path."""
        abs_path = self.get_abs_path(fname)
        if not abs_path:
             return # Error printed by get_abs_path

        rel_path = self._get_rel_path(abs_path)

        # Check if file exists before adding
        if not abs_path.exists():
             # Ask user if they want to create the file
             create = self.io_input(f"File '{rel_path}' does not exist. Create it? (y/N): ")
             if create.lower() == 'y':
                 if not self.create_file(abs_path):
                     return # Error printed by create_file
             else:
                 self.io_print_info(f"File not added: {rel_path}")
                 return

        if rel_path in self.fnames:
            self.io_print_info(f"File {rel_path} is already in the chat.")
        else:
            self.fnames.add(rel_path)
            self.io_print_info(f"Added {rel_path} to the chat.")
            # Note: History writing is handled by the caller (tinycoder)

    def drop_file(self, fname: str):
        """Removes a file from the chat context by its relative or absolute path."""
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
            self.io_print_info(f"Removed {path_to_remove} from the chat.")
            # Note: History writing is handled by the caller (tinycoder)
        else:
            self.io_print_error(f"File {fname} not found in chat.")

    def get_files(self) -> Set[str]:
        """Returns the set of relative file paths currently in the chat."""
        return self.fnames

    def read_file(self, abs_path: Path) -> Optional[str]:
        """Reads the content of a file given its absolute path."""
        try:
            return abs_path.read_text(encoding='utf-8', errors='replace')
        except Exception as e:
            self.io_print_error(f"Error reading file {abs_path}: {e}")
            return None

    def write_file(self, abs_path: Path, content: str) -> bool:
        """Writes content to a file given its absolute path. Handles line endings."""
        try:
            # Check original line endings if file exists
            original_content = ""
            if abs_path.exists():
                try:
                    # Read bytes to detect line endings reliably
                    with open(abs_path, 'rb') as f:
                        original_bytes = f.read()
                    if b'\r\n' in original_bytes:
                        content = content.replace('\n', '\r\n')
                except Exception:
                    # Fallback if reading bytes fails, use normalized content
                    pass # content remains with \n

            abs_path.parent.mkdir(parents=True, exist_ok=True)
            abs_path.write_text(content, encoding='utf-8')
            return True
        except Exception as e:
            self.io_print_error(f"Error writing file {abs_path}: {e}")
            return False

    def create_file(self, abs_path: Path) -> bool:
        """Creates an empty file if it doesn't exist."""
        try:
            if not abs_path.exists():
                abs_path.parent.mkdir(parents=True, exist_ok=True)
                abs_path.touch()
                self.io_print_info(f"Created empty file: {self._get_rel_path(abs_path)}")
            return True
        except Exception as e:
            self.io_print_error(f"Could not create file {abs_path}: {e}")
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

        for fname in current_fnames: # fname is relative path
            abs_path = self.get_abs_path(fname)
            file_prefix = f"{fname}\n```\n" # Use simple backticks for LLM
            file_suffix = "\n```\n"
            if abs_path and abs_path.exists() and abs_path.is_file():
                content = self.read_file(abs_path)
                if content is not None:
                    all_content.append(file_prefix + content + file_suffix)
                else:
                    error_msg = f"Error reading file (see console)."
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

