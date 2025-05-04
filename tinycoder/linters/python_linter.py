import traceback
from pathlib import Path
from typing import Optional


class PythonLinter:
    """Provides Python syntax checking using compile()."""

    def lint(self, abs_path: Path, content: str) -> Optional[str]:
        """
        Checks python syntax using compile().

        Args:
            abs_path: Absolute path to the file (for error reporting).
            content: The Python code content as a string.

        Returns:
            A formatted error string if a syntax error is found, otherwise None.
        """
        try:
            compile(content, str(abs_path), "exec")
            return None
        except (SyntaxError, ValueError) as err:  # Catch ValueError for null bytes etc.
            # Format traceback similar to how it might appear in console
            tb_lines = traceback.format_exception(type(err), err, err.__traceback__)

            # Find the start of the traceback relevant to the compile error
            traceback_marker = "Traceback (most recent call last):"
            relevant_lines = []
            in_relevant_section = False
            for line in tb_lines:
                if traceback_marker in line:
                    in_relevant_section = True
                if in_relevant_section:
                    # Exclude the frame pointing to our internal compile() call
                    if 'compile(content, str(abs_path), "exec")' not in line:
                        relevant_lines.append(line)

            # If filtering didn't work as expected, use the full traceback
            if not relevant_lines or not any(
                str(abs_path) in line for line in relevant_lines
            ):
                formatted_error = "".join(tb_lines)
            else:
                formatted_error = "".join(relevant_lines)

            # Clean up the path representation in the error message
            try:
                # Show relative path if possible, based on the filename part
                rel_path_str = abs_path.name
            except Exception:
                rel_path_str = str(abs_path)  # Fallback to absolute path

            # Reconstruct a cleaner error message
            error_type = type(err).__name__
            error_details = str(err)  # The core error message (e.g., "invalid syntax")

            # Attempt to extract line number and offset if available
            line_info = ""
            if isinstance(err, SyntaxError):
                if err.lineno is not None:
                    line_info += f" (line {err.lineno})"
                # Offset often points to the end of the error, maybe less useful directly
                # if err.offset is not None:
                #     line_info += f", offset {err.offset}"

            # Use the filtered traceback lines
            traceback_str = "".join(relevant_lines).strip()

            return f"{error_type} in {rel_path_str}{line_info}: {error_details}\n```\n{traceback_str}\n```"
