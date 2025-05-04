import unittest
import os
import tempfile
from typing import List, Tuple
from tinycoder.linters.css_validator import CssValidator


class TestCssValidator(unittest.TestCase):
    """Unit tests for the CssValidator class."""

    def setUp(self) -> None:
        """Set up test fixtures, if any."""
        # Create a temporary file for file path tests
        self.temp_file = tempfile.NamedTemporaryFile(
            delete=False, suffix=".css", mode="w", encoding="utf-8"
        )
        self.temp_file_path = self.temp_file.name

    def tearDown(self) -> None:
        """Tear down test fixtures, if any."""
        self.temp_file.close()
        os.unlink(self.temp_file_path)  # Clean up the temporary file

    def _write_to_temp_file(self, content: str) -> None:
        """Helper method to write content to the temp file."""
        with open(self.temp_file_path, "w", encoding="utf-8") as f:
            f.write(content)

    # --- Initialization Tests ---

    def test_init_with_content(self) -> None:
        """Test initialization with direct CSS content."""
        css = "body { color: red; }"
        validator = CssValidator(css_content=css)
        self.assertEqual(validator._css_content, css)
        self.assertIsNone(validator._file_path)

    def test_init_with_file_path(self) -> None:
        """Test initialization with a file path."""
        css = "p { font-size: 12px; }"
        self._write_to_temp_file(css)
        validator = CssValidator(file_path=self.temp_file_path)
        self.assertEqual(validator._css_content, css)
        self.assertEqual(validator._file_path, self.temp_file_path)

    def test_init_no_args(self) -> None:
        """Test initialization with no arguments raises ValueError."""
        with self.assertRaisesRegex(
            ValueError, "Provide either css_content or file_path"
        ):
            CssValidator()

    def test_init_both_args(self) -> None:
        """Test initialization with both arguments raises ValueError."""
        with self.assertRaisesRegex(
            ValueError, "Provide either css_content or file_path"
        ):
            CssValidator(css_content="a{}", file_path=self.temp_file_path)

    def test_init_file_not_found(self) -> None:
        """Test initialization with a non-existent file raises FileNotFoundError."""
        non_existent_path = "non_existent_style.css"
        # Ensure the file doesn't exist before the test
        if os.path.exists(non_existent_path):
            os.unlink(non_existent_path)
        with self.assertRaises(FileNotFoundError):
            CssValidator(file_path=non_existent_path)

    # --- Comment Removal Tests ---

    def test_remove_single_line_comment(self) -> None:
        """Test removal of single-line style comments."""
        css = "h1 { /* color: blue; */ color: red; }"
        expected = "h1 {  color: red; }"
        validator = CssValidator(css_content=css)
        validator._remove_comments()
        self.assertEqual(validator._content_no_comments, expected)

    def test_remove_multi_line_comment(self) -> None:
        """Test removal of multi-line comments."""
        css = "p {\n  /* This is a\n     multi-line comment */\n  font-weight: bold;\n}"
        expected = "p {\n  \n  font-weight: bold;\n}"
        validator = CssValidator(css_content=css)
        validator._remove_comments()
        self.assertEqual(validator._content_no_comments, expected)

    def test_no_comments(self) -> None:
        """Test content with no comments remains unchanged."""
        css = "div { border: 1px solid black; }"
        validator = CssValidator(css_content=css)
        validator._remove_comments()
        self.assertEqual(validator._content_no_comments, css)

    # --- Brace Balance Tests ---

    def test_balanced_braces(self) -> None:
        """Test correctly balanced braces."""
        css = "body { color: red; } p { font-size: 1em; }"
        validator = CssValidator(css_content=css)
        validator._remove_comments()
        is_balanced = validator._check_brace_balance()
        self.assertTrue(is_balanced)
        self.assertEqual(validator._errors, [])

    def test_missing_closing_brace(self) -> None:
        """Test missing closing brace."""
        css = "body { color: red;"
        validator = CssValidator(css_content=css)
        validator._remove_comments()
        is_balanced = validator._check_brace_balance()
        self.assertTrue(is_balanced)  # Returns True as it only fails on early '}'
        self.assertIn("Syntax Error: Unmatched '{' found.", validator._errors[0])

    def test_missing_opening_brace(self) -> None:
        """Test missing opening brace (extra closing brace)."""
        css = "body color: red; }"
        validator = CssValidator(css_content=css)
        validator._remove_comments()
        is_balanced = validator._check_brace_balance()
        self.assertFalse(is_balanced)  # Returns False on early '}'
        self.assertIn("Syntax Error: Unexpected '}'", validator._errors[0])
        self.assertIn("near line 1", validator._errors[0])

    def test_extra_closing_brace(self) -> None:
        """Test extra closing brace within rules."""
        css = "body { color: red; } }"
        validator = CssValidator(css_content=css)
        validator._remove_comments()
        is_balanced = validator._check_brace_balance()
        self.assertFalse(is_balanced)  # Returns False on early '}'
        self.assertIn("Syntax Error: Unexpected '}'", validator._errors[0])
        self.assertIn("near line 1", validator._errors[0])

    # --- Rule Structure Tests ---

    def test_valid_rule_structure(self) -> None:
        """Test valid property: value; structure."""
        css = "h1 { color: blue; font-weight: bold; }"
        validator = CssValidator(css_content=css)
        validator._remove_comments()
        # Assume brace balance check passed or wasn't fatal
        validator._check_brace_balance()  # Run to populate internal state if needed
        validator._check_rule_structure()
        self.assertEqual(validator._errors, [])

    def test_rule_missing_colon(self) -> None:
        """Test rule structure with missing colon."""
        css = "h1 { color blue; }"
        validator = CssValidator(css_content=css)
        validator._remove_comments()
        validator._check_brace_balance()
        validator._check_rule_structure()
        self.assertEqual(len(validator._errors), 1)
        self.assertIn(
            "Syntax Error: Missing ':' in declaration near line 1", validator._errors[0]
        )
        self.assertIn("Found: 'color blue'", validator._errors[0])

    def test_rule_missing_value(self) -> None:
        """Test rule structure with missing value after colon."""
        css = "h1 { color: ; }"
        validator = CssValidator(css_content=css)
        validator._remove_comments()
        validator._check_brace_balance()
        validator._check_rule_structure()
        self.assertEqual(len(validator._errors), 1)
        self.assertIn(
            "Syntax Error: Missing value after ':' near line 1", validator._errors[0]
        )
        self.assertIn("Found: 'color:'", validator._errors[0])

    def test_rule_missing_semicolon(self) -> None:
        """Test rule structure with missing semicolon (should be ok)."""
        # CSS allows the last rule to omit the semicolon
        css = "h1 { color: blue }"
        validator = CssValidator(css_content=css)
        validator._remove_comments()
        validator._check_brace_balance()
        validator._check_rule_structure()
        self.assertEqual(validator._errors, [])

    def test_multiple_structure_errors(self) -> None:
        """Test multiple rule structure errors."""
        css = "p { font-size 12px; color: ; }"
        validator = CssValidator(css_content=css)
        validator._remove_comments()
        validator._check_brace_balance()
        validator._check_rule_structure()
        self.assertEqual(len(validator._errors), 2)
        self.assertTrue(any("Missing ':'" in e for e in validator._errors))
        self.assertTrue(any("Missing value after ':'" in e for e in validator._errors))

    # --- Duplicate Selector Tests ---

    # --- Validate Method Tests (Integration) ---

    def test_validate_valid_css(self) -> None:
        """Test validate() on valid CSS content."""
        css = """
        /* A simple valid CSS */
        body {
            font-family: sans-serif;
            line-height: 1.5;
        }

        h1, h2 {
            color: #333;
            margin-bottom: 0.5em;
        }

        p {
            color: #555; /* Paragraph color */
        }
        """
        validator = CssValidator(css_content=css)
        is_valid, messages = validator.validate()
        self.assertTrue(is_valid)
        self.assertEqual(messages, [])

    def test_validate_invalid_brace(self) -> None:
        """Test validate() with unbalanced braces."""
        css = "body { color: red;"
        validator = CssValidator(css_content=css)
        is_valid, messages = validator.validate()
        self.assertFalse(is_valid)
        self.assertEqual(len(messages), 1)
        self.assertIn("Unmatched '{'", messages[0])

    def test_validate_invalid_structure(self) -> None:
        """Test validate() with invalid rule structure."""
        css = "body { color red; }"
        validator = CssValidator(css_content=css)
        is_valid, messages = validator.validate()
        self.assertFalse(is_valid)
        self.assertEqual(len(messages), 1)
        self.assertIn("Missing ':'", messages[0])

    def test_validate_multiple_issues(self) -> None:
        """Test validate() with multiple different issues."""
        css = "body { color red; \n p { font-size: 10px; \n h1 {color: blue;} \n h1 { border: none; }"  # Missing '}', missing ':', duplicate h1
        validator = CssValidator(css_content=css)
        is_valid, messages = validator.validate()
        self.assertFalse(is_valid)
        self.assertEqual(len(messages), 2, f"Messages: {messages}")
        self.assertTrue(any("Unmatched '{'" in m for m in messages))
        self.assertTrue(any("Missing ':'" in m for m in messages))

    def test_validate_valid_css_from_file(self) -> None:
        """Test validate() on a valid CSS file."""
        css = "div { border: 1px solid green; }"
        self._write_to_temp_file(css)
        validator = CssValidator(file_path=self.temp_file_path)
        is_valid, messages = validator.validate()
        self.assertTrue(is_valid)
        self.assertEqual(messages, [])

    def test_validate_invalid_css_from_file(self) -> None:
        """Test validate() on an invalid CSS file."""
        css = "div border: 1px solid green; }"  # Missing '{'
        self._write_to_temp_file(css)
        validator = CssValidator(file_path=self.temp_file_path)
        is_valid, messages = validator.validate()
        self.assertFalse(is_valid)
        self.assertEqual(len(messages), 1)  # Should catch the unexpected '}' first
        self.assertIn("Unexpected '}'", messages[0])


if __name__ == "__main__":
    unittest.main()
