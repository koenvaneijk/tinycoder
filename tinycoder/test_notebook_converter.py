import json
import unittest

from tinycoder.notebook_converter import ipynb_to_py, py_to_ipynb


class TestNotebookConverter(unittest.TestCase):
    def test_ipynb_to_py_basic_conversion(self):
        notebook = {
            "cells": [
                {
                    "cell_type": "markdown",
                    "metadata": {},
                    "source": ["# Heading\n", "Some text\n", "Line without newline"],
                },
                {
                    "cell_type": "code",
                    "metadata": {},
                    "execution_count": 1,
                    "outputs": [],
                    "source": ["print('Hello')\n", "a=1\n"],
                },
                {
                    "cell_type": "code",
                    "metadata": {},
                    "source": "x = 42\nprint(x)\n",
                },
            ],
            "metadata": {"kernelspec": {"name": "python3"}},
            "nbformat": 4,
            "nbformat_minor": 5,
        }
        nb_json = json.dumps(notebook, indent=2)

        py_script = ipynb_to_py(nb_json)

        expected = (
            "#%% [markdown]\n"
            "# # Heading\n"
            "# Some text\n"
            "# Line without newline\n"
            "\n"
            "#%%\n"
            "print('Hello')\n"
            "a=1\n"
            "\n"
            "#%%\n"
            "x = 42\n"
            "print(x)\n"
        )
        self.assertEqual(py_script, expected)

    def test_ipynb_to_py_invalid_inputs(self):
        # Not JSON
        self.assertEqual(ipynb_to_py("not json"), "")

        # Missing 'cells'
        self.assertEqual(ipynb_to_py(json.dumps({"nbformat": 4})), "")

        # 'cells' not a list
        self.assertEqual(ipynb_to_py(json.dumps({"cells": {}})), "")

    def test_py_to_ipynb_basic_roundtrip(self):
        # Build a script matching the output of test_ipynb_to_py_basic_conversion
        py_script = (
            "#%% [markdown]\n"
            "# # Heading\n"
            "# Some text\n"
            "# Line without newline\n"
            "\n"
            "#%%\n"
            "print('Hello')\n"
            "a=1\n"
            "\n"
            "#%%\n"
            "x = 42\n"
            "print(x)\n"
        )
        original_nb = {
            "cells": [
                {
                    "cell_type": "markdown",
                    "metadata": {},
                    "source": ["original\n"],
                }
            ],
            "metadata": {"custom": 123},
            "nbformat": 4,
            "nbformat_minor": 5,
        }
        result_json = py_to_ipynb(py_script, json.dumps(original_nb))
        result = json.loads(result_json)

        # Top-level metadata preserved
        self.assertEqual(result["nbformat"], 4)
        self.assertEqual(result["nbformat_minor"], 5)
        self.assertEqual(result["metadata"], {"custom": 123})

        # Cells reconstructed correctly
        self.assertEqual(len(result["cells"]), 3)

        # Markdown cell content should be uncommented with keepends where present
        md = result["cells"][0]
        self.assertEqual(md["cell_type"], "markdown")
        self.assertEqual(
            md["source"],
            ["# Heading\n", "Some text\n", "Line without newline"],
        )

        # First code cell
        c1 = result["cells"][1]
        self.assertEqual(c1["cell_type"], "code")
        # No trailing newline on last line due to rstrip in ipynb_to_py
        self.assertEqual(c1["source"], ["print('Hello')\n", "a=1"])

        # Second code cell
        c2 = result["cells"][2]
        self.assertEqual(c2["cell_type"], "code")
        self.assertEqual(c2["source"], ["x = 42\n", "print(x)"])

    def test_py_to_ipynb_invalid_original_creates_skeleton(self):
        py_script = "#%%\nprint(123)\n"
        result_json = py_to_ipynb(py_script, "not json")
        result = json.loads(result_json)

        self.assertEqual(result["nbformat"], 4)
        self.assertEqual(result["nbformat_minor"], 5)
        self.assertEqual(result["metadata"], {})
        self.assertEqual(len(result["cells"]), 1)
        self.assertEqual(result["cells"][0]["cell_type"], "code")
        self.assertEqual(result["cells"][0]["source"], ["print(123)\n"])

    def test_markdown_uncommenting_variants(self):
        # Mix of "# " and "#" prefixes and edge cases
        py_script = (
            "#%% [markdown]\n"
            "# Title\n"
            "#Plain\n"
            "Plain\n"
            "#\n"
            "#  "
        )
        result_json = py_to_ipynb(py_script, json.dumps({"cells": [], "nbformat": 4, "nbformat_minor": 5, "metadata": {}}))
        result = json.loads(result_json)
        self.assertEqual(len(result["cells"]), 1)
        cell = result["cells"][0]
        self.assertEqual(cell["cell_type"], "markdown")
        # Last line has no trailing newline; others do
        self.assertEqual(cell["source"], ["Title\n", "Plain\n", "Plain\n", "\n", " "])

    def test_ipynb_to_py_markdown_source_as_string(self):
        notebook = {
            "cells": [
                {
                    "cell_type": "markdown",
                    "metadata": {},
                    "source": "# Title\nParagraph\n",
                }
            ],
            "metadata": {},
            "nbformat": 4,
            "nbformat_minor": 5,
        }
        nb_json = json.dumps(notebook)
        py_script = ipynb_to_py(nb_json)
        expected = "#%% [markdown]\n# # Title\n# Paragraph\n"
        self.assertEqual(py_script, expected)


if __name__ == "__main__":
    unittest.main()