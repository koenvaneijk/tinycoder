import difflib
from typing import List, Tuple, Dict, Optional, Callable, Set

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tinycoder.file_manager import FileManager
    from tinycoder.git_manager import GitManager

# Linters
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
        original_file_content: Dict[str, Optional[str]] = (
            {}
        )  # Store original content (or None if new)
        edited_file_content: Dict[str, str] = (
            {}
        )  # Stores current content after edits in this run
        touched_files: Set[str] = set()  # Tracks files mentioned in edits
        files_created_in_this_run: Set[str] = (
            set()
        )  # Tracks files created during this call
        lint_errors_found: Dict[str, str] = {}
        write_failed = (
            False  # Flag to track if any write operation fails after the loop
        )

        for i, (fname, search_block, replace_block) in enumerate(edits):
            edit_failed_this_iteration = False  # Flag for this specific edit block
            abs_path = self.file_manager.get_abs_path(fname)
            if not abs_path:
                failed_edits_indices.append(i + 1)
                continue

            rel_path = self.file_manager._get_rel_path(abs_path)
            if not rel_path:
                self.logger.error(f"Skipping edit {i+1} due to relative path issue.")
                failed_edits_indices.append(i + 1)
                continue

            # --- Context Check & Initial Read ---
            if (
                rel_path not in self.file_manager.get_files()
                and rel_path not in touched_files
            ):
                # If not in context AND not already touched in this run, ask user
                confirm = self.input_func(
                    f"LLM wants to edit '{rel_path}' which is not in the chat. Allow? (y/N): "
                )
                if confirm.lower() == "y":
                    if not self.file_manager.add_file(fname):
                        self.logger.error(f"Could not add '{fname}' for editing.")
                        failed_edits_indices.append(i + 1)
                        continue
                else:
                    self.logger.error(f"Skipping edit for {fname}.")
                    failed_edits_indices.append(i + 1)
                    continue

            touched_files.add(rel_path)  # Mark as touched regardless of outcome

            # Read and cache original content only if not already done in this run
            if rel_path not in original_file_content:
                content = self.file_manager.read_file(abs_path)
                # Store original content (None if it doesn't exist/unreadable)
                original_file_content[rel_path] = content
                if content is not None:
                    # If readable, cache its normalized version as the starting point for edits
                    edited_file_content[rel_path] = content.replace("\r\n", "\n")
                # If content is None (new/unreadable), edited_file_content will be populated
                # either by creation logic or potentially error out if read fails later.

            # --- Get Current Content for this Edit ---
            # Use cached content if available, otherwise start fresh (applies to new files)
            current_content_normalized = edited_file_content.get(rel_path, "")
            original_exists = original_file_content.get(rel_path) is not None
            original_is_empty = (
                original_exists and original_file_content[rel_path] == ""
            )

            search_is_empty = search_block == ""
            is_creation_attempt = not original_exists or (
                search_is_empty and original_is_empty
            )

            # --- Apply Edit Logic (in memory) ---
            try:
                new_content_normalized: Optional[str] = None

                # Handle file creation scenario explicitly (first edit for this file is creation)
                if is_creation_attempt and rel_path not in files_created_in_this_run:
                    if search_block != "":
                        self.logger.error(
                            f"Edit {i+1}: Cannot use non-empty SEARCH block on non-existent/empty file '{rel_path}'. Skipping."
                        )
                        edit_failed_this_iteration = True
                    else:
                        # This is a valid creation/prepend-to-empty
                        replace_block_normalized = replace_block.replace("\r\n", "\n")
                        self.logger.info(
                            f"--- Planning to create/overwrite '{rel_path}' ---"
                        )
                        for line in replace_block_normalized.splitlines():
                            # Print added lines in green
                            self.logger.info(f"{COLORS['GREEN']}+ {line}{RESET}")
                        self.logger.info(f"--- End Plan ---")
                        # Update cache, mark as created
                        new_content_normalized = replace_block_normalized
                        edited_file_content[rel_path] = new_content_normalized
                        files_created_in_this_run.add(rel_path)
                        self.logger.info(
                            f"Prepared edit {i+1} for creation of '{rel_path}'"
                        )  # Indicate memory update

                # Handle modification of existing or already-cached content
                elif not is_creation_attempt or rel_path in files_created_in_this_run:
                    # Normalize search and replace blocks for this edit
                    search_block_normalized = search_block.replace("\r\n", "\n")
                    replace_block_normalized = replace_block.replace("\r\n", "\n")

                    if search_is_empty:
                        # Prepend replace block
                        new_content_normalized = (
                            replace_block_normalized + current_content_normalized
                        )
                    elif search_block_normalized in current_content_normalized:
                        # Perform replacement
                        new_content_normalized = current_content_normalized.replace(
                            search_block_normalized, replace_block_normalized, 1
                        )
                    else:
                        # Search block not found
                        self.logger.error(
                            f"Edit {i+1}: SEARCH block not found exactly in '{rel_path}'. Edit failed."
                        )
                        edit_failed_this_iteration = True

                    # Check if content actually changed with *this specific edit*
                    if (
                        not edit_failed_this_iteration
                        and new_content_normalized is not None
                    ):
                        if new_content_normalized != current_content_normalized:
                            # Print diff of this specific step
                            self._print_diff(
                                rel_path,
                                current_content_normalized,
                                new_content_normalized,
                            )
                            # Update cache with the result of this edit
                            edited_file_content[rel_path] = new_content_normalized
                            self.logger.info(
                                f"Prepared edit {i+1} for '{rel_path}'"
                            )  # Indicate memory update
                        else:
                            # No change from this specific edit
                            self.logger.info(
                                f"Edit {i+1} for '{rel_path}' resulted in no changes to current state."
                            )
                    elif edit_failed_this_iteration:
                        # Need to ensure cache still holds the content *before* this failed edit
                        # for potential subsequent edits or final write comparison.
                        # This should already be the case as edited_file_content wasn't updated.
                        pass

                # If this edit failed at any point, record its index
                if edit_failed_this_iteration:
                    failed_edits_indices.append(i + 1)

            except Exception as e:
                self.logger.error(
                    f"Unexpected error processing edit {i+1} for '{fname}': {e}"
                )
                failed_edits_indices.append(i + 1)

        # --- Write changed files to disk ---
        modified_files: Set[str] = set()  # Reset and populate based on final comparison
        # Remove the check `if not failed_edits_indices:` to allow writing successful edits even if others failed.
        for rel_path in touched_files:
            abs_path = self.file_manager.get_abs_path(rel_path)
            if not abs_path:
                self.logger.error(
                    f"Cannot resolve path '{rel_path}' for writing final changes."
                )
                write_failed = True
                continue # Skip to next file if path resolution fails

            # This block should be outside the 'if not abs_path:' block, but inside the 'for' loop
            final_content = edited_file_content.get(rel_path)
            initial_content = original_file_content.get(rel_path)
            initial_content_normalized = (
                initial_content.replace("\r\n", "\n")
                if initial_content is not None
                else None
            )

            # Determine if a write is needed
            needs_write = False
            if rel_path in files_created_in_this_run:
                # If marked for creation, always write (unless final content is None?)
                if (
                    final_content is not None
                ):  # Check if creation didn't somehow fail
                    needs_write = True
            elif (
                final_content is not None
                and final_content != initial_content_normalized
            ):
                # Existing file modified
                needs_write = True

            if needs_write:
                self.logger.info(f"Writing final changes to '{rel_path}'...")
                if self.file_manager.write_file(abs_path, final_content):
                    modified_files.add(rel_path)  # Track successfully written files
                    if rel_path in files_created_in_this_run:
                        self.logger.info(f"Successfully created/wrote '{rel_path}'")
                    else:
                        self.logger.info(
                            f"Successfully saved changes to '{rel_path}'"
                        )
                else:
                    # Error printed by write_file
                    self.logger.error(
                        f"Failed to write final changes to '{rel_path}'."
                    )
                    write_failed = True  # Mark overall failure if any write fails

        # --- Lint modified/created files ---
        # Lint all files that were *touched* using the final cached content
        for rel_path in touched_files:
            abs_path = self.file_manager.get_abs_path(rel_path)
            if not abs_path:
                self.logger.error(
                    f"Could not resolve path '{rel_path}' for linting. Skipping."
                )
                continue

            content_to_lint = edited_file_content.get(rel_path)
            if content_to_lint is None:
                # If content is None (e.g., initial read failed and no edits applied), skip linting
                # Only print error if it was expected to be there (i.e., not None in original_file_content maybe?)
                # Let's skip silently for now if content isn't available in cache.
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

        # Determine overall success and final return value
        all_succeeded = not failed_edits_indices and not write_failed

        if failed_edits_indices:
            self.logger.error(
                f"Failed to apply edit(s): {', '.join(map(str, sorted(failed_edits_indices)))}"
            )
        # No separate error message for write_failed needed here, as write_file prints its own.

        # Return: all succeeded flag, list of failed indices, set of *successfully modified* files, lint errors
        return all_succeeded, failed_edits_indices, modified_files, lint_errors_found

    def _print_diff(
        self, rel_path: str, original_content: str, new_content: str
    ) -> None:
        """
        Prints a unified diff of changes between two strings to the console.

        Compares the original content with the new content and displays the differences
        using standard unified diff format. If there are no differences, nothing is printed.

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
            lineterm="",  # Avoid extra newlines from difflib
        )
        diff_output = list(diff)  # Consume generator

        if not diff_output:
            return  # No changes to print

        self.logger.info(f"--- Diff for '{rel_path}' ---")
        diff_lines = []
        for line in diff_output:
            line = line.rstrip("\n")  # Remove trailing newline for cleaner printing
            if line.startswith("+++"):
                # Skip the '+++ b/...' line for cleaner output
                continue
            elif line.startswith("---"):
                # Skip the '--- a/...' line for cleaner output
                continue
            elif line.startswith("+"):
                diff_lines.append(f"{COLORS['GREEN']}{line}{RESET}")
            elif line.startswith("-") and not line.startswith("---"):
                diff_lines.append(f"{COLORS['RED']}{line}{RESET}")
            else:
                diff_lines.append(line)
        self.logger.info("\n".join(diff_lines))
        self.logger.info(f"--- End Diff for '{rel_path}' ---")
