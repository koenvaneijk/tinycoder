import logging
import sqlite3
from pathlib import Path
from typing import Optional, Set, Callable

from tinycoder.notebook_converter import ipynb_to_py, py_to_ipynb
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
        """
        Reads the content of a file. For .ipynb files, it converts them to a
        Python script representation.
        """
        if abs_path.suffix.lower() == ".ipynb":
            self.logger.debug(f"Reading '{abs_path}' as Jupyter Notebook.")
            try:
                notebook_json_content = abs_path.read_text(
                    encoding="utf-8", errors="replace"
                )
                return ipynb_to_py(notebook_json_content)
            except Exception as e:
                self.logger.error(f"Error reading or converting notebook {abs_path}: {e}")
                return None
        else:
            try:
                return abs_path.read_text(encoding="utf-8", errors="replace")
            except Exception as e:
                self.logger.error(f"Error reading file {abs_path}: {e}")
                return None

    def write_file(self, abs_path: Path, content: str) -> bool:
        """
        Writes content to a file. For .ipynb files, it converts the Python script
        representation back to the notebook JSON format.
        """
        try:
            abs_path.parent.mkdir(parents=True, exist_ok=True)

            if abs_path.suffix.lower() == ".ipynb":
                self.logger.debug(f"Writing to '{abs_path}' as Jupyter Notebook.")
                # Read original to preserve metadata. py_to_ipynb handles non-existent files.
                original_notebook_content = ""
                if abs_path.exists():
                    try:
                        original_notebook_content = abs_path.read_text(
                            encoding="utf-8", errors="replace"
                        )
                    except Exception as e:
                        self.logger.warning(
                            f"Could not read original notebook {abs_path} to preserve metadata: {e}"
                        )

                final_json_content = py_to_ipynb(content, original_notebook_content)
                # py_to_ipynb produces a JSON string with '\n'. No special handling needed.
                abs_path.write_text(final_json_content, encoding="utf-8")

            else:
                # Original logic for other files, slightly improved
                final_content = content
                if abs_path.exists():
                    try:
                        # Read a chunk of bytes to detect line endings reliably
                        with open(abs_path, "rb") as f:
                            original_bytes = f.read(4096)
                        if b"\r\n" in original_bytes:
                            # Assuming content is normalized to '\n', convert to '\r\n'
                            final_content = content.replace("\n", "\r\n")
                    except Exception:
                        # Fallback if reading bytes fails, use normalized content
                        pass  # content remains with \n

                abs_path.write_text(final_content, encoding="utf-8")

            return True
        except Exception as e:
            self.logger.error(f"Error writing file {abs_path}: {e}")
            return False

    def _read_db_summary(self, db_path: Path) -> str:
        """Reads a SQLite DB and returns a summary of schema and sample data."""
        summary_lines = [f"# Summary for SQLite database: {db_path.name}"]
        try:
            # Connect in read-only mode to prevent locking or accidental writes
            db_uri = f'file:{db_path}?mode=ro'
            conn = sqlite3.connect(db_uri, uri=True)
            cursor = conn.cursor()

            # Get all user table names
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%';")
            tables = [row[0] for row in cursor.fetchall()]

            if not tables:
                conn.close()
                return f"# Database '{db_path.name}' contains no user tables."

            for table_name in tables:
                # Get the CREATE TABLE statement (schema)
                summary_lines.append(f"\n# Schema for table: {table_name}")
                cursor.execute(f"SELECT sql FROM sqlite_master WHERE type='table' AND name='{table_name}';")
                schema = cursor.fetchone()[0]
                summary_lines.append(schema)

                # Get column names for a header
                cursor.execute(f'PRAGMA table_info("{table_name}")')
                columns = [info[1] for info in cursor.fetchall()]

                # Get the first 3 rows of data
                summary_lines.append(f"\n# First 3 rows from table: {table_name}")
                summary_lines.append("# " + " | ".join(columns)) # Header
                
                cursor.execute(f'SELECT * FROM "{table_name}" LIMIT 3;')
                for row in cursor.fetchall():
                    str_row = [str(val) if val is not None else "NULL" for val in row]
                    summary_lines.append("# " + " | ".join(str_row))
            
            conn.close()
        
        except sqlite3.DatabaseError as e:
            # Handle cases where the file isn't a valid DB or is encrypted
            self.logger.warning(f"Could not read SQLite DB summary for {db_path.name}: {e}")
            return f"# Could not read SQLite DB summary for '{db_path.name}': {e}"
        except Exception as e:
            self.logger.error(f"An unexpected error occurred reading DB {db_path.name}: {e}")
            return f"# An unexpected error occurred reading DB '{db_path.name}': {e}"

        return "\n".join(summary_lines)

    def get_db_summary(self, db_path_str: str) -> Optional[str]:
        """
        Public method to get a summary for a given database file path.
        Returns the summary string or None if the file is invalid.
        """
        abs_path = self.get_abs_path(db_path_str)
        if not abs_path or not abs_path.exists():
            # get_abs_path logs an error if path is invalid/out of scope
            # We add one here in case it's valid but doesn't exist
            if not (abs_path and abs_path.exists()):
                 self.logger.error(f"Database file not found: {db_path_str}")
            return None
        if abs_path.suffix.lower() not in ['.db', '.sqlite', '.sqlite3']:
            self.logger.error(f"File is not a recognized SQLite database: {db_path_str}")
            return None
        
        return self._read_db_summary(abs_path)

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
                # Handle SQLite databases by providing a schema and data summary
                if abs_path.suffix.lower() in ['.db', '.sqlite', '.sqlite3']:
                    self.logger.debug(f"File '{fname}' is a database, providing summary.")
                    summary_content = self._read_db_summary(abs_path)
                    all_content.append(file_prefix + summary_content + file_suffix)
                    continue # Skip to the next file
                
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
