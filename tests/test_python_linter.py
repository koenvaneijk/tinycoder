import unittest
from pathlib import Path
from tinycoder.linters.python_linter import PythonLinter


class TestPythonLinter(unittest.TestCase):

    def setUp(self):
        self.linter = PythonLinter()
        self.dummy_path = Path("dummy_file.py")

    def test_valid_syntax(self):
        """Test linting code with valid Python syntax."""
        valid_code = """
def hello(name):
    print(f"Hello, {name}!")

if __name__ == "__main__":
    hello("World")
"""
        result = self.linter.lint(self.dummy_path, valid_code)
        self.assertIsNone(result, "Should return None for valid syntax")

    def test_invalid_syntax(self):
        """Test linting code with a Python syntax error."""
        invalid_code = """
def greet(name)
    print(f"Hi, {name}!")
"""
        result = self.linter.lint(self.dummy_path, invalid_code)
        self.assertIsNotNone(
            result, "Should return an error message for invalid syntax"
        )
        self.assertIn("SyntaxError", result)
        self.assertIn(self.dummy_path.name, result)
        self.assertIn("expected ':'", result)  # Specific SyntaxError message
        self.assertIn("line 2", result)

    def test_value_error_null_byte(self):
        """Test linting code containing a null byte (causes ValueError)."""
        invalid_code_null = "print('Hello')\x00print('World')"
        result = self.linter.lint(self.dummy_path, invalid_code_null)
        self.assertIsNotNone(
            result, "Should return an error message for code with null byte"
        )
        self.assertIn(
            "SyntaxError", result
        )  # compile() raises SyntaxError for null bytes
        self.assertIn(self.dummy_path.name, result)
        self.assertIn(
            "source code string cannot contain null bytes", result
        )  # Specific message

    def test_empty_content(self):
        """Test linting an empty string."""
        empty_code = ""
        result = self.linter.lint(self.dummy_path, empty_code)
        self.assertIsNone(result, "Should return None for empty content")

    def test_complex_valid_code(self):
        """Test linting slightly more complex valid code."""
        complex_code = """
import os

class MyClass:
    def __init__(self, value):
        self.value = value

    def process(self):
        return self.value * 2

def run():
    instance = MyClass(10)
    result = instance.process()
    print(f"Result: {result}")

run()
"""
        result = self.linter.lint(self.dummy_path, complex_code)
        self.assertIsNone(result, "Should return None for complex valid syntax")


if __name__ == "__main__":
    unittest.main()
