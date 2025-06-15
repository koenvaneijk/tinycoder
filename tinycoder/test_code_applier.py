import unittest
from unittest.mock import MagicMock, patch, call, ANY
from pathlib import Path
from typing import List, Tuple, Dict, Set, Optional

# Import the class to test
from tinycoder.code_applier import CodeApplier
from tinycoder.file_manager import FileManager
from tinycoder.git_manager import GitManager


class TestCodeApplier(unittest.TestCase):
    def setUp(self):
        """Set up test fixtures for each test method."""
        self.mock_file_manager = MagicMock(spec=FileManager)
        self.mock_git_manager = MagicMock(spec=GitManager)
        self.mock_input_func = MagicMock()
        # Removed mock_print_info and mock_print_error as CodeApplier uses logging now

        # Mock linters
        self.mock_python_linter = MagicMock()
        self.mock_html_linter = MagicMock()

        # Patch the linter instances within the CodeApplier module
        self.linter_patches = [
            patch(
                "tinycoder.code_applier.PythonLinter",
                return_value=self.mock_python_linter,
            ),
            patch(
                "tinycoder.code_applier.HTMLLinter", return_value=self.mock_html_linter
            ),
        ]
        for p in self.linter_patches:
            p.start()
            self.addCleanup(p.stop)  # Ensure patches are stopped even if setUp fails

        self.code_applier = CodeApplier(
            file_manager=self.mock_file_manager,
            git_manager=self.mock_git_manager,
            input_func=self.mock_input_func,
            # Removed print_info and print_error args
        )

        # --- Centralized Mock Setup ---
        # Store mock path objects and their content
        self.mock_path_objects: Dict[str, MagicMock] = {}
        self.mock_file_contents: Dict[str, Optional[str]] = {}

        # Default _get_rel_path (can be overridden if needed)
        self.mock_file_manager._get_rel_path.side_effect = lambda p: str(p).replace(
            "/fake/repo/", ""
        )

        # Default get_files (can be overridden in tests)
        self.mock_file_manager.get_files.return_value = {
            "existing.py",
            "another.txt",
            "empty.html",
        }
        # Default write/add success (can be overridden)
        self.mock_file_manager.write_file.return_value = True
        self.mock_file_manager.add_file.return_value = True

        # --- Dynamic Side Effects Based on Dictionaries ---
        def get_abs_path_side_effect(rel_path_arg: str):
            abs_path_str = f"/fake/repo/{rel_path_arg}"
            return self.mock_path_objects.get(abs_path_str) # Return stored mock or None

        def read_file_side_effect(path_arg: Path):
            # FileManager uses the absolute Path object from get_abs_path
            abs_path_str = str(path_arg)
            # Return stored content based on the absolute path string
            return self.mock_file_contents.get(abs_path_str, None)

        self.mock_file_manager.get_abs_path.side_effect = get_abs_path_side_effect
        self.mock_file_manager.read_file.side_effect = read_file_side_effect

        # Default linter behavior
        self.mock_python_linter.lint.return_value = None
        self.mock_html_linter.lint.return_value = None

    def _setup_file_content(
        self,
        rel_path: str,
        content: Optional[str],
        exists: bool = True,
        size: int = 10,
    ):
        """
        Helper to configure mock Path object and store content for a file.
        It populates self.mock_path_objects and self.mock_file_contents,
        which are used by the centralized side effects defined in setUp.
        """
        abs_path_str = f"/fake/repo/{rel_path}"

        path_mock = MagicMock(spec=Path)
        path_mock.exists.return_value = exists
        path_mock.is_file.return_value = exists
        path_mock.stat.return_value.st_size = size if exists else 0
        path_mock.suffix = Path(rel_path).suffix
        path_mock.__str__.return_value = abs_path_str # For _get_rel_path and read_file key

        # Store the mock path object and content in the dictionaries
        self.mock_path_objects[abs_path_str] = path_mock
        self.mock_file_contents[abs_path_str] = content
        # Do NOT reassign side effects here

    # --- Test Cases ---

    def test_apply_single_edit_success(self):
        """Test applying a simple, valid edit to an existing file."""
        rel_path = "existing.py"
        original_content = "print('hello world')"
        search_block = "print('hello world')"
        replace_block = "print('Hello, Python!')"
        expected_content = "print('Hello, Python!')"

        self._setup_file_content(rel_path, original_content)
        self.mock_file_manager.get_files.return_value = {
            rel_path
        }  # Ensure file is in context

        edits = [(rel_path, search_block, replace_block)]

        # Use assertLogs to capture log messages
        with self.assertLogs('tinycoder.code_applier', level='INFO') as cm:
            result = self.code_applier.apply_edits(edits)

        self.assertEqual(
            result, (True, [], {rel_path}, {})
        )  # success, no failed, modified, no lint err
        abs_path_str = f"/fake/repo/{rel_path}"  # Expected path string

        # Assert write_file call using call_args to handle potential mock path object
        self.mock_file_manager.write_file.assert_called_once()  # Check it was called once
        write_call_args, _ = self.mock_file_manager.write_file.call_args
        called_write_path_arg = write_call_args[0]
        called_write_content_arg = write_call_args[1]
        self.assertEqual(
            str(called_write_path_arg), abs_path_str
        )  # Check path string matches
        self.assertEqual(
            called_write_content_arg, expected_content
        )  # Check content matches

        # Assert linter call using call_args as well
        self.mock_python_linter.lint.assert_called_once()
        lint_call_args, _ = self.mock_python_linter.lint.call_args
        called_lint_path_arg = lint_call_args[0]
        called_lint_content_arg = lint_call_args[1]
        self.assertEqual(
            str(called_lint_path_arg), abs_path_str
        )  # Check path string matches
        self.assertEqual(
            called_lint_content_arg, expected_content
        )  # Check content matches

        self.mock_html_linter.lint.assert_not_called()

        # Check log messages
        log_output = "\n".join(cm.output)
        # Exact diff content might vary slightly, check for key parts
        self.assertIn(f"--- Diff for '{rel_path}' ---", log_output)
        self.assertIn(f"--- End Diff for '{rel_path}' ---", log_output)
        self.assertIn(f"Prepared edit 1 for '{rel_path}'", log_output)
        self.assertIn(f"Writing final changes to '{rel_path}'...", log_output)
        self.assertIn(f"Successfully saved changes to '{rel_path}'", log_output)

    def test_apply_create_new_file_success(self):
        """Test creating a new file with an empty search block."""
        rel_path = "new_file.py"
        replace_block = "def new_func():\n    pass"
        expected_content = "def new_func():\n    pass"

        # Mock file does not exist initially
        self._setup_file_content(rel_path, None, exists=False)
        self.mock_file_manager.get_files.return_value = (
            set()
        )  # Not in context initially
        self.mock_input_func.return_value = "y"  # Confirm adding the file

        edits = [(rel_path, "", replace_block)]

        with self.assertLogs('tinycoder.code_applier', level='INFO') as cm:
            result = self.code_applier.apply_edits(edits)

        self.assertEqual(result, (True, [], {rel_path}, {}))
        abs_path_str = f"/fake/repo/{rel_path}"  # Expected path string
        self.mock_file_manager.add_file.assert_called_once_with(rel_path)

        # Assert write_file call using call_args
        self.mock_file_manager.write_file.assert_called_once()
        write_call_args, _ = self.mock_file_manager.write_file.call_args
        self.assertEqual(str(write_call_args[0]), abs_path_str)
        self.assertEqual(write_call_args[1], expected_content)

        # Assert linter call using call_args
        self.mock_python_linter.lint.assert_called_once()
        lint_call_args, _ = self.mock_python_linter.lint.call_args
        self.assertEqual(str(lint_call_args[0]), abs_path_str)
        self.assertEqual(lint_call_args[1], expected_content)

        # Check log messages
        log_output = "\n".join(cm.output)
        self.assertIn(f"--- Planning to create/overwrite '{rel_path}' ---", log_output)
        self.assertIn(f"--- End Plan ---", log_output)
        self.assertIn(f"Prepared edit 1 for creation of '{rel_path}'", log_output)
        self.assertIn(f"Writing final changes to '{rel_path}'...", log_output)
        self.assertIn(f"Successfully created/wrote '{rel_path}'", log_output)

    def test_apply_prepend_to_existing_file(self):
        """Test prepending content to an existing file using empty search block."""
        rel_path = "existing.py"
        original_content = "print('world')"
        replace_block = "#!/usr/bin/env python\n"
        expected_content = "#!/usr/bin/env python\nprint('world')"

        self._setup_file_content(rel_path, original_content)
        self.mock_file_manager.get_files.return_value = {rel_path}

        edits = [(rel_path, "", replace_block)]

        with self.assertLogs('tinycoder.code_applier', level='INFO') as cm:
            result = self.code_applier.apply_edits(edits)

        self.assertEqual(result, (True, [], {rel_path}, {}))
        abs_path_str = f"/fake/repo/{rel_path}"  # Expected path string

        # Assert write_file call using call_args
        self.mock_file_manager.write_file.assert_called_once()
        write_call_args, _ = self.mock_file_manager.write_file.call_args
        self.assertEqual(str(write_call_args[0]), abs_path_str)
        self.assertEqual(write_call_args[1], expected_content)

        # Assert linter call using call_args
        self.mock_python_linter.lint.assert_called_once()
        lint_call_args, _ = self.mock_python_linter.lint.call_args
        self.assertEqual(str(lint_call_args[0]), abs_path_str)
        self.assertEqual(lint_call_args[1], expected_content)

        # Check log messages
        log_output = "\n".join(cm.output)
        self.assertIn(f"--- Diff for '{rel_path}' ---", log_output)
        self.assertIn(f"--- End Diff for '{rel_path}' ---", log_output)
        self.assertIn(f"Prepared edit 1 for '{rel_path}'", log_output)
        self.assertIn(f"Writing final changes to '{rel_path}'...", log_output)
        self.assertIn(f"Successfully saved changes to '{rel_path}'", log_output)

    def test_apply_multiple_edits_same_file(self):
        """Test applying multiple sequential edits to the same file."""
        rel_path = "multi_edit.py"
        original_content = "line1\nline2\nline3"
        expected_content_after_edit1 = "line_one\nline2\nline3"
        expected_content_final = "line_one\nline_two\nline3"

        self._setup_file_content(rel_path, original_content)
        self.mock_file_manager.get_files.return_value = {rel_path}

        edits = [
            (rel_path, "line1", "line_one"),
            (rel_path, "line2", "line_two"),
        ]

        with self.assertLogs('tinycoder.code_applier', level='INFO') as cm:
            result = self.code_applier.apply_edits(edits)

        self.assertEqual(result, (True, [], {rel_path}, {}))
        abs_path_str = f"/fake/repo/{rel_path}"  # Expected path string

        # Assert write_file call using call_args
        # Should only write the final content
        self.mock_file_manager.write_file.assert_called_once()
        write_call_args, _ = self.mock_file_manager.write_file.call_args
        self.assertEqual(str(write_call_args[0]), abs_path_str)
        self.assertEqual(write_call_args[1], expected_content_final)

        # Assert linter call using call_args
        self.mock_python_linter.lint.assert_called_once()
        lint_call_args, _ = self.mock_python_linter.lint.call_args
        self.assertEqual(str(lint_call_args[0]), abs_path_str)
        self.assertEqual(lint_call_args[1], expected_content_final)

        # Check expected log messages
        log_output = "\n".join(cm.output)
        # Check diffs were logged (count might be fragile, check key parts)
        self.assertTrue(log_output.count(f"--- Diff for '{rel_path}' ---") >= 2)
        self.assertTrue(log_output.count(f"--- End Diff for '{rel_path}' ---") >= 2)
        # Check prepared messages
        self.assertIn(f"Prepared edit 1 for '{rel_path}'", log_output)
        self.assertIn(f"Prepared edit 2 for '{rel_path}'", log_output)
        # Check write/save messages
        self.assertIn(f"Writing final changes to '{rel_path}'...", log_output)
        self.assertIn(f"Successfully saved changes to '{rel_path}'", log_output)

    def test_apply_edit_fail_search_not_found(self):
        """Test failure when the search block is not found."""
        rel_path = "existing.py"
        original_content = "print('hello world')"
        search_block = "print('goodbye world')"  # This won't be found
        replace_block = "print('This should not be applied')"

        self._setup_file_content(rel_path, original_content)
        self.mock_file_manager.get_files.return_value = {rel_path}

        edits = [(rel_path, search_block, replace_block)]

        # Expect ERROR level logs
        with self.assertLogs('tinycoder.code_applier', level='ERROR') as cm:
            result = self.code_applier.apply_edits(edits)

        self.assertEqual(
            result, (False, [1], set(), {})
        )  # failure, index 1 failed, no files modified, no lint err
        self.mock_file_manager.write_file.assert_not_called()

        # Check specific error messages
        log_output = "\n".join(cm.output)
        self.assertIn(
            f"Edit 1: SEARCH block not found exactly in '{rel_path}'. Edit failed.",
            log_output
        )
        # Check the final summary error message
        self.assertIn("Failed to apply edit(s): 1", log_output)

        # Linter should still run on the original cached content
        abs_path_str = f"/fake/repo/{rel_path}"  # Expected path string

        # Assert linter call using call_args
        self.mock_python_linter.lint.assert_called_once()
        lint_call_args, _ = self.mock_python_linter.lint.call_args
        self.assertEqual(str(lint_call_args[0]), abs_path_str)
        self.assertEqual(lint_call_args[1], original_content)

    def test_apply_edit_fail_write_error(self):
        """Test failure when the file manager fails to write."""
        rel_path = "existing.py"
        original_content = "print('hello world')"
        search_block = "print('hello world')"
        replace_block = "print('Hello, Python!')"

        self._setup_file_content(rel_path, original_content)
        self.mock_file_manager.get_files.return_value = {rel_path}

        # Define a side effect that returns False (simulating write failure)
        # The error message is now expected from CodeApplier, not FileManager mock
        def write_fail_side_effect(*args, **kwargs):
            # We don't need to mock print_error here anymore
            return False

        # Assign the custom side effect function
        self.mock_file_manager.write_file.side_effect = write_fail_side_effect

        edits = [(rel_path, search_block, replace_block)]

        # Expect INFO logs for preparation and ERROR log for the write failure.
        # Use level='INFO' to capture both.
        with self.assertLogs('tinycoder.code_applier', level='INFO') as cm:
            result = self.code_applier.apply_edits(edits)

        # Expected failure: Overall process failed (write_failed=True), no files modified.
        # failed_edits_indices remains empty because the edit processing itself succeeded before the write failed.
        self.assertEqual(result, (False, [], set(), {}))
        abs_path_str = f"/fake/repo/{rel_path}"  # Expected path string

        # Assert write_file call using call_args
        self.mock_file_manager.write_file.assert_called_once()
        write_call_args, _ = self.mock_file_manager.write_file.call_args
        self.assertEqual(str(write_call_args[0]), abs_path_str)
        self.assertEqual(write_call_args[1], replace_block)

        # Check log messages (both INFO and the expected ERROR)
        log_output = "\n".join(cm.output)
        self.assertIn(f"Prepared edit 1 for '{rel_path}'", log_output) # Check INFO log
        self.assertIn(f"Writing final changes to '{rel_path}'...", log_output) # Check INFO log
        self.assertIn(
            f"Failed to write final changes to '{rel_path}'.", # Check ERROR log
            log_output
        )
        # Note: The final summary "Failed to apply edit(s): ..." is NOT logged
        # when only the write fails, only when edit processing itself fails.
        # Check the return value `all_succeeded` is False, which is done above.
        # `write_file` in FileManager is mocked, so it won't print its own error unless we make it.
        # CodeApplier now logs its own error if write_file returns False.

        # Linter should still run on the content *intended* to be written
        # Assert linter call using call_args
        self.mock_python_linter.lint.assert_called_once()
        lint_call_args, _ = self.mock_python_linter.lint.call_args
        self.assertEqual(str(lint_call_args[0]), abs_path_str)
        self.assertEqual(lint_call_args[1], replace_block)

    def test_apply_edit_no_change(self):
        """Test applying an edit that results in no change to the content."""
        rel_path = "existing.py"
        original_content = "print('hello world')"
        search_block = "print('hello world')"
        replace_block = "print('hello world')"  # Same as original

        self._setup_file_content(rel_path, original_content)
        self.mock_file_manager.get_files.return_value = {rel_path}

        edits = [(rel_path, search_block, replace_block)]

        with self.assertLogs('tinycoder.code_applier', level='INFO') as cm:
            result = self.code_applier.apply_edits(edits)

        # Success overall, no fails, but no *modified* files
        self.assertEqual(result, (True, [], set(), {}))
        self.mock_file_manager.write_file.assert_not_called()  # Write should be skipped

        # Check the specific info message was logged
        self.assertIn(
             # The exact message changed slightly in implementation
             f"Edit 1 for '{rel_path}' resulted in no changes to current state.",
             "\n".join(cm.output)
        )

        abs_path_str = f"/fake/repo/{rel_path}"  # Expected path string
        # Linter should still run on the original content
        # Assert linter call using call_args
        self.mock_python_linter.lint.assert_called_once()
        lint_call_args, _ = self.mock_python_linter.lint.call_args
        self.assertEqual(str(lint_call_args[0]), abs_path_str)
        self.assertEqual(lint_call_args[1], original_content)

    def test_apply_edit_with_lint_error(self):
        """Test applying an edit where the resulting code has a lint error."""
        rel_path = "existing.py"
        original_content = "print('hello world')"
        search_block = "print('hello world')"
        replace_block = "print 'bad syntax'"  # Python 2 syntax
        expected_content = "print 'bad syntax'"
        lint_error_msg = "SyntaxError: Missing parentheses in call to 'print'"

        self._setup_file_content(rel_path, original_content)
        self.mock_file_manager.get_files.return_value = {rel_path}
        self.mock_python_linter.lint.return_value = (
            lint_error_msg  # Simulate lint error
        )

        edits = [(rel_path, search_block, replace_block)]

        # Lint errors aren't logged at ERROR level, just returned. Capture INFO.
        with self.assertLogs('tinycoder.code_applier', level='INFO') as cm:
            result = self.code_applier.apply_edits(edits)

        # Edit applied successfully, but lint error reported
        self.assertEqual(result, (True, [], {rel_path}, {rel_path: lint_error_msg}))
        abs_path_str = f"/fake/repo/{rel_path}"  # Expected path string

        # Assert write_file call using call_args
        self.mock_file_manager.write_file.assert_called_once()
        write_call_args, _ = self.mock_file_manager.write_file.call_args
        self.assertEqual(str(write_call_args[0]), abs_path_str)
        self.assertEqual(write_call_args[1], expected_content)

        # Assert linter call using call_args
        self.mock_python_linter.lint.assert_called_once()
        lint_call_args, _ = self.mock_python_linter.lint.call_args
        self.assertEqual(str(lint_call_args[0]), abs_path_str)
        self.assertEqual(lint_call_args[1], expected_content)

    def test_apply_edit_html_with_lint_error(self):
        """Test applying an edit to HTML where the result has a lint error."""
        rel_path = "page.html"
        original_content = "<p>Hello</p>"
        search_block = "<p>Hello</p>"
        replace_block = "<div><h1>Title</b></div>"  # Mismatched tag
        expected_content = "<div><h1>Title</b></div>"
        lint_error_msg = "Mismatched tag: expected '</h1>', got '</b>'"

        self._setup_file_content(rel_path, original_content)
        self.mock_file_manager.get_files.return_value = {rel_path}
        self.mock_html_linter.lint.return_value = lint_error_msg  # Simulate lint error

        edits = [(rel_path, search_block, replace_block)]

        # Lint errors aren't logged at ERROR level, just returned. Capture INFO.
        with self.assertLogs('tinycoder.code_applier', level='INFO') as cm:
            result = self.code_applier.apply_edits(edits)

        self.assertEqual(result, (True, [], {rel_path}, {rel_path: lint_error_msg}))
        abs_path_str = f"/fake/repo/{rel_path}"  # Expected path string

        # Assert write_file call using call_args
        self.mock_file_manager.write_file.assert_called_once()
        write_call_args, _ = self.mock_file_manager.write_file.call_args
        self.assertEqual(str(write_call_args[0]), abs_path_str)
        self.assertEqual(write_call_args[1], expected_content)

        # Assert linter call using call_args
        self.mock_html_linter.lint.assert_called_once()
        lint_call_args, _ = self.mock_html_linter.lint.call_args
        self.assertEqual(str(lint_call_args[0]), abs_path_str)
        self.assertEqual(lint_call_args[1], expected_content)

        self.mock_python_linter.lint.assert_not_called()

    def test_apply_edit_file_not_in_context_confirm_yes(self):
        """Test editing a file not in context, user confirms."""
        rel_path = "untracked.txt"
        original_content = "Some text."
        search_block = "text"
        replace_block = "content"
        expected_content = "Some content."

        # Use the centralized setup method
        self._setup_file_content(rel_path, original_content)
        self.mock_file_manager.get_files.return_value = {
            "existing.py"
        }  # File not in context
        self.mock_input_func.return_value = "y"  # User confirms

        edits = [(rel_path, search_block, replace_block)]

        with self.assertLogs('tinycoder.code_applier', level='INFO') as cm:
            result = self.code_applier.apply_edits(edits)

        self.assertEqual(result, (True, [], {rel_path}, {}))
        self.mock_input_func.assert_called_once_with(
            f"LLM wants to edit '{rel_path}' which is not in the chat. Allow? (y/N): "
        )
        self.mock_file_manager.add_file.assert_called_once_with(rel_path)
        abs_path_str = f"/fake/repo/{rel_path}"  # Expected path string
        # Retrieve the mock Path object using the absolute path string key
        self.assertIn(abs_path_str, self.mock_path_objects) # Ensure path was set up
        path_mock = self.mock_path_objects[abs_path_str]

        # Assert write_file call using call_args
        self.mock_file_manager.write_file.assert_called_once()
        write_call_args, _ = self.mock_file_manager.write_file.call_args
        # Path arg for write_file should be the mock Path object returned by get_abs_path
        self.assertEqual(write_call_args[0], path_mock) # Check the object itself
        self.assertEqual(write_call_args[1], expected_content)

        self.mock_python_linter.lint.assert_not_called()  # Not a .py file
        self.mock_html_linter.lint.assert_not_called()  # Not an .html file

    def test_apply_edit_file_not_in_context_confirm_no(self):
        """Test editing a file not in context, user denies."""
        rel_path = "untracked.txt"
        original_content = "Some text."
        search_block = "text"
        replace_block = "content"

        # Use the centralized setup method
        self._setup_file_content(rel_path, original_content)
        self.mock_file_manager.get_files.return_value = {"existing.py"}
        self.mock_input_func.return_value = "n"  # User denies

        edits = [(rel_path, search_block, replace_block)]

        # User denial logs an error
        with self.assertLogs('tinycoder.code_applier', level='ERROR') as cm:
            result = self.code_applier.apply_edits(edits)

        # Edit fails because user denied
        self.assertEqual(result, (False, [1], set(), {}))
        self.mock_input_func.assert_called_once_with(
            f"LLM wants to edit '{rel_path}' which is not in the chat. Allow? (y/N): "
        )
        self.mock_file_manager.add_file.assert_not_called()
        self.mock_file_manager.write_file.assert_not_called()

        log_output = "\n".join(cm.output)
        self.assertIn(f"Skipping edit for {rel_path}.", log_output)
        self.assertIn("Failed to apply edit(s): 1", log_output)

    def test_apply_fail_non_empty_search_on_new_file(self):
        """Test failure when trying to search in a non-existent file."""
        rel_path = "new_file.txt"
        search_block = "find me"  # Non-empty search
        replace_block = "replace text"

        # NOTE: Although we call _setup_file_content, the file is marked as non-existent.
        # The key is that `get_abs_path` will return the mock Path object,
        # but `read_file` will return `None` based on the content stored in setup.
        self._setup_file_content(rel_path, None, exists=False)
        self.mock_file_manager.get_files.return_value = set()  # Not in context
        self.mock_input_func.return_value = "y"  # Confirm adding

        edits = [(rel_path, search_block, replace_block)]

        with self.assertLogs('tinycoder.code_applier', level='ERROR') as cm:
            result = self.code_applier.apply_edits(edits)

        # Should fail because search block is not empty for a new file scenario
        self.assertEqual(result, (False, [1], set(), {}))
        self.mock_file_manager.add_file.assert_called_once_with(
            rel_path
        )  # Still tries to add
        self.mock_file_manager.write_file.assert_not_called()

        log_output = "\n".join(cm.output)
        self.assertIn(
            f"Edit 1: Cannot use non-empty SEARCH block on non-existent/empty file '{rel_path}'. Skipping.",
            log_output
        )
        self.assertIn("Failed to apply edit(s): 1", log_output)
        # Linter should not be called as no content was processed/cached for this file
        self.mock_python_linter.lint.assert_not_called()
        self.mock_html_linter.lint.assert_not_called()

    def test_apply_edit_with_crlf_normalization(self):
        """Test that CRLF line endings are normalized to LF."""
        rel_path = "crlf.txt"
        original_content = "line1\r\nline2\r\n"
        search_block = "line1\r\n"
        replace_block = "line_one\r\n"
        expected_content = "line_one\nline2\n"  # Note the LF endings

        self._setup_file_content(rel_path, original_content)
        self.mock_file_manager.get_files.return_value = {rel_path}

        edits = [(rel_path, search_block, replace_block)]

        with self.assertLogs('tinycoder.code_applier', level='INFO') as cm:
            result = self.code_applier.apply_edits(edits)

        self.assertEqual(result, (True, [], {rel_path}, {}))
        abs_path_str = f"/fake/repo/{rel_path}"  # Expected path string
        # Check that normalized content is written using call_args
        self.mock_file_manager.write_file.assert_called_once()
        write_call_args, _ = self.mock_file_manager.write_file.call_args
        self.assertEqual(str(write_call_args[0]), abs_path_str)
        self.assertEqual(write_call_args[1], expected_content)

        # Check essential log messages
        log_output = "\n".join(cm.output)
        self.assertIn(f"--- Diff for '{rel_path}' ---", log_output)
        self.assertIn(f"--- End Diff for '{rel_path}' ---", log_output)
        self.assertIn(f"Prepared edit 1 for '{rel_path}'", log_output)
        self.assertIn(f"Writing final changes to '{rel_path}'...", log_output)
        self.assertIn(f"Successfully saved changes to '{rel_path}'", log_output)

    def test_empty_edits_list(self):
        """Test calling apply_edits with an empty list."""
        edits = []
        # No logs expected for empty edits list
        with self.assertNoLogs('tinycoder.code_applier', level='INFO'):
             result = self.code_applier.apply_edits(edits)

        self.assertEqual(
            result, (True, [], set(), {})
        )  # Success, no failures, no modified, no lint
        self.mock_file_manager.write_file.assert_not_called()
        self.mock_python_linter.lint.assert_not_called()
        self.mock_html_linter.lint.assert_not_called()
        # No error logs expected, checked by assertNoLogs

    def test_fail_get_abs_path(self):
        """Test failure when get_abs_path returns None."""
        rel_path = "bad/path.py"

        # Configure the mock to return None for the specific bad path
        def get_abs_path_side_effect(p):
            if p == rel_path:
                return None
            # Need to reference the original side effect for other paths if it was complex,
            # or recreate the simple one if it wasn't. Assuming simple case here.
            return Path(f"/fake/repo/{p}")

        # Assign the new side effect
        self.mock_file_manager.get_abs_path.side_effect = get_abs_path_side_effect

        edits = [(rel_path, "search", "replace")]

        # No logs expected at ERROR for this failure as the loop continues immediately
        # However, the final summary error *is* logged. Check for that.
        with self.assertLogs('tinycoder.code_applier', level='ERROR') as cm:
            result = self.code_applier.apply_edits(edits)


        # Check the outcome
        self.assertEqual(
            result, (False, [1], set(), {})
        )  # Failed, index 1, no modified files, no lint errors

        # Verify the mock was called with the bad path
        self.mock_file_manager.get_abs_path.assert_called_with(rel_path)

        # Verify no read/write attempts were made for this edit
        self.mock_file_manager.read_file.assert_not_called()
        self.mock_file_manager.write_file.assert_not_called()

        # Verify the *correct* summary error message logged by CodeApplier at the end
        self.assertIn("Failed to apply edit(s): 1", "\n".join(cm.output))
        # Note: CodeApplier doesn't log the "Cannot resolve path" itself; FileManager might.
        # We only assert the summary error from CodeApplier.

        # Verify linters were not called for this non-existent path
        self.mock_python_linter.lint.assert_not_called()
        self.mock_html_linter.lint.assert_not_called()

    def test_apply_delete_block(self):
        """Test deleting a block of code using an empty replace_block."""
        rel_path = "delete_me.py"
        original_content = "line1\n# Delete this block\nline2\nline3"
        search_block = "# Delete this block\nline2\n"
        replace_block = ""  # Empty replace block signifies deletion
        expected_content = "line1\nline3"

        self._setup_file_content(rel_path, original_content)
        self.mock_file_manager.get_files.return_value = {rel_path}

        edits = [(rel_path, search_block, replace_block)]

        with self.assertLogs('tinycoder.code_applier', level='INFO') as cm:
            result = self.code_applier.apply_edits(edits)

        self.assertEqual(result, (True, [], {rel_path}, {}))
        abs_path_str = f"/fake/repo/{rel_path}"

        # Check write call
        self.mock_file_manager.write_file.assert_called_once()
        write_call_args, _ = self.mock_file_manager.write_file.call_args
        self.assertEqual(str(write_call_args[0]), abs_path_str)
        self.assertEqual(write_call_args[1], expected_content)

        # Check linter call
        self.mock_python_linter.lint.assert_called_once()
        lint_call_args, _ = self.mock_python_linter.lint.call_args
        self.assertEqual(str(lint_call_args[0]), abs_path_str)
        self.assertEqual(lint_call_args[1], expected_content)

        # Check logs for diff, prepare, write, save
        log_output = "\n".join(cm.output)
        self.assertIn(f"--- Diff for '{rel_path}' ---", log_output)
        self.assertIn(f"Prepared edit 1 for '{rel_path}'", log_output)
        self.assertIn(f"Writing final changes to '{rel_path}'...", log_output)
        self.assertIn(f"Successfully saved changes to '{rel_path}'", log_output)

    def test_apply_mixed_batch(self):
        """Test applying a batch of edits with mixed outcomes across files."""
        # Clear previous mock states just in case (though setUp should handle it)
        self.mock_path_objects.clear()
        self.mock_file_contents.clear()

        # Setup initial file states using the helper
        file_a_path = "file_a.py"
        file_a_orig = "print('original A')"
        file_a_abs_str = f"/fake/repo/{file_a_path}"
        self._setup_file_content(file_a_path, file_a_orig)

        new_file_path = "new_file.txt"
        new_file_abs_str = f"/fake/repo/{new_file_path}"
        self._setup_file_content(new_file_path, None, exists=False) # New file

        file_b_path = "file_b.py"
        file_b_orig = "print('original B')"
        file_b_abs_str = f"/fake/repo/{file_b_path}"
        self._setup_file_content(file_b_path, file_b_orig)

        file_c_path = "file_c.html"
        file_c_orig = "<p>Hello</p>"
        file_c_abs_str = f"/fake/repo/{file_c_path}"
        self._setup_file_content(file_c_path, file_c_orig)

        file_d_path = "file_d.py"
        file_d_orig = "unchanged_var = 1"
        file_d_abs_str = f"/fake/repo/{file_d_path}"
        self._setup_file_content(file_d_path, file_d_orig)

        # Mock initial file manager context
        # This now needs to contain the *relative* paths
        self.mock_file_manager.get_files.return_value = {
            file_a_path, file_b_path, file_c_path, file_d_path
        }

        # Setup mocks for specific outcomes
        lint_error_c = "Mismatched tag on C"
        self.mock_html_linter.lint.side_effect = lambda path, content: (
            lint_error_c if "file_c.html" in str(path) else None
        )
        self.mock_python_linter.lint.return_value = None # Default no error for others

        # Define the mixed batch of edits
        edits = [
            # 1. Successful edit on file_a.py
            (file_a_path, "original A", "modified A"),
            # 2. Creation of new_file.txt (ask for confirm, assume 'y')
            (new_file_path, "", "This is a new file."),
            # 3. Failing edit on file_b.py (search not found)
            (file_b_path, "search_not_found", "this won't apply"),
            # 4. Successful edit on file_c.html, but results in lint error
            (file_c_path, "Hello", "<b>World</b>"), # Intentional bad HTML
            # 5. Edit on file_d.py that results in no change
            (file_d_path, "unchanged_var = 1", "unchanged_var = 1"),
        ]

        # Mock user confirmation for the new file
        self.mock_input_func.return_value = 'y'

        # Capture logs (expect both INFO and ERROR)
        with self.assertLogs('tinycoder.code_applier', level='INFO') as cm:
            result = self.code_applier.apply_edits(edits)

        # Assertions
        all_succeeded, failed_indices, modified_files, lint_errors = result

        self.assertFalse(all_succeeded, "Overall success should be False due to failed edit")
        self.assertEqual(failed_indices, [3], "Edit 3 (file_b) should have failed")

        # Check modified files: only successfully written files
        self.assertEqual(
            modified_files,
            {file_a_path, new_file_path, file_c_path},
            "Modified files should include A, new, and C, but not B (failed) or D (unchanged)"
        )

        # Check lint errors
        self.assertEqual(
            lint_errors,
            {file_c_path: lint_error_c},
            "Lint errors should only contain the error for file C"
        )

        # Check file manager calls
        # Add file called for new file
        self.mock_file_manager.add_file.assert_called_once_with(new_file_path)

        # --- Verify Write Calls ---
        # Check which mock Path objects were passed to write_file
        write_calls = self.mock_file_manager.write_file.call_args_list
        written_paths = {str(c.args[0]) for c in write_calls} # Extract path strings
        written_content = {c.args[0]: c.args[1] for c in write_calls} # Map path obj to content

        self.assertEqual(written_paths, {file_a_abs_str, new_file_abs_str, file_c_abs_str},
                         "Should have written to A, new_file, and C")
        self.assertEqual(self.mock_file_manager.write_file.call_count, 3, "Should only write 3 files")

        # Verify content written for each file (using the correct mock path objects)
        path_a_mock = self.mock_path_objects[file_a_abs_str]
        path_new_mock = self.mock_path_objects[new_file_abs_str]
        path_c_mock = self.mock_path_objects[file_c_abs_str]

        self.assertEqual(written_content.get(path_a_mock), "print('modified A')")
        self.assertEqual(written_content.get(path_new_mock), "This is a new file.")
        self.assertEqual(written_content.get(path_c_mock), "<p><b>World</b></p>")


        # --- Verify Linter Calls ---
        # Linters are called on A, new, B(original), C, D(original)
        py_lint_calls = self.mock_python_linter.lint.call_args_list
        py_linted_paths = {str(c.args[0]) for c in py_lint_calls}
        py_linted_content = {c.args[0]: c.args[1] for c in py_lint_calls}

        self.assertEqual(py_linted_paths, {file_a_abs_str, file_b_abs_str, file_d_abs_str},
                         "Python linter should be called on A, B, and D")
        self.assertEqual(self.mock_python_linter.lint.call_count, 3)

        # Verify content linted for Python files (using the correct mock path objects)
        path_b_mock = self.mock_path_objects[file_b_abs_str]
        path_d_mock = self.mock_path_objects[file_d_abs_str]
        self.assertEqual(py_linted_content.get(path_a_mock), "print('modified A')") # Linted modified A
        self.assertEqual(py_linted_content.get(path_b_mock), file_b_orig) # Linted original B (edit failed)
        self.assertEqual(py_linted_content.get(path_d_mock), file_d_orig) # Linted original D (no change)

        html_lint_calls = self.mock_html_linter.lint.call_args_list
        html_linted_paths = {str(c.args[0]) for c in html_lint_calls}
        html_linted_content = {c.args[0]: c.args[1] for c in html_lint_calls}

        self.assertEqual(html_linted_paths, {file_c_abs_str}, "HTML linter should be called on C")
        self.assertEqual(self.mock_html_linter.lint.call_count, 1)
        self.assertEqual(html_linted_content.get(path_c_mock), "<p><b>World</b></p>") # Linted modified C
        # Note: new_file.txt is not linted as it has no specific linter

        # Check specific log messages
        log_output = "\n".join(cm.output)
        self.assertIn(f"Prepared edit 1 for '{file_a_path}'", log_output) # Success A
        self.assertIn(f"Prepared edit 2 for creation of '{new_file_path}'", log_output) # Create New
        self.assertIn(f"Edit 3: SEARCH block not found exactly in '{file_b_path}'. Edit failed.", log_output) # Fail B
        self.assertIn(f"Prepared edit 4 for '{file_c_path}'", log_output) # Prepare C
        self.assertIn(f"Edit 5 for '{file_d_path}' resulted in no changes to current state.", log_output) # No change D
        self.assertIn(f"Writing final changes to '{file_a_path}'...", log_output) # Write A
        self.assertIn(f"Writing final changes to '{new_file_path}'...", log_output) # Write New
        self.assertIn(f"Writing final changes to '{file_c_path}'...", log_output) # Write C
        self.assertIn(f"Failed to apply edit(s): 3", log_output) # Final error summary


if __name__ == "__main__":
    unittest.main()
