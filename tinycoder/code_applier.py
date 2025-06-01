import difflib
from typing import List, Tuple, Dict, Optional, Callable, Set

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tinycoder.file_manager import FileManager
    from tinycoder.git_manager import GitManager

from tinycoder.linters.python_linter import PythonLinter
from tinycoder.linters.html_linter import HTMLLinter
from tinycoder.linters.css_validator import CssValidator

from tinycoder.ui.log_formatter import COLORS, RESET

import logging


class CodeApplier:
    """Applies parsed edits to files and performs linting."""

    def __init__(
        self,
        file_manager: "FileManager",
        git_manager: "GitManager",
        input_func: Callable[[str], str],
    ):
        """
        Initializes the CodeApplier.

        Args:
            file_manager: An instance of FileManager.
            git_manager: An instance of GitManager (used for context).
            input_func: Function to use for user input (like confirmation).
        """
        self.file_manager = file_manager
        self.git_manager = git_manager
        self.input_func = input_func
        self.logger = logging.getLogger(__name__)

        self.python_linter = PythonLinter()
        self.html_linter = HTMLLinter()
        self.css_validator = CssValidator()

    def apply_edits(
        self, edits: List[Tuple[str, str, str]]
    ) -> Tuple[bool, List[int], Set[str], Dict[str, str]]:
        """
        Applies a list of edits to files, managing creation, modification, and linting.

        Each edit is processed sequentially. If an edit modifies a file, subsequent edits
        in the same batch operate on the modified content. Files are only written to
        disk if their content actually changes. Linters are run on all touched files
        (created or modified) after all edits are processed.

        Args:
            edits: A list of edit instructions. Each instruction is a tuple:
                (filename: str, search_block: str, replace_block: str).
                - filename: The relative path to the target file.
                - search_block: The exact block of text to find. If empty,
                  `replace_block` is prepended to the file (or creates the file).
                - replace_block: The text to replace the `search_block` with.

        Returns:
            A tuple containing:
            - all_succeeded (bool): True if *all* edits were successfully processed
              (applied, created file, or resulted in no change without error).
              False if any edit failed (e.g., file not found, search block not
              found, write error, user declined edit on untracked file).
            - failed_indices (List[int]): A list of 1-based indices corresponding
              to the `edits` list for edits that failed to apply.
            - modified_files (Set[str]): Relative paths of files whose content was
              actually changed (created or modified) by the applied edits.
            - lint_errors (Dict[str, str]): A dictionary mapping relative file paths
              to lint error messages for any files touched during the process
              (even if the edit itself failed, the linter might run on the
              original or partially modified content if applicable).
        """
        failed_edits_indices: List[int] = []
        original_file_content: Dict[str, Optional[str]] = {} # Stores content as read from disk at start of this batch
        edited_file_content: Dict[str, str] = {} # Stores in-memory state of files as edits are applied
        touched_files: Set[str] = set() # Files mentioned in edit instructions or added
        files_created_in_this_run: Set[str] = set() # Files treated as new creations in this batch
        lint_errors_found: Dict[str, str] = {}
        write_failed = False

        for i, (fname, search_block, replace_block) in enumerate(edits):
            edit_failed_this_iteration = False
            abs_path = self.file_manager.get_abs_path(fname)
            if not abs_path:
                failed_edits_indices.append(i + 1)
                continue

            rel_path = self.file_manager._get_rel_path(abs_path)
            if not rel_path:
                self.logger.error(f"Skipping edit {i+1} due to relative path issue.")
                failed_edits_indices.append(i + 1)
                continue

            # --- Context Check & Initial Read for this edit iteration ---
            if (
                rel_path not in self.file_manager.get_files()
                and rel_path not in touched_files # Check if touched earlier in *this specific batch*
            ):
                confirm = self.input_func(
                    f"LLM wants to edit '{rel_path}' which is not in the chat. Allow? (y/N): "
                )
                if confirm.lower() == "y":
                    if not self.file_manager.add_file(fname): # Adds to FileManager's context
                        self.logger.error(f"Could not add '{fname}' to context for editing.")
                        failed_edits_indices.append(i + 1)
                        continue
                else:
                    self.logger.error(f"Skipping edit for {fname} as user declined.")
                    failed_edits_indices.append(i + 1)
                    continue
            
            touched_files.add(rel_path)

            # Read and cache original disk content ONCE per file for this batch
            if rel_path not in original_file_content:
                disk_content = self.file_manager.read_file(abs_path)
                original_file_content[rel_path] = disk_content
                # Initialize edited_file_content with disk content if it exists, otherwise empty string for new files
                edited_file_content[rel_path] = disk_content.replace("\r\n", "\n") if disk_content is not None else ""

            # --- Get Current Content (from previous edits in this batch) & Normalize Search/Replace Blocks ---
            current_content_normalized = edited_file_content.get(rel_path, "")
            
            original_exists_on_disk = original_file_content.get(rel_path) is not None

            search_block_normalized = search_block.replace("\r\n", "\n")
            replace_block_normalized = replace_block.replace("\r\n", "\n")

            # --- Apply Edit Logic (in memory) ---
            try:
                new_content_normalized: Optional[str] = None

                is_current_target_empty = (current_content_normalized == "")
                is_search_effectively_empty = (search_block_normalized == "" or 
                                               (search_block_normalized.strip() == "" and search_block_normalized != ""))

                if is_current_target_empty and is_search_effectively_empty:
                    # CASE 1: Current content is empty, and search block is empty or just whitespace (e.g., "\n").
                    self.logger.info(
                        f"Edit {i+1} for '{rel_path}': Target is empty and search block "
                        f"({repr(search_block_normalized)}) is effectively empty. Setting content to replace_block."
                    )
                    new_content_normalized = replace_block_normalized
                    
                    if not original_exists_on_disk and rel_path not in files_created_in_this_run:
                         files_created_in_this_run.add(rel_path)
                         self.logger.info(
                            f"--- Planning to create '{rel_path}' with content ---"
                         )
                         for line_content in replace_block_normalized.splitlines(): # Use splitlines() for proper iteration
                             self.logger.info(f"{COLORS['GREEN']}+ {line_content}{RESET}")
                         self.logger.info(f"--- End Plan ---")

                elif search_block_normalized == "": 
                    # CASE 2: Search block is truly empty (""), but current target is NOT empty. Prepend.
                    new_content_normalized = (
                        replace_block_normalized + current_content_normalized
                    )
                elif search_block_normalized in current_content_normalized:
                    # CASE 3: Standard search and replace.
                    if search_block_normalized.strip() == "" and search_block_normalized != "":
                        occurrence_count = current_content_normalized.count(search_block_normalized)
                        if occurrence_count > 1:
                            self.logger.warning(
                                f"Edit {i+1} for '{rel_path}': The search block {repr(search_block_normalized)} "
                                f"consists only of whitespace/newlines and appears {occurrence_count} times. "
                                f"The edit will target the *first* occurrence."
                            )
                    new_content_normalized = current_content_normalized.replace(
                        search_block_normalized, replace_block_normalized, 1
                    )
                else:
                    # CASE 4: Search block not found.
                    search_preview = search_block_normalized.replace('\n', r'\n')[:50] + ('...' if len(search_block_normalized) > 50 else '')
                    if not original_exists_on_disk and \
                       rel_path not in files_created_in_this_run and \
                       search_block_normalized != "" and \
                       search_block_normalized.strip() != "":
                        self.logger.error(
                            f"Edit {i+1}: Cannot use non-empty, non-whitespace SEARCH block ({repr(search_preview)}) "
                            f"on an initially non-existent file '{rel_path}'. Expected empty or whitespace-only search block for creation. Skipping."
                        )
                    else: 
                        content_preview = current_content_normalized.replace('\n', r'\n')[:50] + ('...' if len(current_content_normalized) > 50 else '')
                        self.logger.error(
                            f"Edit {i+1}: SEARCH block ({repr(search_preview)}) not found exactly in current content of '{rel_path}'. "
                            f"Content preview: ({repr(content_preview)}). Edit failed."
                        )
                    edit_failed_this_iteration = True

                # --- Post-edit processing for this iteration ---
                if not edit_failed_this_iteration and new_content_normalized is not None:
                    if new_content_normalized != current_content_normalized:
                        # Diff print conditions adjustment
                        should_print_diff = True
                        if is_current_target_empty and rel_path in files_created_in_this_run and not original_exists_on_disk:
                             # This is a new file creation; the "Planning to create" log serves as the "diff"
                             should_print_diff = False
                        
                        if should_print_diff:
                            self._print_diff(
                                rel_path,
                                current_content_normalized,
                                new_content_normalized,
                            )
                        edited_file_content[rel_path] = new_content_normalized # Update in-memory content
                        self.logger.info(
                            f"Prepared edit {i+1} for '{rel_path}'"
                        )
                    else:
                        self.logger.info(
                            f"Edit {i+1} for '{rel_path}' resulted in no changes to current state."
                        )
                
                if edit_failed_this_iteration:
                    failed_edits_indices.append(i + 1)

            except Exception as e:
                self.logger.error(
                    f"Unexpected error processing edit {i+1} for '{fname}': {e}"
                )
                failed_edits_indices.append(i + 1)

        # --- Write all modified files to disk and lint ---
        modified_files_on_disk: Set[str] = set()
        for rel_path in touched_files: # Iterate over all files that were involved in edits
            abs_path = self.file_manager.get_abs_path(rel_path)
            if not abs_path:
                self.logger.error(
                    f"Cannot resolve path '{rel_path}' for writing final changes."
                )
                write_failed = True
                continue

            final_content_in_memory = edited_file_content.get(rel_path)
            initial_content_from_disk = original_file_content.get(rel_path)
            
            initial_content_from_disk_normalized = (
                initial_content_from_disk.replace("\r\n", "\n")
                if initial_content_from_disk is not None
                else None
            )

            needs_write = False
            if rel_path in files_created_in_this_run: # If it was marked as a new file creation
                if final_content_in_memory is not None: # And there's content to write
                    needs_write = True
            elif final_content_in_memory is not None and \
                 final_content_in_memory != initial_content_from_disk_normalized:
                # If it existed and content has changed from original disk state
                needs_write = True
            
            if needs_write:
                self.logger.info(f"Writing final changes to '{rel_path}'...")
                if self.file_manager.write_file(abs_path, final_content_in_memory):
                    modified_files_on_disk.add(rel_path)
                    if rel_path in files_created_in_this_run:
                        self.logger.info(f"Successfully created/wrote '{rel_path}'")
                    else:
                        self.logger.info(
                            f"Successfully saved changes to '{rel_path}'"
                        )
                else:
                    self.logger.error(
                        f"Failed to write final changes to '{rel_path}'."
                    )
                    write_failed = True

        # Lint all files that were touched (created or had attempt to modify)
        for rel_path in touched_files:
            abs_path = self.file_manager.get_abs_path(rel_path)
            if not abs_path: # Should have been caught above, but defensive
                continue

            # Lint the final in-memory state, as that's what would have been written or attempted
            content_to_lint = edited_file_content.get(rel_path)
            if content_to_lint is None: # Should not happen if it's in touched_files and processed
                continue

            error_string: Optional[str] = None
            file_suffix = abs_path.suffix.lower()

            if file_suffix == ".py":
                error_string = self.python_linter.lint(abs_path, content_to_lint)
            elif file_suffix in [".html", ".htm"]:
                error_string = self.html_linter.lint(abs_path, content_to_lint)
            elif file_suffix == ".css":
                error_string = self.css_validator.lint(abs_path, content_to_lint)

            if error_string:
                lint_errors_found[rel_path] = error_string

        all_succeeded = not failed_edits_indices and not write_failed

        if failed_edits_indices:
            self.logger.error(
                f"Failed to apply edit(s): {', '.join(map(str, sorted(failed_edits_indices)))}"
            )
        return all_succeeded, failed_edits_indices, modified_files_on_disk, lint_errors_found

    def _print_diff(
        self, rel_path: str, original_content: str, new_content: str
    ) -> None:
        """
        Prints a unified diff of changes between two strings to the console with expanded context.

        Compares the original content with the new content and displays the differences
        with more context lines (10 lines) and without the @@ markers for cleaner output.
        Visually separates different edit sections for better readability.

        Args:
            rel_path: The relative path of the file being diffed, used in the diff header.
            original_content: The original string content before the changes.
            new_content: The new string content after the changes.

        Side Effects:
            Prints the diff output directly to the standard output using logger.
        """
        diff = difflib.unified_diff(
            original_content.splitlines(keepends=True),
            new_content.splitlines(keepends=True),
            fromfile=f"{rel_path} (original)",
            tofile=f"{rel_path} (modified)",
            lineterm="",
            n=10
        )
        diff_output = list(diff)

        if not diff_output:
            return

        self.logger.info(f"--- Diff for '{rel_path}' ---")
        diff_lines = []
        in_edit_block = False
        found_change = False
        
        for line in diff_output:
            line = line.rstrip("\n")  # Remove trailing newline for cleaner printing
            
            if line.startswith("+++") or line.startswith("---"):
                # Skip the file header lines for cleaner output
                continue
            elif line.startswith("@@"):
                # When we hit a new @@ marker, insert a separator if we were in an edit block
                if in_edit_block and found_change:
                    diff_lines.append("-" * 40)  # Visual separator between edit sections
                in_edit_block = True
                found_change = False
                continue  # Skip the @@ position markers
            
            # Track if we've found any actual changes in this edit block
            if line.startswith("+") or (line.startswith("-") and not line.startswith("---")):
                found_change = True
            
            # Format the line with color
            if line.startswith("+"):
                diff_lines.append(f"{COLORS['GREEN']}{line}{RESET}")
            elif line.startswith("-") and not line.startswith("---"):
                diff_lines.append(f"{COLORS['RED']}{line}{RESET}")
            else:
                diff_lines.append(line)
                
        self.logger.info("\n".join(diff_lines))
        self.logger.info(f"--- End Diff for '{rel_path}' ---")
