import logging
import os
import re
import sys
import traceback
from typing import Optional, List, Dict, Tuple

from prompt_toolkit import print_formatted_text
from prompt_toolkit.application.current import get_app
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.styles import Style
from prompt_toolkit.utils import get_cwidth

from tinycoder.llms.base import LLMClient
from tinycoder.llms.pricing import get_model_pricing


class LLMResponseProcessor:
    """Handles LLM response generation, streaming, formatting, and token tracking."""
    
    def __init__(self, client: LLMClient, model: str, style: Style, logger: logging.Logger):
        self.client = client
        self.model = model
        self.style = style
        self.logger = logger
        self.total_input_tokens = 0
        self.total_output_tokens = 0

    def process(self, messages_to_send: List[Dict[str, str]], mode: str, use_streaming: bool) -> Optional[str]:
        """
        Sends messages to LLM and returns the response content.
        Handles both streaming and non-streaming modes.
        """
        try:
            # Extract system prompt and history
            system_prompt_text = ""
            history_to_send = []

            if messages_to_send and messages_to_send[0]["role"] == "system":
                system_prompt_text = messages_to_send[0]["content"]
                history_to_send = messages_to_send[1:]
            else:
                history_to_send = messages_to_send
                self.logger.warning("System prompt not found at the beginning of messages for LLM.")

            # Calculate input tokens
            input_chars = sum(len(msg["content"]) for msg in history_to_send) + len(system_prompt_text)
            input_tokens = round(input_chars / 4)
            self.total_input_tokens += input_tokens
            
            self.logger.debug(f"Approx. input tokens to send: {input_tokens}")

            response_content = None
            error_message = None

            # Handle streaming mode
            if use_streaming and hasattr(self.client, 'generate_content_stream'):
                response_content = self._handle_streaming(system_prompt_text, history_to_send, mode)
                if response_content is None:
                    error_message = "Streaming failed"
            else:
                # Non-streaming mode
                response_content, error_message = self.client.generate_content(
                    system_prompt=system_prompt_text, history=history_to_send
                )

            # Handle response
            if error_message:
                self.logger.error(f"Error calling LLM API ({self.client.__class__.__name__}): {error_message}")
                return None
            elif response_content is None:
                self.logger.warning(f"LLM API ({self.client.__class__.__name__}) returned no content.")
                return None
            else:
                # For non-streaming, print the response
                if not (use_streaming and hasattr(self.client, 'generate_content_stream')):
                    self._print_response(response_content, mode)
                
                # Track output tokens
                output_tokens = round(len(response_content) / 4)
                self.total_output_tokens += output_tokens
                self.logger.debug(f"Approx. response tokens: {output_tokens}")
                
                return response_content

        except Exception as e:
            self.logger.error(f"An unexpected error occurred during LLM API call ({self.client.__class__.__name__}): {e}")
            traceback.print_exc()
            return None

    def _handle_streaming(self, system_prompt_text: str, history_to_send: List[Dict[str, str]], mode: str) -> Optional[str]:
        """Handles streaming LLM response."""
        assistant_header = [('class:assistant.header', 'ASSISTANT'), ('', ':\n')]
        print_formatted_text(FormattedText(assistant_header), style=self.style)
        
        full_response_chunks = []
        try:
            stream = self.client.generate_content_stream(
                system_prompt=system_prompt_text, history=history_to_send
            )
            for chunk in stream:
                if "STREAMING_ERROR:" in chunk:
                    return None
                
                # Use print_formatted_text to be safe with prompt_toolkit rendering
                print_formatted_text(chunk, end='')
                sys.stdout.flush()  # Ensure chunks are displayed immediately
                full_response_chunks.append(chunk)
            
            response_content = "".join(full_response_chunks)

            # Re-render with formatting if applicable
            is_markdown_candidate = mode == "ask" and response_content and not response_content.strip().startswith("<")
            
            if is_markdown_candidate:
                self._reformat_streamed_response(response_content)
            else:
                # Not a markdown candidate. The original streamed output is fine.
                # We just need the newline that was originally there.
                print()
            
            return response_content

        except Exception as e:
            self.logger.error(f"Error while streaming from LLM: {e}", exc_info=True)
            return None

    def _reformat_streamed_response(self, response_content: str) -> None:
        """Reformats streamed response for better terminal display."""
        try:
            try:
                width = get_app().output.get_size().columns
            except Exception:
                width = os.get_terminal_size().columns
            
            # Calculate lines for the streamed content
            content_lines_count = self._calculate_content_lines(response_content, width)
            
            # Total lines to move up: header (1) + content lines.
            total_lines_up = 1 + content_lines_count

            # Move cursor up, clear, and reprint formatted
            sys.stdout.write(f"\x1b[{total_lines_up}A")
            sys.stdout.write("\x1b[J")
            sys.stdout.flush()

            assistant_header = [('class:assistant.header', 'ASSISTANT'), ('', ':\n')]
            print_formatted_text(FormattedText(assistant_header), style=self.style)
            
            display_response_tuples = self._format_markdown_for_terminal(response_content)
            print_formatted_text(FormattedText(display_response_tuples), style=self.style)
            print()  # Match spacing of non-streaming case

        except Exception as fmt_e:
            # If formatting fails, just print a newline to not mess up the prompt
            print()
            self.logger.warning(f"Could not re-format streaming response: {fmt_e}")

    def _calculate_content_lines(self, content: str, width: int) -> int:
        """Calculate number of lines needed to display content at given width."""
        if not content:
            return 0
            
        lines = 1
        current_line_length = 0
        
        for char in content:
            if char == '\n':
                lines += 1
                current_line_length = 0
            else:
                char_width = get_cwidth(char)
                if current_line_length + char_width > width:
                    lines += 1
                    current_line_length = char_width
                else:
                    current_line_length += char_width
        
        # Check for soft wrap on last line
        if not content.endswith('\n') and current_line_length > 0 and current_line_length % width == 0:
            lines += 1
            
        return lines

    def _print_response(self, response_content: str, mode: str) -> None:
        """Prints LLM response in non-streaming mode."""
        assistant_header = [('class:assistant.header', 'ASSISTANT'), ('', ':\n')]
        print_formatted_text(FormattedText(assistant_header), style=self.style)

        # Format for display if in ask mode and not an edit block
        if mode == "ask" and response_content and not response_content.strip().startswith("<"):
            display_response_tuples = self._format_markdown_for_terminal(response_content)
            print_formatted_text(FormattedText(display_response_tuples), style=self.style)
        else:
            # Print raw content, but use prompt_toolkit to handle potential long lines
            print_formatted_text(response_content)
        
        print()  # Add a final newline for spacing

    def _format_markdown_for_terminal(self, markdown_text: str) -> List[Tuple[str, str]]:
        """Converts markdown text to a list of (style_class, text) tuples for prompt_toolkit."""
        formatted_text = []
        in_code_block = False

        # Regex for lists
        ulist_pattern = re.compile(r'^(\s*)([*+-])(\s+)(.*)')
        olist_pattern = re.compile(r'^(\s*)(\d+\.)(\s+)(.*)')

        lines = markdown_text.split('\n')
        for i, line in enumerate(lines):
            # Handle full-line block elements first
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

            # Handle elements with inline content
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
            
            # Parse the content and combine
            formatted_text.extend(prefix_tuples)
            formatted_text.extend(self._parse_inline_markdown(content_to_parse))
            
            # Add newline for all but the last line
            if i < len(lines) - 1:
                formatted_text.append(('', '\n'))

        return formatted_text

    def _parse_inline_markdown(self, text: str) -> List[Tuple[str, str]]:
        """Parses a single line of text for inline markdown styles like bold, italic, and code."""
        # Combined pattern to find all markdown elements at once.
        # Order of OR matters for greedy matching: *** before **, *
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
            else:  # Should not happen
                style = ''
                content = matched_text
            
            parts.append((style, content))
            last_end = end

        # Add any remaining plain text after the last match
        if last_end < len(text):
            parts.append(('', text[last_end:]))

        return parts

    def get_usage_summary(self) -> Tuple[int, int, int]:
        """Returns total input tokens, output tokens, and total tokens."""
        total_tokens = self.total_input_tokens + self.total_output_tokens
        return self.total_input_tokens, self.total_output_tokens, total_tokens

    def get_cost_estimate(self) -> Optional[float]:
        """Returns estimated cost in USD, or None if pricing unavailable."""
        pricing = get_model_pricing(self.model)
        if not pricing:
            return None
            
        input_cost = (self.total_input_tokens / 1_000_000) * pricing["input"]
        output_cost = (self.total_output_tokens / 1_000_000) * pricing["output"]
        return input_cost + output_cost