import sys
import re
from typing import Tuple, List, Optional


class CssValidator:
    """
    Validates a CSS file or string based on simple structural checks.

    Checks for:
    1. Balanced curly braces {}.
    2. Basic structure within rule sets (selector { property: value; }).
    """

    def __init__(
        self, css_content: Optional[str] = None, file_path: Optional[str] = None
    ):
        """
        Initializes the validator.

        Args:
            css_content: A string containing the CSS content.
            file_path: The path to the .css file.

        Raises:
            ValueError: If neither css_content nor file_path is provided,
                        or if both are provided.
            FileNotFoundError: If file_path is provided but the file does not exist.
            IOError: If there's an error reading the file.
        """
        if (css_content is None and file_path is None) or (
            css_content is not None and file_path is not None
        ):
            raise ValueError(
                "Provide either css_content or file_path, not both or neither."
            )

        self._errors: List[str] = []
        self._css_content: str = ""
        self._content_no_comments: str = ""

        if file_path:
            self._file_path = file_path
            self._read_file()
        elif css_content is not None:
            self._file_path = None  # Indicate content was provided directly
            self._css_content = css_content

    def _read_file(self) -> None:
        """Reads the CSS content from the specified file_path."""
        if self._file_path is None:
            # Should not happen if constructor logic is correct, but defensive check
            raise ValueError("File path is not set.")
        try:
            with open(self._file_path, "r", encoding="utf-8") as f:
                self._css_content = f.read()
        except FileNotFoundError:
            # Raise specific error for constructor to handle or re-raise
            raise FileNotFoundError(f"Error: File not found at '{self._file_path}'")
        except Exception as e:
            # Raise a more generic IO error
            raise IOError(f"Error reading file '{self._file_path}': {e}")

    def _remove_comments(self) -> None:
        """Removes CSS comments (/* ... */) from the content."""
        self._content_no_comments = re.sub(
            r"/\*.*?\*/", "", self._css_content, flags=re.DOTALL
        )

    def _check_brace_balance(self) -> bool:
        """
        Checks for balanced curly braces {}.

        Populates self._errors if issues are found.

        Returns:
            bool: True if braces are balanced so far, False if an unrecoverable
                  imbalance (like '}') is found early.
        """
        brace_balance = 0
        for i, char in enumerate(self._content_no_comments):
            if char == "{":
                brace_balance += 1
            elif char == "}":
                brace_balance -= 1

            if brace_balance < 0:
                # Find the line number for the error
                error_line = self._content_no_comments[: i + 1].count("\n") + 1
                self._errors.append(
                    f"Syntax Error: Unexpected '}}' on or near line {error_line}."
                )
                # Stop further checks if braces are fundamentally unbalanced
                return False  # Indicates fatal imbalance

        if brace_balance > 0:
            self._errors.append(
                "Syntax Error: Unmatched '{' found. End of file reached before closing '}'."
            )

        return True  # Braces might be balanced, or only missing closing ones at the end

    def _check_rule_structure(self) -> None:
        """
        Performs basic structure checks within rule sets ({ ... }).

        Checks for `property: value;` structure. Populates self._errors if issues are found.
        Assumes comments have been removed and basic brace balance might be okay.
        """
        rule_blocks = re.findall(
            r"\{(.*?)\}", self._content_no_comments, flags=re.DOTALL
        )
        # Get start indices to calculate line numbers more accurately
        block_start_indices = [
            m.start() for m in re.finditer(r"\{", self._content_no_comments)
        ]

        # Ensure we don't have index errors if counts mismatch (e.g., due to earlier brace errors)
        num_blocks_to_check = min(len(rule_blocks), len(block_start_indices))

        for i in range(num_blocks_to_check):
            block = rule_blocks[i]
            current_block_start_index = block_start_indices[i]
            # Calculate the starting line number of the block in the no-comment content
            block_start_line = (
                self._content_no_comments[:current_block_start_index].count("\n") + 1
            )

            # Split declarations by semicolon
            declarations = block.strip().split(";")

            for decl_index, declaration in enumerate(declarations):
                declaration = declaration.strip()
                if (
                    not declaration
                ):  # Ignore empty parts resulting from split or whitespace
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
                    self._errors.append(
                        f"Syntax Error: Missing ':' in declaration near line {error_line}. Found: '{declaration}'"
                    )
                elif declaration.endswith(":"):
                    self._errors.append(
                        f"Syntax Error: Missing value after ':' near line {error_line}. Found: '{declaration}'"
                    )
                # Note: This doesn't validate property names or value formats, just basic structure.

    def validate(self) -> Tuple[bool, List[str]]:
        """
        Runs all validation checks on the loaded CSS content.

        Returns:
            A tuple containing:
            - bool: True if the CSS appears valid based on basic checks, False otherwise.
            - List[str]: A list of error messages if validation fails.
        """
        self._errors = []  # Reset errors for this run

        # Perform checks sequentially
        self._remove_comments()

        if not self._check_brace_balance():
            # If braces are fundamentally broken (e.g., early '}'), stop.
            return False, self._errors

        # Check rule structure even if closing braces might be missing at the end
        self._check_rule_structure()

        is_valid = not self._errors
        return is_valid, self._errors


def main():
    """Main function to run the validator from the command line."""
    if len(sys.argv) != 2:
        print("Usage: python css_validator.py <path_to_css_file>")
        sys.exit(1)

    file_path = sys.argv[1]

    try:
        validator = CssValidator(file_path=file_path)
        is_valid, messages = validator.validate()

        if is_valid:
            print(f"'{file_path}' appears to be valid CSS (based on basic checks).")
        else:
            print(f"'{file_path}' has validation errors:")
            for msg in messages:
                print(f"- {msg}")
            sys.exit(1)  # Exit with error code if invalid

    except (FileNotFoundError, IOError, ValueError) as e:
        print(f"Error: {e}")
        sys.exit(1)  # Exit with error code on file/init errors


if __name__ == "__main__":
    main()
