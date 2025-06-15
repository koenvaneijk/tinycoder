import unittest
import os
import tempfile
from pathlib import Path
from typing import List, Tuple, Optional
from tinycoder.linters.css_validator import CssValidator


class TestCssValidator(unittest.TestCase):
    """Unit tests for the refactored CssValidator class using the lint method."""

    def setUp(self) -> None:
        """Set up test fixtures, if any."""
        # Create a temporary file for file path tests
        self.temp_file = tempfile.NamedTemporaryFile(
            delete=False, suffix=".css", mode="w", encoding="utf-8"
        )
        self.temp_file_path = self.temp_file.name
        self.test_path_obj = Path(self.temp_file_path) # For lint method

    def tearDown(self) -> None:
        """Tear down test fixtures, if any."""
        self.temp_file.close()
        os.unlink(self.temp_file_path)  # Clean up the temporary file

    def _write_to_temp_file(self, content: str) -> None:
        """Helper method to write content to the temp file."""
        with open(self.temp_file_path, "w", encoding="utf-8") as f:
            f.write(content)

    # --- Initialization Test ---
    def test_init(self) -> None:
        """Test that CssValidator initializes without error."""
        try:
            _ = CssValidator()
        except Exception as e:
            self.fail(f"CssValidator initialization failed: {e}")

    # --- Comment Removal Tests (Testing Helper) ---
    # These test the internal helper directly, ensuring it works as expected.
    # The public `lint` method uses this helper.

    def test__remove_comments_single_line(self) -> None:
        """Test _remove_comments with single-line style comments."""
        css = "h1 { /* color: blue; */ color: red; }"
        expected = "h1 {  color: red; }"
        validator = CssValidator() # Instantiate
        result = validator._remove_comments(css)
        self.assertEqual(result, expected)

    def test__remove_comments_multi_line(self) -> None:
        """Test _remove_comments with multi-line comments."""
        css = "p {\n  /* This is a\n     multi-line comment */\n  font-weight: bold;\n}"
        expected = "p {\n  \n  font-weight: bold;\n}"
        validator = CssValidator() # Instantiate
        result = validator._remove_comments(css)
        self.assertEqual(result, expected)

    def test__remove_comments_no_comments(self) -> None:
        """Test _remove_comments with no comments remains unchanged."""
        css = "div { border: 1px solid black; }"
        validator = CssValidator() # Instantiate
        result = validator._remove_comments(css)
        self.assertEqual(result, css)

    # --- Lint Method Tests (Primary Public Interface) ---

    def test_lint_balanced_braces(self) -> None:
        """Test lint() with correctly balanced braces."""
        css = "body { color: red; } p { font-size: 1em; }"
        validator = CssValidator()
        result = validator.lint(self.test_path_obj, css)
        self.assertIsNone(result, f"Expected no errors, got: {result}")

    def test_lint_missing_closing_brace(self) -> None:
        """Test lint() with missing closing brace."""
        css = "body { color: red;"
        validator = CssValidator()
        result = validator.lint(self.test_path_obj, css)
        self.assertIsNotNone(result)
        self.assertIn("Syntax Error: Unmatched '{' found.", result)

    def test_lint_missing_opening_brace(self) -> None:
        """Test lint() with missing opening brace (extra closing brace)."""
        css = "body color: red; }"
        validator = CssValidator()
        result = validator.lint(self.test_path_obj, css)
        self.assertIsNotNone(result)
        self.assertIn("Syntax Error: Unexpected '}'", result)
        self.assertIn("near line 1", result) # Check line number reporting

    def test_lint_extra_closing_brace(self) -> None:
        """Test lint() with extra closing brace within rules."""
        css = "body { color: red; } }"
        validator = CssValidator()
        result = validator.lint(self.test_path_obj, css)
        self.assertIsNotNone(result)
        self.assertIn("Syntax Error: Unexpected '}'", result)
        self.assertIn("near line 1", result) # Check line number reporting

    def test_lint_valid_rule_structure(self) -> None:
        """Test lint() with valid property: value; structure."""
        css = "h1 { color: blue; font-weight: bold; }"
        validator = CssValidator()
        result = validator.lint(self.test_path_obj, css)
        self.assertIsNone(result, f"Expected no errors, got: {result}")

    def test_lint_rule_missing_colon(self) -> None:
        """Test lint() with rule structure missing colon."""
        css = "h1 { color blue; }"
        validator = CssValidator()
        result = validator.lint(self.test_path_obj, css)
        self.assertIsNotNone(result)
        self.assertIn("Syntax Error: Missing ':' in declaration near line 1", result)
        self.assertIn("Found: 'color blue'", result)

    def test_lint_rule_missing_value(self) -> None:
        """Test lint() with rule structure missing value after colon."""
        css = "h1 { color: ; }"
        validator = CssValidator()
        result = validator.lint(self.test_path_obj, css)
        self.assertIsNotNone(result)
        self.assertIn("Syntax Error: Missing value after ':' near line 1", result)
        self.assertIn("Found: 'color:'", result)

    def test_lint_rule_missing_semicolon(self) -> None:
        """Test lint() with rule structure missing semicolon (should be ok)."""
        # CSS allows the last rule to omit the semicolon
        css = "h1 { color: blue }"
        validator = CssValidator()
        result = validator.lint(self.test_path_obj, css)
        self.assertIsNone(result, f"Expected no errors for missing final semicolon, got: {result}")

    def test_lint_multiple_structure_errors(self) -> None:
        """Test lint() with multiple rule structure errors."""
        css = "p { font-size 12px; color: ; }"
        validator = CssValidator()
        result = validator.lint(self.test_path_obj, css)
        self.assertIsNotNone(result)
        # Errors are combined into a single string, check for substrings
        self.assertIn("Missing ':'", result)
        self.assertIn("Missing value after ':'", result)

    def test_lint_valid_css_complex(self) -> None:
        """Test lint() on more complex valid CSS content."""
        css = """
        /* A simple valid CSS */
        body {
            font-family: sans-serif;
            line-height: 1.5;
        }

        h1, h2 {
            color: #333;
            margin-bottom: 0.5em; /* Comment here */
        }

        p {
            color: #555;
        }
        """
        validator = CssValidator()
        result = validator.lint(self.test_path_obj, css)
        self.assertIsNone(result, f"Expected no errors, got: {result}")

    def test_lint_multiple_issues(self) -> None:
        """Test lint() with multiple different issues."""
        css = "body { color red; \n p { font-size: 10px; \n h1 {color: blue;} \n h1 { border: none; }" # Missing '}', missing ':'
        validator = CssValidator()
        result = validator.lint(self.test_path_obj, css)
        self.assertIsNotNone(result)
        # Check that both types of errors are mentioned in the final string
        self.assertIn("Unmatched '{'", result)
        self.assertIn("Missing ':'", result)

    def test_lint_empty_content(self) -> None:
        """Test lint() with empty CSS content."""
        css = ""
        validator = CssValidator()
        result = validator.lint(self.test_path_obj, css)
        self.assertIsNone(result, f"Expected no errors for empty content, got: {result}")

    def test_lint_content_with_only_comments(self) -> None:
        """Test lint() with content containing only comments."""
        css = "/* Only comments */\n/* Another one */"
        validator = CssValidator()
        result = validator.lint(self.test_path_obj, css)
        self.assertIsNone(result, f"Expected no errors for comment-only content, got: {result}")



    def test_lint_from_file_valid(self) -> None:
        """Test lint() reading from a valid CSS file."""
        css = "div { border: 1px solid green; }"
        self._write_to_temp_file(css)
        validator = CssValidator()
        # Read content to pass to lint
        with open(self.test_path_obj, 'r', encoding='utf-8') as f:
            content = f.read()
        result = validator.lint(self.test_path_obj, content)
        self.assertIsNone(result, f"Expected no errors reading from file, got: {result}")

    def test_lint_from_file_invalid(self) -> None:
        """Test lint() reading from an invalid CSS file."""
        css = "div border: 1px solid green; }"  # Missing '{'
        self._write_to_temp_file(css)
        validator = CssValidator()
        # Read content to pass to lint
        with open(self.test_path_obj, 'r', encoding='utf-8') as f:
            content = f.read()
        result = validator.lint(self.test_path_obj, content)
        self.assertIsNotNone(result)
        # Should catch the unexpected '}' first due to brace check priority
        self.assertIn("Unexpected '}'", result)


if __name__ == "__main__":
    unittest.main()
