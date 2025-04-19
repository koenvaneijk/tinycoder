import traceback
from pathlib import Path
from typing import List, Tuple, Dict, Optional, Callable, Set

# Conditional import for type checking
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from tinycoder.files import FileManager
    from tinycoder.git import GitManager

class CodeApplier:
    """Applies parsed edits to files and performs linting."""

    def __init__(
        self,
        file_manager: 'FileManager',
        git_manager: 'GitManager',
        input_func: Callable[[str], str],
        print_info: Callable[[str], None],
        print_error: Callable[[str], None],
    ):
        """
        Initializes the CodeApplier.

        Args:
            file_manager: An instance of FileManager.
            git_manager: An instance of GitManager (used for context).
            input_func: Function to use for user input (like confirmation).
            print_info: Callback for printing informational messages.
            print_error: Callback for printing error messages.
        """
        self.file_manager = file_manager
        self.git_manager = git_manager
        self.input_func = input_func
        self.print_info = print_info
        self.print_error = print_error

    def _lint_python_compile(self, abs_path: Path, content: str) -> Optional[str]:
        """Checks python syntax using compile(). Returns error string or None."""
        try:
            compile(content, str(abs_path), "exec")
            return None
        except (SyntaxError, ValueError) as err: # Catch ValueError for null bytes etc.
            # Format traceback similar to Coder's linter
            tb_lines = traceback.format_exception(type(err), err, err.__traceback__)

            # Find the start of the traceback relevant to the compile error
            traceback_marker = "Traceback (most recent call last):"
            relevant_lines = []
            in_relevant_section = False
            for line in tb_lines:
                if traceback_marker in line:
                    in_relevant_section = True
                if in_relevant_section:
                    # Exclude the frame pointing to our internal compile() call
                    if 'compile(content, str(abs_path), "exec")' not in line:
                         relevant_lines.append(line)

            # If we couldn't filter properly, return the whole traceback
            if not relevant_lines or not any(str(abs_path) in line for line in relevant_lines):
                 formatted_error = "".join(tb_lines)
            else:
                 formatted_error = "".join(relevant_lines)

            return f"Syntax error in {abs_path.name}:\n```\n{formatted_error}\n```"

    def apply_edits(self, edits: List[Tuple[str, str, str]]) -> Tuple[bool, Dict[str, str]]:
        """
        Applies the parsed edits to the files and lints Python files.

        Args:
            edits: A list of tuples, where each tuple contains (filename, search_block, replace_block).

        Returns:
            A tuple containing:
            - bool: True if at least one edit was successfully applied, False otherwise.
            - Dict[str, str]: A dictionary mapping filenames (relative paths) to lint error messages.
        """
        applied_edit_to_at_least_one_file = False
        failed_edits_indices = []
        edited_py_files: Dict[str, str] = {} # Store {rel_path: new_content} for linting
        applied_files: Set[str] = set() # Track relative paths of files edited or created
        lint_errors_found: Dict[str, str] = {} # Store lint errors found

        for i, (fname, search_block, replace_block) in enumerate(edits):
            abs_path = self.file_manager.get_abs_path(fname)
            if not abs_path:
                 # Error printed by get_abs_path
                 failed_edits_indices.append(i)
                 continue

            # Determine relative path for checking context and reporting
            rel_path = self.file_manager._get_rel_path(abs_path) # Use internal helper for consistency
            if not rel_path: # Should not happen if get_abs_path succeeded, but check defensively
                 self.print_error(f"Could not determine relative path for {abs_path}. Skipping edit {i+1}.")
                 failed_edits_indices.append(i)
                 continue

            # Ensure file is in chat context or get confirmation
            if rel_path not in self.file_manager.get_files():
                 confirm = self.input_func(f"LLM wants to edit '{rel_path}' which is not in the chat. Allow? (y/N): ")
                 if confirm.lower() == 'y':
                     # Use the original fname the user might have typed, or the resolved relative path
                     if not self.file_manager.add_file(fname): # Add file to context
                           self.print_error(f"Could not add '{fname}' for editing.")
                           failed_edits_indices.append(i)
                           continue
                 else:
                     self.print_info(f"Skipping edit for {fname}.")
                     failed_edits_indices.append(i)
                     continue

            is_new_file = not abs_path.exists() or (search_block == "" and (not abs_path.exists() or abs_path.stat().st_size == 0))

            if is_new_file:
                 if search_block != "":
                      self.print_error(f"Edit for new file {rel_path} has a non-empty SEARCH block. Skipping.")
                      failed_edits_indices.append(i)
                      continue
                 self.print_info(f"Creating and writing new file {rel_path}")
                 # Use FileManager to write the new file (expects normalized content)
                 if self.file_manager.write_file(abs_path, replace_block):
                     applied_edit_to_at_least_one_file = True
                     applied_files.add(rel_path) # Track new file
                     if abs_path.suffix == '.py': # Lint new python files too
                         edited_py_files[rel_path] = replace_block
                 else:
                     # Error printed by write_file
                     failed_edits_indices.append(i)
                 continue # Move to next edit

            # --- Existing file logic ---
            try:
                # Use FileManager to read the file
                original_content = self.file_manager.read_file(abs_path)
                if original_content is None:
                    # Error printed by read_file
                    failed_edits_indices.append(i)
                    continue

                original_content_normalized = original_content.replace('\r\n', '\n')

                # The search needs to be exact.
                if search_block not in original_content_normalized:
                    self.print_error(f"SEARCH block not found exactly in {rel_path}. Edit {i+1} failed.")
                    failed_edits_indices.append(i)
                    continue

                # Perform the replacement
                new_content_normalized = original_content_normalized.replace(search_block, replace_block, 1)

                # Only write if content actually changed (normalized comparison)
                if new_content_normalized != original_content_normalized:
                    # Use FileManager to write the file (expects normalized content)
                    if self.file_manager.write_file(abs_path, new_content_normalized):
                        self.print_info(f"Applied edit {i+1} to {rel_path}")
                        applied_edit_to_at_least_one_file = True
                        applied_files.add(rel_path)
                        # Store normalized content for linting if it's a python file
                        if abs_path.suffix == '.py':
                            edited_py_files[rel_path] = new_content_normalized
                    else:
                        # Error printed by write_file
                        failed_edits_indices.append(i)
                else:
                     self.print_info(f"Edit {i+1} for {rel_path} resulted in no changes. Skipping write.")
                     # Still need to lint even if no changes, in case the edit *fixed* a syntax error
                     if abs_path.suffix == '.py':
                         # Use the normalized content which might be different due to line endings only
                         edited_py_files[rel_path] = new_content_normalized
                         applied_files.add(rel_path) # Track for linting even if no write


            except FileNotFoundError:
                 self.print_error(f"File {rel_path} vanished before edit {i+1} could be applied.")
                 failed_edits_indices.append(i)
            except Exception as e:
                self.print_error(f"Error applying edit {i+1} to {fname}: {e}")
                failed_edits_indices.append(i)

        if failed_edits_indices:
            self.print_error(f"Failed to apply edits: {', '.join(map(lambda x: str(x+1), failed_edits_indices))}")

        # --- Lint Python files after edits ---
        # Lint all python files that were touched or newly created
        for rel_path in applied_files:
            if rel_path.endswith('.py'):
                abs_path = self.file_manager.get_abs_path(rel_path)
                if abs_path:
                    content_to_lint = edited_py_files.get(rel_path) # Get potentially modified content
                    if content_to_lint is None: # If not in edited_py_files, read from disk
                        content_to_lint = self.file_manager.read_file(abs_path)

                    if content_to_lint is not None:
                        error_string = self._lint_python_compile(abs_path, content_to_lint)
                        if error_string:
                            lint_errors_found[rel_path] = error_string
                    else:
                         # Use print_error as this indicates a problem reading a file we just edited/checked
                         self.print_error(f"Could not read {rel_path} for linting after edit.")

        return applied_edit_to_at_least_one_file, lint_errors_found
