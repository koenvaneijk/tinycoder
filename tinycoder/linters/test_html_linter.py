import unittest
from pathlib import Path
from tinycoder.linters.html_linter import HTMLLinter

# Use a dummy path for testing purposes
DUMMY_PATH = Path("dummy.html")


class TestHTMLLinter(unittest.TestCase):

    def setUp(self):
        self.linter = HTMLLinter()

    def test_valid_html(self):
        html_content = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Test</title>
            <meta charset="utf-8">
            <link rel="stylesheet" href="style.css">
        </head>
        <body>
            <h1>Hello</h1>
            <p>This is a paragraph.<br>With a line break.</p>
            <img src="image.jpg" alt="Test image">
            <div><input type="text" name="test"></div>
        </body>
        </html>
        """
        result = self.linter.lint(DUMMY_PATH, html_content)
        self.assertIsNone(result, f"Expected no errors, but got:\n{result}")

    def test_mismatched_tags(self):
        html_content = """
        <html>
        <head><title>Mismatched</title></head>
        <body>
            <div><p>Uh oh</span></div> <!-- Mismatch: p vs span -->
        </body>
        </html>
        """
        result = self.linter.lint(DUMMY_PATH, html_content)
        self.assertIsNotNone(result, "Expected mismatch error, but got None")
        self.assertIn("Mismatched closing tag", result)
        self.assertIn("Found </span> but expected </p>", result)
        self.assertIn("line 5", result)  # Line where </span> occurs


    def test_closing_void_element(self):
        # Closing void elements like <br> is technically invalid in HTML5,
        # but browsers often tolerate it. Our linter currently ignores these.
        html_content = """
        <html><body><p>Line break closed?<br></br></p></body></html>
        """
        result = self.linter.lint(DUMMY_PATH, html_content)
        self.assertIsNone(
            result, f"Expected no errors for closing void element, but got:\n{result}"
        )


    def test_empty_content(self):
        html_content = ""
        result = self.linter.lint(DUMMY_PATH, html_content)
        self.assertIsNone(
            result, f"Expected no errors for empty content, but got:\n{result}"
        )

    def test_content_with_only_comment(self):
        html_content = "<!-- This is just a comment -->"
        result = self.linter.lint(DUMMY_PATH, html_content)
        self.assertIsNone(
            result, f"Expected no errors for comment-only content, but got:\n{result}"
        )

    def test_content_with_only_doctype(self):
        html_content = "<!DOCTYPE html>"
        result = self.linter.lint(DUMMY_PATH, html_content)
        self.assertIsNone(
            result, f"Expected no errors for doctype-only content, but got:\n{result}"
        )

if __name__ == "__main__":
    unittest.main()
