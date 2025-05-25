import re
from typing import List, Tuple, Dict, Any # Added Dict, Any
import logging

class EditParser:
    """
    Parses LLM responses to extract structured edit blocks in the XML format
    and <request_files> blocks.
    """

    def __init__(self):
        """Initializes the EditParser."""
        self.logger = logging.getLogger(__name__)

        # Regex patterns for the XML structures
        # Using non-greedy matching (.*?) and DOTALL (s) flag
        
        # Captures the path attribute and the content inside <edit>
        self.edit_tag_pattern = re.compile(
            r"<edit path=\"(.*?)\">([\s\S]*?)</edit>", re.DOTALL
        )
        # Captures the content inside <old_code>
        self.old_code_pattern = re.compile(
            r"<old_code>([\s\S]*?)</old_code>", re.DOTALL
        )
        # Captures the content inside <new_code>
        self.new_code_pattern = re.compile(
            r"<new_code>([\s\S]*?)</new_code>", re.DOTALL
        )
        # Captures content inside <request_files>
        self.request_files_pattern = re.compile(
            r"<request_files>([\s\S]*?)</request_files>", re.DOTALL
        )


    def parse(self, response: str) -> Dict[str, Any]:
        """
        Parses LLM responses to extract structured edit blocks in the XML format
        and <request_files> blocks.

        Returns:
            A dictionary with two keys:
            - "edits": A list of tuples, where each tuple is (path, old_code, new_code).
            - "requested_files": A list of file path strings.
        """
        edits: List[Tuple[str, str, str]] = []
        requested_files: List[str] = []

        # Find all <edit path="..."> blocks in the response
        for edit_tag_match in self.edit_tag_pattern.finditer(response):
            # group(1) is the path, group(2) is the content inside <edit>
            path_attr = edit_tag_match.group(1).strip()
            edit_tag_content = edit_tag_match.group(2)

            if not path_attr:
                self.logger.warning(
                    "Skipping <edit> block with empty or missing path attribute."
                )
                continue  # Skip this edit block if path is empty

            # Extract content from <old_code> and <new_code> within the <edit> tag's content
            old_code = ""  # Initialize
            old_code_match = self.old_code_pattern.search(edit_tag_content)
            if old_code_match:
                # Strip leading/trailing whitespace AFTER extraction
                old_code_content = old_code_match.group(1)
                # Preserve leading/trailing newlines if they are the *only* content
                if old_code_content.strip() == "":
                    old_code = old_code_content # Keep as is (e.g. "\n\n")
                else: # Strip if there's other non-whitespace content
                    old_code = old_code_content.strip()


            new_code = ""  # Initialize
            new_code_match = self.new_code_pattern.search(edit_tag_content)
            if new_code_match:
                # Strip leading/trailing whitespace AFTER extraction
                new_code_content = new_code_match.group(1)
                if new_code_content.strip() == "":
                    new_code = new_code_content
                else:
                    new_code = new_code_content.strip()
            
            # Normalize line endings
            old_code = old_code.replace("\r\n", "\n")
            new_code = new_code.replace("\r\n", "\n")

            # Append the extracted edit to the list
            # Skip edits that are effectively empty (both old and new code are empty *after stripping*)
            if old_code == "" and new_code == "":
                self.logger.warning(
                    f"Skipping edit for file '{path_attr}' because both <old_code> and <new_code> are effectively empty."
                )
                continue

            edits.append((path_attr, old_code, new_code))

        # Find <request_files> block
        request_match = self.request_files_pattern.search(response)
        if request_match:
            files_text = request_match.group(1).strip()
            if files_text:
                # Split by newline and filter out empty strings after stripping each line
                requested_files.extend([f.strip() for f in files_text.splitlines() if f.strip()])
        
        if requested_files and edits:
            self.logger.warning("LLM response contains both <request_files> and <edit> tags. "
                                "Prioritizing file request as per standard instructions.")
            # Note: The app.py logic will handle whether to process edits if files are requested.
            # For strictness, one might clear `edits` here:
            # edits = []


        return {"edits": edits, "requested_files": requested_files}

if __name__ == '__main__':
    # Example usage (requires logging setup to see warnings)
    logging.basicConfig(level=logging.INFO)
    parser = EditParser()

    # Test case 1: Basic valid input
    response1 = """
Some introductory text.
<edit path="./path/to/file1.py">
<old_code>
print("hello old world")</old_code>
<new_code>
print("hello new world")</new_code>
</edit>
Some text in between.
<edit path="another/file.txt">
<old_code>old line1
old line2</old_code>
<new_code>new line1
new line2
new line3</new_code>
</edit>
    """
    edits1 = parser.parse(response1)
    print("Edits from response 1:")
    for edit in edits1:
        print(f"  Path: {edit[0]}\n  Old Code: <<<{edit[1]}>>>\n  New Code: <<<{edit[2]}>>>\n")
    # Expected: 2 edits

    # Test case 2: Empty path attribute
    response2 = """
<edit path="">
<old_code>foo</old_code>
<new_code>bar</new_code>
</edit>
    """
    edits2 = parser.parse(response2)
    print("Edits from response 2 (empty path):")
    print(f"  Found {len(edits2)} edits.\n") # Expected: 0 edits, warning logged

    # Test case 3: Missing old_code or new_code tags
    response3 = """
<edit path="file3.py">
<old_code>only old</old_code>
</edit>
<edit path="file4.py">
<new_code>only new</new_code>
</edit>
    """
    edits3 = parser.parse(response3)
    print("Edits from response 3 (missing tags):")
    for edit in edits3:
        print(f"  Path: {edit[0]}\n  Old Code: <<<{edit[1]}>>>\n  New Code: <<<{edit[2]}>>>\n")
    # Expected: 2 edits, one with empty new_code, one with empty old_code

    # Test case 4: Both old_code and new_code are empty (or contain only whitespace)
    response4 = """
<edit path="file5.py">
<old_code>
</old_code>
<new_code>   </new_code>
</edit>
    """
    edits4 = parser.parse(response4)
    print("Edits from response 4 (empty codes):")
    print(f"  Found {len(edits4)} edits.\n") # Expected: 0 edits, warning logged

    # Test case 5: Malformed XML (extra > in new_code closing tag, as per example)
    response5 = """
<edit path="./path/to/file.py">
<old_code>
A contiguous chunk of lines...
</old_code>
<new_code>
The lines to replace...
</new_code>> 
</edit>
    """ # Note the `</new_code>>` - the regex should handle this gracefully.
    edits5 = parser.parse(response5)
    print("Edits from response 5 (malformed new_code tag):")
    for edit in edits5:
        print(f"  Path: {edit[0]}\n  Old Code: <<<{edit[1]}>>>\n  New Code: <<<{edit[2]}>>>\n")
    # Expected: 1 edit, content of new_code should be "The lines to replace..."

    # Test case 6: No edit blocks
    response6 = "This is just a regular response with no edit blocks."
    edits6 = parser.parse(response6)
    print("Edits from response 6 (no edits):")
    print(f"  Found {len(edits6)} edits.\n") # Expected: 0 edits

    # Test case 7: Edit block with content but old/new tags are empty
    response7 = """
<edit path="file7.py">
<old_code></old_code>
<new_code></new_code>
</edit>
    """
    edits7 = parser.parse(response7)
    print("Edits from response 7 (empty tags):")
    print(f"  Found {len(edits7)} edits.\n") # Expected: 0 edits, warning logged

    # Test case 8: Path with spaces (should be preserved by strip on attribute value, not content)
    response8 = """
<edit path=" path with spaces/file.py ">
<old_code>old</old_code>
<new_code>new</new_code>
</edit>
    """
    edits8 = parser.parse(response8)
    print("Edits from response 8 (path with spaces):")
    for edit in edits8: # Expected: path is "path with spaces/file.py"
        print(f"  Path: '{edit[0]}'\n  Old Code: <<<{edit[1]}>>>\n  New Code: <<<{edit[2]}>>>\n")