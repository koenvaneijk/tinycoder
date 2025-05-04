import html.parser
from pathlib import Path
from typing import List, Tuple, Optional, Set, Dict, Any

# Set of known HTML void elements (tags that don't need closing tags)
# Source: https://developer.mozilla.org/en-US/docs/Glossary/Void_element
VOID_ELEMENTS: Set[str] = {
    "area",
    "base",
    "br",
    "col",
    "embed",
    "hr",
    "img",
    "input",
    "link",
    "meta",
    "param",
    "source",
    "track",
    "wbr",
}


class _HTMLValidationParser(html.parser.HTMLParser):
    """
    Internal parser subclass to track tag nesting and report errors.
    """

    def __init__(
        self, content_lines: List[str], *, convert_charrefs: bool = True
    ) -> None:
        super().__init__(convert_charrefs=convert_charrefs)
        self._tag_stack: List[Tuple[str, Tuple[int, int]]] = (
            []
        )  # Stores (tag_name, (line, col))
        self._errors: List[Dict[str, Any]] = []  # Stores error details dictionaries
        self._content_lines: List[str] = (
            content_lines  # Store content lines for context
        )

    def _add_error(self, error_details: Dict[str, Any]):
        """Adds error details along with context."""
        line_num = error_details.get(
            "line", 1
        )  # 1-based line number from getpos() or stored start_pos
        error_details["context"] = self._get_context(
            line_num - 1
        )  # Get context using 0-based index
        self._errors.append(error_details)

    def _get_context(self, line_index: int, num_lines: int = 5) -> List[str]:
        """Extracts surrounding lines for context."""
        if not self._content_lines:
            # This case should ideally not happen if initialized correctly
            return ["Context unavailable."]

        start = max(0, line_index - num_lines)
        end = min(len(self._content_lines), line_index + num_lines + 1)
        context = []
        for i in range(start, end):
            # Ensure line numbers displayed match original file (1-based) for clarity
            line_num_display = i + 1
            prefix = f"{line_num_display:>{len(str(end))}}: "  # Right-align line number
            prefix += ">> " if i == line_index else "   "  # Indicate the target line
            context.append(f"{prefix}{self._content_lines[i]}")
        return context

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        """Handles opening tags. Pushes non-void tags onto the stack."""
        tag_lower = tag.lower()
        # Don't push void elements onto the stack as they don't need closing tags
        if tag_lower not in VOID_ELEMENTS:
            self._tag_stack.append((tag_lower, self.getpos()))

    def handle_endtag(self, tag: str) -> None:
        """Handles closing tags. Checks against the stack."""
        tag_lower = tag.lower()
        line, col = self.getpos()  # 1-based line number

        # Ignore closing tags for void elements if encountered (technically invalid HTML5, but common)
        if tag_lower in VOID_ELEMENTS:
            # Optionally add a warning here if desired, but for rudimentary check, we can ignore
            # self._add_error({'type': 'warning_void_close', 'line': line, 'tag': tag})
            return

        if not self._tag_stack:
            self._add_error(
                {
                    "type": "unexpected_close",
                    "line": line,
                    "tag": tag_lower,
                    "message": f"Unexpected closing tag </{tag}> found. No tags are currently open.",
                }
            )
            return

        expected_tag, start_pos = self._tag_stack.pop()
        start_line, start_col = start_pos  # 1-based line number

        if tag_lower != expected_tag:
            # Simple Mismatch: Report the error found vs expected.
            # The incorrect closing tag effectively closes the expected tag in this model.
            self._add_error(
                {
                    "type": "mismatch",
                    "line": line,
                    "tag": tag_lower,
                    "expected_tag": expected_tag,
                    "expected_line": start_line,
                    "message": f"Mismatched closing tag. Found </{tag}> but expected </{expected_tag}> (opened on line {start_line}).",
                }
            )
            # No complex recovery heuristic implemented here.
            # We assume the mismatch implies the expected tag is now closed.

    def finalize_checks(self) -> None:
        """Checks for any remaining unclosed tags after parsing."""
        # Any tags left on the stack are unclosed
        while self._tag_stack:
            tag, pos = self._tag_stack.pop()
            line, col = pos  # 1-based line number where the tag opened
            self._add_error(
                {
                    "type": "unclosed",
                    "line": line,
                    "tag": tag,
                    "message": f"Unclosed tag <{tag}> (opened on line {line}) found at end of file.",
                }
            )

    def get_errors(self) -> List[Dict[str, Any]]:
        """Returns the list of structured errors found during parsing."""
        return self._errors


class HTMLLinter:
    """
    Provides rudimentary HTML linting functionality using html.parser.
    Focuses on tag matching and void elements.
    """

    def lint(self, abs_path: Path, content: str) -> Optional[str]:
        """
        Lints the provided HTML content for basic well-formedness.

        Args:
            abs_path: The absolute path to the file (used for error reporting).
            content: The HTML content string to lint.

        Returns:
            A formatted error string with context if issues are found, otherwise None.
        """
        lines = content.splitlines()
        # Handle case where content ends without a newline, splitlines might miss the last line if empty
        if content.endswith("\n"):
            # Add an empty string to represent the potential position after the last newline
            # This helps if the error is conceptually *after* the last character
            pass  # splitlines already handles this correctly by not including trailing empty string
        # else:
        # If no trailing newline, splitlines gives accurate number of lines
        # pass

        parser = _HTMLValidationParser(content_lines=lines)
        structured_errors: List[Dict[str, Any]] = []

        try:
            parser.feed(content)
            parser.close()  # Ensure finalization
        except html.parser.HTMLParseError as e:
            # Try to determine the line number from the error message
            line_num = 1
            if hasattr(e, "lineno"):
                line_num = e.lineno
            elif e.msg and "line " in e.msg:
                try:
                    line_part = e.msg.split("line ")[1].split(",")[0]
                    line_num = int(line_part)
                except (IndexError, ValueError):
                    pass  # Use default line 1 if parsing fails
            parser._add_error(
                {  # Use the parser's add_error to get context
                    "type": "parse_error",
                    "line": line_num,
                    "message": f"HTML Parsing Error: {e.msg}",
                }
            )
        except Exception as e:
            # Catch unexpected errors during parsing
            parser._add_error(
                {  # Use the parser's add_error to get context (line 1 default)
                    "type": "unexpected_exception",
                    "line": 1,  # Cannot determine line number reliably
                    "message": f"Unexpected error during HTML parsing: {e}",
                }
            )
            # Optionally log the full traceback here

        # Perform our custom final checks (like unclosed tags)
        parser.finalize_checks()
        structured_errors = parser.get_errors()

        if structured_errors:
            error_header = f"HTML lint errors found in {abs_path.name}:"
            formatted_error_blocks = []
            for error in structured_errors:
                # Ensure context is present, provide fallback
                context_str = "\n".join(
                    error.get("context", ["    Context unavailable."])
                )
                # Use the message stored in the error dict
                message = error.get("message", f"Unknown {error.get('type', 'error')}")
                formatted_error_blocks.append(
                    f"- {message}\nContext:\n```html\n{context_str}\n```"
                )

            return f"{error_header}\n\n" + "\n\n".join(formatted_error_blocks)
        else:
            return None


# Example Usage (for testing purposes, not part of the main application flow)
if __name__ == "__main__":
    linter = HTMLLinter()
    test_path = Path("example.html")

    # Test case 1: Valid HTML
    html_valid = """
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
    print(f"--- Testing Valid HTML ---")
    result = linter.lint(test_path, html_valid)
    print(result if result else "No errors found.")

    # Test case 2: Mismatched tags
    html_mismatched = """
    <html>
    <head><title>Mismatched</title></head>
    <body>
        <div><p>Uh oh</span></div> <!-- Mismatch: p vs span -->
    </body>
    </html>
    """
    print(f"\n--- Testing Mismatched Tags ---")
    result = linter.lint(test_path, html_mismatched)
    print(result if result else "No errors found.")

    # Test case 3: Unclosed tag
    html_unclosed = """
    <html>
    <head><title>Unclosed</title></head>
    <body>
        <div>
            <p>This paragraph is not closed.
    </body>
    </html>
    """
    print(f"\n--- Testing Unclosed Tags ---")
    result = linter.lint(test_path, html_unclosed)
    print(result if result else "No errors found.")

    # Test case 4: Unexpected closing tag
    html_unexpected_close = """
    <html>
    <head><title>Unexpected</title></head>
    <body>
        </div> <!-- Closed div before opening -->
        <p>Content</p>
    </body>
    </html>
    """
    print(f"\n--- Testing Unexpected Closing Tag ---")
    result = linter.lint(test_path, html_unexpected_close)
    print(result if result else "No errors found.")

    # Test case 5: Closing void element (warning/ignored)
    html_close_void = """
    <html><body><p>Line break closed?<br></br></p></body></html>
    """
    print(f"\n--- Testing Closing Void Element ---")
    result = linter.lint(test_path, html_close_void)
    print(result if result else "No errors found.")  # Should find no errors by default

    # Test case 6: More complex mismatch recovery
    html_complex_mismatch = """
    <html><body>
    <div><a><b>Text</b></div> <!-- trying to close div, but b/a are open -->
    </a>
    </body></html>
    """
    print(f"\n--- Testing Complex Mismatch ---")
    result = linter.lint(test_path, html_complex_mismatch)
    print(result if result else "No errors found.")
