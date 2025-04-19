import re
from typing import List, Tuple, Callable, Optional, Set

class EditParser:
    """Parses LLM responses to extract structured edit blocks."""

    def __init__(self, print_warning: Callable[[str], None], fnames_provider: Callable[[], Set[str]]):
        """
        Initializes the EditParser.

        Args:
            print_warning: A function to call for printing warning messages.
            fnames_provider: A function that returns the current set of file names in the chat context.
        """
        self.print_warning = print_warning
        self.fnames_provider = fnames_provider # To get context for fallback filename

        # Regex for the inner SEARCH/REPLACE structure
        self.edit_block_pattern = re.compile(
            r"<<<<<<< SEARCH\s*\n([\s\S]*?)\n=======\s*\n([\s\S]*?)\n>>>>>>> REPLACE",
            re.DOTALL
        )
        # Regex for code blocks (```lang\n...\n```)
        self.code_block_pattern = re.compile(
            r"```(?:python|diff|[\w\.]+)?\s*\n([\s\S]*?)\n```", # Allow optional language or filename
            re.DOTALL
        )

    def parse(self, response: str) -> List[Tuple[str, str, str]]:
        """Parses diff/diff-fenced edit blocks from the LLM response."""
        edits = []
        # Find all potential code blocks first
        potential_code_blocks = self.code_block_pattern.finditer(response)

        # Keep track of the end position of the last processed match to avoid overlap/double matching filename
        last_pos = 0

        for code_match in potential_code_blocks:
            code_content_full = code_match.group(1) # Content inside ```...```
            code_block_start, code_block_end = code_match.span()

            # Check if this block contains the SEARCH/REPLACE markers
            inner_matches_found = list(self.edit_block_pattern.finditer(code_content_full))
            if not inner_matches_found:
                continue # This code block doesn't contain edits, skip

            # --- Determine the filename ---
            fname = None
            code_content_for_edits = code_content_full # Default content for parsing edits

            # Case 1: Filename is the first line *inside* the code block
            lines = code_content_full.split('\n', 1)
            first_line_inside = lines[0].strip()
            # Basic check: does it look like a path? (contains / or \ or ends with common extension)
            # Avoid matching keywords like 'python' or the SEARCH marker itself
            # Also check it's not empty
            if first_line_inside and \
               not first_line_inside.startswith("<<<<<<< SEARCH") and \
               first_line_inside not in {"python", "diff"} and \
               ('/' in first_line_inside or '\\' in first_line_inside or '.' in first_line_inside):
                 # Check if the *rest* of the content contains the edit block start marker
                 # This ensures the first line IS the filename and not part of the search block
                 if len(lines) > 1 and self.edit_block_pattern.search(lines[1]):
                     fname = first_line_inside
                     # Adjust content to exclude the filename line for inner parsing
                     code_content_for_edits = lines[1]
                     # Re-run inner matches on the adjusted content
                     inner_matches_found = list(self.edit_block_pattern.finditer(code_content_for_edits))


            # Case 2: Filename is on the line *before* the code block
            if fname is None:
                # Search backwards from the start of the code block in the original response
                # Ensure we don't re-read text processed by previous block matches
                search_start = response.rfind('\n', 0, code_block_start) + 1 # Start of the line before the block
                if search_start < last_pos: # Avoid overlap with previous matches/filenames
                     search_start = last_pos

                preceding_text = response[search_start:code_block_start]
                lines_before = preceding_text.strip().split('\n')
                if lines_before:
                    last_line_before = lines_before[-1].strip()
                    # Basic check: does it look like a path?
                    if last_line_before and \
                       last_line_before not in {"python", "diff"} and \
                       ('/' in last_line_before or '\\' in last_line_before or '.' in last_line_before):
                        fname = last_line_before
                        # Use the original full content for inner parsing
                        code_content_for_edits = code_content_full
                        # Reset inner matches based on full content (already done above)
                        inner_matches_found = list(self.edit_block_pattern.finditer(code_content_for_edits))


            # --- If filename is still undetermined ---
            if fname is None:
                 # Fallback or Warning
                 self.print_warning(f"Could not determine filename for edit block:\n```\n{code_content_full[:100]}...\n```")
                 # Option: Default to first file in chat?
                 current_fnames = self.fnames_provider()
                 if current_fnames:
                     fname = list(sorted(current_fnames))[0] # Use sorted list for determinism
                     self.print_warning(f"Assuming edit applies to the first file in chat: {fname}")
                     code_content_for_edits = code_content_full # Use original content
                     # Reset inner matches based on full content
                     inner_matches_found = list(self.edit_block_pattern.finditer(code_content_for_edits))
                 else:
                     # Cannot print error here as it's a different callback type
                     self.print_warning("Cannot apply edit block - no filename found and no files in chat.")
                     continue # Skip this block

            # --- Extract edits using the determined content ---
            if fname: # Ensure filename was found or defaulted
                for match in inner_matches_found: # Use the potentially updated inner_matches
                    search_block, replace_block = match.groups()
                    edits.append((fname, search_block, replace_block))

            # Update last position to prevent the next iteration from re-parsing this block's preceding line
            last_pos = code_block_end


        # Post-process all found edits (same as before)
        processed_edits = []
        for fname, search_block, replace_block in edits:
             # Normalize line endings to LF for comparison and application
             search_block = search_block.replace('\r\n', '\n')
             replace_block = replace_block.replace('\r\n', '\n')

             # Handle case where replace_block is meant to be empty (deletion)
             if replace_block.strip() == "":
                  replace_block = "" # Explicitly empty

             processed_edits.append((fname.strip(), search_block, replace_block))

        return processed_edits
