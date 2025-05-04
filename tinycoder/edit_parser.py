import re
from typing import List, Tuple
import logging

class EditParser:
    """Parses LLM responses to extract structured edit blocks in the new XML format."""

    def __init__(self):
        """Initializes the EditParser."""
        self.logger = logging.getLogger(__name__)

        # Regex patterns for the new XML structure
        # Using non-greedy matching (.*?) and DOTALL (s) flag
        # Captures the path attribute and the content inside <file>
        self.file_block_pattern = re.compile(
            r"<file path=\"(.*?)\">([\s\S]*?)</file>", re.DOTALL
        )
        # Captures the content inside <edit_block>
        self.edit_block_pattern = re.compile(
            r"<edit_block>([\s\S]*?)</edit_block>", re.DOTALL
        )
        # Captures the content inside <old_code>
        self.old_code_pattern = re.compile(
            r"<old_code>([\s\S]*?)</old_code>", re.DOTALL
        )
        # Captures the content inside <new_code>
        self.new_code_pattern = re.compile(
            r"<new_code>([\s\S]*?)</new_code>", re.DOTALL
        )

    def parse(self, response: str) -> List[Tuple[str, str, str]]:
        """Parses XML-structured edit blocks from the LLM response."""
        edits = []

        # Find all <file> blocks in the response
        for file_match in self.file_block_pattern.finditer(response):
            # group(1) is the path, group(2) is the content inside <file>
            fname = file_match.group(1).strip()
            file_content = file_match.group(2)

            if not fname:
                self.logger.warning(
                    "Skipping <file> block with empty or missing path attribute."
                )
                continue  # Skip this file block if path is empty

            # Find all <edit_block> blocks within the current <file> content
            for edit_match in self.edit_block_pattern.finditer(file_content):
                edit_content = edit_match.group(1)  # Content inside <edit_block>

                # Extract content from <old_code> and <new_code> within the edit block
                # Default to empty string if tags are not found (though they should be)
                old_code = ""  # Initialize
                old_code_match = self.old_code_pattern.search(edit_content)
                if old_code_match:
                    # Strip leading/trailing whitespace AFTER extraction
                    old_code = old_code_match.group(1).strip()

                new_code = ""  # Initialize
                new_code_match = self.new_code_pattern.search(edit_content)
                if new_code_match:
                    # Strip leading/trailing whitespace AFTER extraction
                    new_code = new_code_match.group(1).strip()
                    
                # Normalize line endings
                old_code = old_code.replace("\r\n", "\n")
                new_code = new_code.replace("\r\n", "\n")

                # Append the extracted edit to the list
                # Check if both are effectively empty after stripping, treat old_code as truly empty
                if old_code == "" and new_code == "":
                    self.logger.warning(
                        f"Found edit block with empty <old_code> and <new_code> for file {fname}. Skipping edit."
                    )
                    continue  # Skip edits that would do nothing

                edits.append((fname, old_code, new_code))

        return edits
