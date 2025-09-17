import logging
import os
import re
import sys
import traceback
from typing import Optional, List, Dict, Tuple, Iterable

import zenllm as llm
from prompt_toolkit import print_formatted_text
from prompt_toolkit.application.current import get_app
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.styles import Style
from prompt_toolkit.utils import get_cwidth


class LLMResponseProcessor:
    """Handles LLM response generation, streaming, formatting, and usage tracking via zenllm."""
    
    def __init__(self, model: str, style: Style, logger: logging.Logger, provider: Optional[str]=None, base_url: Optional[str]=None):
        self.model = model
        self.provider = provider
        self.base_url = base_url
        self.style = style
        self.logger = logger
        self.total_input_tokens = 0
        self.total_output_tokens = 0
        self.total_cost_usd: float = 0.0

    def _raw_model_for_call(self) -> str:
        """Return the model id stripped of any redundant provider prefix when provider/base_url are explicit.
        
        Do NOT strip for providers whose native model IDs include their prefix:
        - anthropic: claude-*
        - gemini: gemini-*
        - deepseek: deepseek-*
        
        Only strip for providers that don't require the provider name in the model id:
        - groq: remove leading "groq-"
        - together: remove leading "together-"
        - xai: remove leading "xai-" (but keep native "grok-*" as-is)
        """
        model = self.model or ""
        p = (self.provider or "").lower() if self.provider else ""
        if not p:
            return model
        if p in ("groq", "together") and model.startswith(f"{p}-"):
            return model[len(p) + 1:]
        if p == "xai" and model.startswith("xai-"):
            return model[len("xai-"):]
        return model

    def process(self, messages_to_send: List[Dict[str, str]], mode: str, use_streaming: bool) -> Optional[str]:
        """
        Sends messages to LLM via zenllm.chat and returns the response content.
        Handles both streaming and non-streaming modes.
        """
        try:
            # Convert messages into zenllm shorthands
            zen_messages: List[Tuple[str, str]] = []
            for msg in messages_to_send:
                role = msg.get("role")
                content = msg.get("content", "") or ""
                if role in ("system", "user", "assistant"):
                    zen_messages.append((role, content))

            # Approximate input tokens (adjust later if real usage is available)
            input_chars = sum(len(m[1]) for m in zen_messages)
            approx_input_tokens = round(input_chars / 4)
            self.total_input_tokens += approx_input_tokens
            self.logger.debug(f"Approx. input tokens to send: {approx_input_tokens}")

            if use_streaming:
                response_content, final_resp = self._handle_streaming(zen_messages, mode)
                if response_content is None or final_resp is None:
                    self.logger.error("Error calling LLM API (zenllm) in streaming mode.")
                    return None
                # Track approximate output tokens first
                approx_output_tokens = round(len(response_content) / 4)
                self.total_output_tokens += approx_output_tokens
                self.logger.debug(f"Approx. response tokens: {approx_output_tokens}")
                # Adjust with real usage if available
                self._adjust_usage_and_cost(final_resp, approx_input_tokens, approx_output_tokens)
                return response_content
            else:
                call_model = self._raw_model_for_call()
                kwargs = {"model": call_model}
                if self.provider:
                    kwargs["provider"] = self.provider
                if self.base_url:
                    kwargs["base_url"] = self.base_url
                resp = llm.chat(zen_messages, **kwargs)
                
                response_content = (resp.text or "")
                # Print the response in non-streaming mode
                self._print_response(response_content, mode)
                # Track approximate output tokens
                approx_output_tokens = round(len(response_content) / 4)
                self.total_output_tokens += approx_output_tokens
                self.logger.debug(f"Approx. response tokens: {approx_output_tokens}")
                # Adjust with real usage and add cost if available
                self._adjust_usage_and_cost(resp, approx_input_tokens, approx_output_tokens)
                return response_content

        except Exception as e:
            self.logger.error(f"An unexpected error occurred during zenllm API call: {e}")
            traceback.print_exc()
            return None

    def _adjust_usage_and_cost(self, resp: object, approx_in: int, approx_out: int) -> None:
        """Adjust token counters using provider usage if available; accumulate cost if reported."""
        try:
            usage = getattr(resp, "usage", None)
        except Exception:
            usage = None

        if isinstance(usage, dict):
            in_tok = usage.get("input_tokens")
            out_tok = usage.get("output_tokens")
            # Common alternates
            if in_tok is None and "prompt_tokens" in usage:
                in_tok = usage.get("prompt_tokens")
            if out_tok is None and "completion_tokens" in usage:
                out_tok = usage.get("completion_tokens")

            try:
                if in_tok is not None:
                    in_tok = int(in_tok)
                    self.total_input_tokens += (in_tok - approx_in)
                    self.logger.debug(f"Adjusted input tokens to provider-reported value: {in_tok}")
                if out_tok is not None:
                    out_tok = int(out_tok)
                    self.total_output_tokens += (out_tok - approx_out)
                    self.logger.debug(f"Adjusted output tokens to provider-reported value: {out_tok}")
            except Exception:
                pass

        # Cost accumulation if zenllm can compute it
        try:
            cost_val = getattr(resp, "cost", None)
            if callable(cost_val):
                cost = cost_val()  # returns float or None
                if isinstance(cost, (int, float)):
                    self.total_cost_usd += float(cost)
        except Exception:
            pass

    def _handle_streaming(self, zen_messages: List[Tuple[str, str]], mode: str) -> Tuple[Optional[str], Optional[object]]:
        """Handles streaming LLM response via zenllm."""
        assistant_header = [('class:assistant.header', 'ASSISTANT'), ('', ':\n')]
        print_formatted_text(FormattedText(assistant_header), style=self.style)
        
        full_response_chunks: List[str] = []
        try:
            call_model = self._raw_model_for_call()
            kwargs = {"model": call_model, "stream": True}
            if self.provider:
                kwargs["provider"] = self.provider
            if self.base_url:
                kwargs["base_url"] = self.base_url
            stream = llm.chat(zen_messages, **kwargs)
            for ev in stream:
                # Only surface text events to the console
                if getattr(ev, "type", None) == "text":
                    text = getattr(ev, "text", "")
                    if text:
                        print_formatted_text(text, end='')
                        sys.stdout.flush()
                        full_response_chunks.append(text)

            final_resp = stream.finalize()
            response_content = "".join(full_response_chunks)

            # Re-render with formatting if applicable
            is_markdown_candidate = mode == "ask" and response_content and not response_content.strip().startswith("<")
            if is_markdown_candidate:
                self._reformat_streamed_response(response_content)
            else:
                print()  # newline for spacing
            
            return response_content, final_resp

        except Exception as e:
            self.logger.error(f"Error while streaming from zenllm: {e}", exc_info=True)
            return None, None

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
        pattern = re.compile(
            r'(\*\*\*.+?\*\*\*|___.+?___)'  # Bold+Italic
            r'|(\*\*.+?\*\*|__.+?__)'       # Bold
            r'|(\*.+?\*|_.+?_)'             # Italic
            r'|(`.+?`)'                      # Inline Code
        )

        parts: List[Tuple[str, str]] = []
        last_end = 0
        for match in pattern.finditer(text):
            start, end = match.span()
            if start > last_end:
                parts.append(('', text[last_end:start]))

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
            else:
                style = ''
                content = matched_text
            
            parts.append((style, content))
            last_end = end

        if last_end < len(text):
            parts.append(('', text[last_end:]))

        return parts

    def get_usage_summary(self) -> Tuple[int, int, int]:
        """Returns total input tokens, output tokens, and total tokens."""
        total_tokens = self.total_input_tokens + self.total_output_tokens
        return self.total_input_tokens, self.total_output_tokens, total_tokens

    def get_cost_estimate(self) -> Optional[float]:
        """
        Returns accumulated cost in USD if zenllm provided pricing; otherwise None.
        """
        return self.total_cost_usd if self.total_cost_usd > 0 else None