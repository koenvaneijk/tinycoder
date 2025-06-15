import unittest
import tempfile
import logging
import ast
from pathlib import Path
from unittest.mock import patch, MagicMock

# Ensure tinycoder is importable
import sys
import os

# Add the project root to the Python path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from tinycoder.repo_map import RepoMap
from tinycoder.local_import import find_local_imports_with_entities


# Helper function to create dummy files
def create_dummy_file(path: Path, content: str):
    """Creates a file with content, ensuring parent directories exist."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


class TestRepoMap(unittest.TestCase):
    """Tests for the RepoMap class."""

    def setUp(self):
        """Set up a temporary directory with sample files for testing."""
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root_dir = Path(self.temp_dir.name)

        # --- Python Files ---
        create_dummy_file(
            self.root_dir / "module1.py",
            """
import os
import sys

# A top-level function
def func_a(x, y=10):
    pass

class MyClass:
    # A method
    def method_b(self, z: int, *args, **kwargs) -> None:
        \"\"\"Method docstring.\"\"\"
        pass

    def _private_method(self):
        pass

# Another function
def func_c():
    pass
""",
        )
        create_dummy_file(
            self.root_dir / "subdir" / "module2.py",
            """
from ..module1 import MyClass # Relative import
from external_lib import External

class AnotherClass(MyClass):
    def __init__(self, name="default"):
        self.name = name

    async def async_method(self, param):
        pass
""",
        )
        create_dummy_file(
            self.root_dir / "empty.py",
            "",  # Empty python file
        )
        create_dummy_file(
            self.root_dir / "syntax_error.py",
            "def func_error( :",  # Python file with syntax error
        )
        create_dummy_file(
            self.root_dir / "pos_only.py",
            """
def pos_only_func(a, b, /, c, d=5):
    pass
""",
        )
        create_dummy_file(
            self.root_dir / "kw_only.py",
            """
def kw_only_func(*, key, value=None):
    pass

def mixed_kw_only(arg1, *args, key, value=None, **kwargs):
    pass
""",
        )
        # --- HTML Files ---
        create_dummy_file(
            self.root_dir / "index.html",
            """
<!DOCTYPE html>
<html>
<head>
    <meta charset="utf-8">
    <title>Test Title</title>
    <link rel="stylesheet" href="style.css">
    <script src="script.js" defer></script>
</head>
<body>
    <nav id="main-nav">Navigation</nav>
    <h1>Main Heading</h1>
    <div id="content">
        <p>Some content</p>
        <section id="features">
            <article class="feature">Feature 1</article>
        </section>
        <!-- A comment -->
        <form action="/submit" method="post" id="myForm">
            <button type="submit">Submit</button>
        </form>
    </div>
    <footer>Footer</footer>
    <script>console.log('inline');</script>
</body>
</html>
""",
        )
        create_dummy_file(
            self.root_dir / "subdir" / "other.html",
            "<html><body><p>Simple page</p></body></html>",
        )
        create_dummy_file(
            self.root_dir / "empty.html",
            "",  # Empty HTML file
        )
        create_dummy_file(
            self.root_dir / "malformed.html",
            "<html><body><p>Missing closing tag</body></html>",
        )
        # --- Excluded Files/Dirs ---
        create_dummy_file(
            self.root_dir / ".venv" / "lib" / "site.py",
            "print('in venv')",
        )
        create_dummy_file(
            self.root_dir / "__pycache__" / "cache.pyc",
            "binary data",
        )
        create_dummy_file(
            self.root_dir / "node_modules" / "lib.js",
            "console.log('node');",
        )
        create_dummy_file(
            self.root_dir / "data.txt",
            "Some text data",  # Non-python/html file
        )

        self.repo_map = RepoMap(str(self.root_dir))
        # Suppress logging during tests unless needed for debugging
        logging.disable(logging.CRITICAL)

    def tearDown(self):
        """Clean up the temporary directory."""
        self.temp_dir.cleanup()
        logging.disable(logging.NOTSET)  # Re-enable logging

    def test_init(self):
        """Test RepoMap initialization."""
        self.assertEqual(self.repo_map.root, self.root_dir)
        # Test default root (cwd)
        repo_map_default = RepoMap(None)
        self.assertEqual(repo_map_default.root, Path.cwd())

    def test_get_py_files(self):
        """Test discovery of Python files, excluding specified directories."""
        py_files = list(self.repo_map.get_py_files())
        rel_paths = {p.relative_to(self.root_dir) for p in py_files}

        expected_paths = {
            Path("module1.py"),
            Path("subdir/module2.py"),
            Path("empty.py"),
            Path("syntax_error.py"),
            Path("pos_only.py"),
            Path("kw_only.py"),
        }
        self.assertEqual(rel_paths, expected_paths)
        self.assertNotIn(Path(".venv/lib/site.py"), rel_paths)
        self.assertNotIn(Path("__pycache__/cache.pyc"), rel_paths)

    def test_get_html_files(self):
        """Test discovery of HTML files, excluding specified directories."""
        html_files = list(self.repo_map.get_html_files())
        rel_paths = {p.relative_to(self.root_dir) for p in html_files}

        expected_paths = {
            Path("index.html"),
            Path("subdir/other.html"),
            Path("empty.html"),
            Path("malformed.html"),
        }
        self.assertEqual(rel_paths, expected_paths)
        self.assertNotIn(Path("node_modules/lib.js"), rel_paths)

    @patch("tinycoder.repo_map.RepoMap.get_py_files", return_value=[])
    @patch("tinycoder.repo_map.RepoMap.get_html_files", return_value=[])
    def test_generate_map_no_files(self, mock_get_html, mock_get_py):
        """Test map generation when no files are found."""
        repo_map_str = self.repo_map.generate_map(set())
        self.assertEqual(repo_map_str, "") # Should return empty string


if __name__ == "__main__":
    unittest.main(argv=['first-arg-is-ignored'], exit=False)