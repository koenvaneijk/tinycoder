import re
from typing import List, Tuple


class MarkdownFormatter:
    """Handles markdown text formatting for terminal display."""
    
    @staticmethod
    def parse_inline_markdown(text: str) -> List[Tuple[str, str]]:
        """Parses a single line of text for inline markdown styles like bold, italic, and code."""
        # Combined pattern to find all markdown elements at once.
        # Order of OR matters for greedy matching: *** before **, *
        # We look for non-greedy content `.+?` between delimiters.
        pattern = re.compile(
            r'(\*\*\*.+?\*\*\*|___.+?___)'  # Bold+Italic
            r'|(\*\*.+?\*\*|__.+?__)'  # Bold
            r'|(\*.+?\*|_.+?_)'  # Italic
            r'|(`.+?`)'  # Inline Code
        )

        parts = []
        last_end = 0
        for match in pattern.finditer(text):
            start, end = match.span()
            
            # Add the plain text before the match
            if start > last_end:
                parts.append(('', text[last_end:start]))

            # Determine the style and content of the match
            matched_text = match.group(0)
            if matched_text.startswith('***') or matched_text.startswith('___'):
                style = 'class:markdown.bold-italic'
                content = matched_text[3:-3]
            elif matched_text.startswith('**') or matched_text.startswith('__'):
                style = 'class:markdown.bold'
                content = matched_text[2:-2]
            elif matched_text.startswith('*') or matched_text.startswith('_'):
                style = 'class:markdown.italic'
                content = matched_text[1:-1]
            elif matched_text.startswith('`'):
                style = 'class:markdown.inline-code'
                content = matched_text[1:-1]
            else: # Should not happen
                style = ''
                content = matched_text
            
            parts.append((style, content))
            last_end = end

        # Add any remaining plain text after the last match
        if last_end < len(text):
            parts.append(('', text[last_end:]))

        return parts

    @staticmethod
    def format_for_terminal(markdown_text: str) -> List[Tuple[str, str]]:
        """Converts markdown text to a list of (style_class, text) tuples for prompt_toolkit."""
        formatted_text = []
        in_code_block = False

        # Regex for lists
        ulist_pattern = re.compile(r'^(\s*)([*+-])(\s+)(.*)')
        olist_pattern = re.compile(r'^(\s*)(\d+\.)(\s+)(.*)')

        lines = markdown_text.split('\n')
        for i, line in enumerate(lines):
            # --- Handle full-line block elements first ---
            stripped_line = line.lstrip()

            if stripped_line.startswith("```"):
                in_code_block = not in_code_block
                formatted_text.append(('class:markdown.code-block', line))
                if i < len(lines) - 1:
                    formatted_text.append(('', '\n'))
                continue

            if in_code_block:
                formatted_text.append(('class:markdown.code-block', line))
                if i < len(lines) - 1:
                    formatted_text.append(('', '\n'))
                continue

            # --- Handle elements with inline content ---
            prefix_tuples = []
            content_to_parse = line

            # Check for headers
            if stripped_line.startswith("#"):
                level = len(stripped_line) - len(stripped_line.lstrip('#'))
                if stripped_line[level:].startswith(' '):
                    style_class = f'class:markdown.h{min(level, 3)}'
                    content_to_parse = stripped_line.lstrip('#').lstrip()
                    # Calculate prefix including original indentation and '#' marks
                    prefix = line[:len(line) - len(content_to_parse)]
                    prefix_tuples.append((style_class, prefix))
            
            # Check for lists if not a header
            else:
                ulist_match = ulist_pattern.match(line)
                olist_match = olist_pattern.match(line)
                list_match = ulist_match or olist_match

                if list_match:
                    indent, marker, space, content = list_match.groups()
                    prefix_tuples.extend([
                        ('', indent),
                        ('class:markdown.list-marker', marker),
                        ('', space)
                    ])
                    content_to_parse = content
            
            # Now, parse the content and combine
            formatted_text.extend(prefix_tuples)
            formatted_text.extend(MarkdownFormatter.parse_inline_markdown(content_to_parse))
            
            # Add newline for all but the last line
            if i < len(lines) - 1:
                formatted_text.append(('', '\n'))

        return formatted_text