import re
from typing import List, Tuple
import logging

class EditParser:
    """
    Parses LLM responses to extract structured edit operations described
    in the simplified <edit path="..."> XML format.
    Uses a more nuanced approach to stripping newlines from code blocks.
    """

    def __init__(self):
        """Initializes the EditParser."""
        self.logger = logging.getLogger(__name__)
        self.edit_pattern = re.compile(
            r"<edit path=\"(.*?)\">([\s\S]*?)</edit>", re.DOTALL
        )
        self.old_code_pattern = re.compile(
            r"<old_code>([\s\S]*?)</old_code>", re.DOTALL
        )
        self.new_code_pattern = re.compile(
            r"<new_code>([\s\S]*?)</new_code>", re.DOTALL
        )

    def _strip_formatting_newlines(self, text: str) -> str:
        """
        Removes a single leading newline and/or a single trailing newline if they exist.
        This is to counteract typical XML pretty-printing by LLMs,
        without stripping significant newlines that are part of the code block itself.
        """
        if not text: # Handle empty string case
            return ""
        
        s = text
        
        if s.startswith('\n'):
            s = s[1:]
        
        if not s: # If original was just "\n"
            return ""
            
        if s.endswith('\n'):
            s = s[:-1]
            
        return s

    def parse(self, response: str) -> List[Tuple[str, str, str]]:
        """
        Parses XML-structured edit operations from the LLM response.
        Each operation is expected to be in an <edit path="...">...</edit> block.

        Args:
            response: The string response from the LLM.

        Returns:
            A list of tuples, where each tuple contains:
            (file_path: str, old_code_content: str, new_code_content: str)
        """
        edits = []

        for edit_match in self.edit_pattern.finditer(response):
            raw_path = edit_match.group(1)
            edit_content = edit_match.group(2)
            
            fname = raw_path.strip() # Path attribute value can still be stripped normally

            if not fname:
                self.logger.warning(
                    "Skipping <edit> block with empty or missing path attribute value."
                )
                continue

            old_code_raw = "" 
            old_code_match = self.old_code_pattern.search(edit_content)
            if old_code_match:
                old_code_raw = old_code_match.group(1)
            else:
                self.logger.warning(
                    f"Missing <old_code> tag within <edit path=\"{fname}\">. Assuming empty old_code."
                )
            
            # Apply nuanced stripping for code content
            old_code = self._strip_formatting_newlines(old_code_raw)

            new_code_raw = ""
            new_code_match = self.new_code_pattern.search(edit_content)
            if new_code_match:
                new_code_raw = new_code_match.group(1)
            else:
                self.logger.warning(
                    f"Missing <new_code> tag within <edit path=\"{fname}\">. Assuming empty new_code."
                )

            # Apply nuanced stripping for code content
            new_code = self._strip_formatting_newlines(new_code_raw)
                
            # Normalize line endings AFTER stripping formatting newlines
            old_code = old_code.replace("\r\n", "\n")
            new_code = new_code.replace("\r\n", "\n")

            if old_code == "" and new_code == "":
                self.logger.warning(
                    f"Found edit operation with effectively empty <old_code> and <new_code> "
                    f"for file '{fname}' after processing. Skipping this operation."
                )
                continue 

            edits.append((fname, old_code, new_code))

        if not edits and response.strip():
            if any(tag in response for tag in ["<edit", "<old_code>", "<new_code>"]):
                 self.logger.warning(
                    "LLM response contained edit-related tags but no valid <edit path=...>...</edit> "
                    "structures were successfully parsed. The XML might be malformed."
                 )
            else:
                self.logger.info(
                    "No <edit path=...> blocks found in the LLM response."
                )
        elif not response.strip():
             self.logger.info("Received an empty response from LLM.")

        return edits