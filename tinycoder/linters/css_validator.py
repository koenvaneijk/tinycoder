import sys
import re
from typing import Tuple, List, Optional
from pathlib import Path


class CssValidator:
    """
    Validates CSS content based on simple structural checks.

    Checks for:
    1. Balanced curly braces {}.
    2. Basic structure within rule sets (selector { property: value; }).
    """

    def __init__(self):
        """Initializes the validator."""
        # State is now managed per-lint call
        pass

    def _remove_comments(self, content: str) -> str:
        """Removes CSS comments (/* ... */) from the content."""
        return re.sub(r"/\*.*?\*/", "", content, flags=re.DOTALL)

    def _check_brace_balance(
        self, content_no_comments: str, errors: List[str]
    ) -> bool:
        """
        Checks for balanced curly braces {}.

        Populates self._errors if issues are found.

        Checks for balanced curly braces {}. Populates the provided `errors` list.

        Returns:
            bool: True if braces are balanced so far, False if an unrecoverable
                  imbalance (like '}') is found early.
        """
        brace_balance = 0
        for i, char in enumerate(content_no_comments):
            if char == "{":
                brace_balance += 1
            elif char == "}":
                brace_balance -= 1

            if brace_balance < 0:
                # Find the line number for the error
                error_line = content_no_comments[: i + 1].count("\n") + 1
                errors.append(
                    f"Syntax Error: Unexpected '}}' on or near line {error_line}."
                )
                # Stop further checks if braces are fundamentally unbalanced
                return False  # Indicates fatal imbalance

        if brace_balance > 0:
            errors.append(
                "Syntax Error: Unmatched '{' found. End of file reached before closing '}'."
            )

        return True  # Braces might be balanced, or only missing closing ones at the end

    def _check_rule_structure(
        self, content_no_comments: str, errors: List[str]
    ) -> None:
        """
        Performs basic structure checks within rule sets ({ ... }).

        Checks for `property: value;` structure. Populates the provided `errors` list.
        Assumes comments have been removed and basic brace balance might be okay.
        """
        rule_blocks = re.findall(r"\{(.*?)\}", content_no_comments, flags=re.DOTALL)
        # Get start indices to calculate line numbers more accurately
        block_start_indices = [
            m.start() for m in re.finditer(r"\{", content_no_comments)
        ]

        # Ensure we don't have index errors if counts mismatch (e.g., due to earlier brace errors)
        num_blocks_to_check = min(len(rule_blocks), len(block_start_indices))

        for i in range(num_blocks_to_check):
            block = rule_blocks[i]
            current_block_start_index = block_start_indices[i]
            # Calculate the starting line number of the block in the no-comment content
            block_start_line = content_no_comments[:current_block_start_index].count("\n") + 1

            # Split declarations by semicolon
            declarations = block.strip().split(";")

            for decl_index, declaration in enumerate(declarations):
                declaration = declaration.strip()
                if not declaration:  # Ignore empty parts resulting from split or whitespace
                    continue

                # Calculate the approximate line number *within the block* for this declaration
                # This is tricky because split removes context, we estimate based on previous declarations
                line_offset_in_block = (
                    block[: block.find(declaration)].count("\n")
                    if declaration in block
                    else 0
                )
                error_line = block_start_line + line_offset_in_block

                # Check if the declaration looks like a property: value pair
                if ":" not in declaration:
                    errors.append(
                        f"Syntax Error: Missing ':' in declaration near line {error_line}. Found: '{declaration}'"
                    )
                elif declaration.endswith(":"):
                    errors.append(
                        f"Syntax Error: Missing value after ':' near line {error_line}. Found: '{declaration}'"
                    )
                # Note: This doesn't validate property names or value formats, just basic structure.

    def lint(self, abs_path: Path, content: str) -> Optional[str]:
        """
        Runs all validation checks on the provided CSS content.

        Args:
            abs_path: The absolute path to the file (used for context in errors, potentially).
                      Currently unused in the checks themselves.
            content: The CSS content string to validate.

        Returns:
            A formatted string containing all error messages (one per line),
            or None if the CSS appears valid based on basic checks.
        """
        errors: List[str] = []  # Errors specific to this lint call

        # Perform checks sequentially
        content_no_comments = self._remove_comments(content)

        if not self._check_brace_balance(content_no_comments, errors):
            # If braces are fundamentally broken (e.g., early '}'), return early.
            return "\n".join(errors) if errors else None # Should always have at least one error here

        # Check rule structure even if closing braces might be missing at the end
        self._check_rule_structure(content_no_comments, errors)

        return "\n".join(errors) if errors else None


def main():
    """Main function to run the validator from the command line."""
    if len(sys.argv) != 2:
        print("Usage: python css_validator.py <path_to_css_file>")
        sys.exit(1)

    file_path_str = sys.argv[1]
    file_path = Path(file_path_str)

    try:
        if not file_path.is_file():
            raise FileNotFoundError(f"Error: File not found at '{file_path_str}'")

        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        validator = CssValidator()
        error_string = validator.lint(file_path, content)

        if error_string is None:
            print(f"'{file_path_str}' appears to be valid CSS (based on basic checks).")
        else:
            print(f"'{file_path_str}' has validation errors:")
            # Errors are already newline-separated
            print(error_string)
            sys.exit(1)  # Exit with error code if invalid

    except (FileNotFoundError, IOError, ValueError) as e:
        print(f"Error: {e}")
        sys.exit(1)  # Exit with error code on file/init errors


if __name__ == "__main__":
    main()
