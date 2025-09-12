import json
import re

def ipynb_to_py(notebook_content: str) -> str:
    """
    Converts a Jupyter Notebook's JSON content to a Python script with '#%%' separators.
    This format is compatible with tools like VS Code, Jupytext, and PyCharm.
    """
    try:
        data = json.loads(notebook_content)
        if "cells" not in data or not isinstance(data["cells"], list):
            return ""  # Not a valid notebook format
    except json.JSONDecodeError:
        return ""  # Not valid JSON

    py_script_parts = []
    for cell in data["cells"]:
        cell_type = cell.get("cell_type")
        source = cell.get("source", [])

        # The 'source' can be a list of strings or a single string.
        if isinstance(source, list):
            source_content = "".join(source)
        else:
            source_content = str(source)

        if cell_type == "code":
            # Standard code cell
            py_script_parts.append(f"#%%\n{source_content.rstrip()}")
        elif cell_type == "markdown":
            # Markdown cells are represented as commented-out Python code
            commented_source = "\n".join(
                [f"# {line}" for line in source_content.splitlines()]
            )
            py_script_parts.append(f"#%% [markdown]\n{commented_source}")

    # Use two newlines to separate cells clearly, mimicking jupytext.
    return "\n\n".join(py_script_parts) + "\n"


def py_to_ipynb(py_content: str, original_notebook_content: str) -> str:
    """
    Converts a '#%%' Python script back to a Jupyter Notebook JSON string,
    preserving metadata from the original notebook.
    """
    original_valid = True
    try:
        original_data = json.loads(original_notebook_content)
        # Ensure base structure is valid
        if "cells" not in original_data or "nbformat" not in original_data:
            raise ValueError("Original notebook content is not a valid notebook.")
    except (json.JSONDecodeError, ValueError):
        # If original is invalid, create a skeleton notebook structure.
        original_valid = False
        original_data = {
            "cells": [],
            "metadata": {},
            "nbformat": 4,
            "nbformat_minor": 5,
        }

    def _split_lines_with_optional_trim(text: str, trim_last_newline: bool):
        lines = text.splitlines(keepends=True)
        if trim_last_newline and lines and lines[-1].endswith("\n"):
            lines[-1] = lines[-1][:-1]
        return lines

    new_cells = []
    # Split by the separator at the beginning of a line.
    script_cells = re.split(r"\n\n(?=#%%)", py_content)

    for script_cell in script_cells:
        if not script_cell.strip():
            continue

        parts = script_cell.split("\n", 1)
        header = parts[0]
        source_str = parts[1] if len(parts) > 1 else ""

        if header.strip() == "#%%":
            new_cells.append(
                {
                    "cell_type": "code",
                    "execution_count": None,
                    "metadata": {},
                    "outputs": [],
                    # When original is valid, normalize to no trailing newline on the last line,
                    # matching ipynb_to_py's rstrip-induced representation.
                    "source": _split_lines_with_optional_trim(source_str, trim_last_newline=original_valid),
                }
            )
        elif header.strip() == "#%% [markdown]":
            # Uncomment the markdown content
            uncommented_lines = []
            for line in source_str.splitlines():
                if line.startswith("# "):
                    uncommented_lines.append(line[2:])
                elif line.startswith("#"):
                    uncommented_lines.append(line[1:])
                else:
                    uncommented_lines.append(line)
            uncommented_source = "\n".join(uncommented_lines)

            new_cells.append(
                {
                    "cell_type": "markdown",
                    "metadata": {},
                    "source": _split_lines_with_optional_trim(uncommented_source, trim_last_newline=original_valid),
                }
            )

    # Replace the cells in the original data structure
    original_data["cells"] = new_cells
    # Return pretty-printed JSON, which is standard for .ipynb files
    return json.dumps(original_data, indent=2) + "\n"
