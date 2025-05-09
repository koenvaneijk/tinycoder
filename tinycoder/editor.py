import curses
import curses.ascii
import os
import io
import tokenize
import keyword
import traceback
import locale
from typing import List, Tuple, Optional

class EditorConstants:
    """Stores all constants for the editor."""
    # Color pair definitions
    COLOR_PAIR_DEFAULT: int = 1
    COLOR_PAIR_COMMENT: int = 2
    COLOR_PAIR_STRING: int = 3
    COLOR_PAIR_NUMBER: int = 4
    COLOR_PAIR_KEYWORD_MAIN: int = 5
    COLOR_PAIR_KEYWORD_SECONDARY: int = 6
    COLOR_PAIR_OPERATOR: int = 7
    COLOR_PAIR_FUNCTION_NAME: int = 8
    COLOR_PAIR_CLASS_NAME: int = 9
    COLOR_PAIR_IDENTIFIER_DEFAULT: int = 10
    COLOR_PAIR_LINE_NUMBER: int = 11

    # Ncurses color indices (for 256-color mode)
    NCURSES_COLOR_BG: int = 234
    NCURSES_COLOR_DEFAULT_TEXT: int = 252
    NCURSES_COLOR_COMMENT_FG: int = 65
    NCURSES_COLOR_STRING_FG: int = 174
    NCURSES_COLOR_NUMBER_FG: int = 151
    NCURSES_COLOR_KEYWORD_MAIN_FG: int = 175
    NCURSES_COLOR_KEYWORD_SECONDARY_FG: int = 74
    NCURSES_COLOR_OPERATOR_FG: int = 188
    NCURSES_COLOR_FUNCTION_NAME_FG: int = 187
    NCURSES_COLOR_CLASS_NAME_FG: int = 79
    NCURSES_COLOR_IDENTIFIER_DEFAULT_FG: int = 153

    LINE_NUMBER_AREA_WIDTH: int = 6
    STATUS_BAR_HEIGHT: int = 1
    TAB_WIDTH: int = 4

    # Syntax Highlighting Keywords
    KEYWORDS_MAIN: set[str] = {"def", "class", "import", "from", "global", "nonlocal", "pass", "del", "assert", "lambda"}
    KEYWORDS_SECONDARY: set[str] = {
        "if", "else", "elif", "for", "while", "try", "except", "finally", "match", "case",
        "return", "raise", "yield", "break", "continue",
        "in", "is", "and", "or", "not",
        "async", "await", "with"
    }
    LANGUAGE_CONSTANTS_AND_SPECIAL_VARS: set[str] = {"True", "False", "None", "self", "cls"}


class ColorManager:
    """Manages curses color pairs and default attributes."""
    def __init__(self) -> None:
        self.default_attr: int = curses.A_NORMAL
        self._initialize_colors()

    def _initialize_colors(self) -> None:
        """Initializes color pairs based on terminal capabilities."""
        if curses.has_colors():
            curses.start_color()
            curses.use_default_colors() # Use terminal's default background
            actual_bg_color: int = -1 # Use default background

            if curses.COLORS >= 256:
                self._init_256_color_pairs(actual_bg_color)
            else:
                self._init_basic_color_pairs(actual_bg_color)
            
            self.default_attr = curses.color_pair(EditorConstants.COLOR_PAIR_DEFAULT)
        else:
            self.default_attr = curses.A_NORMAL
            
    def _init_256_color_pairs(self, bg_color: int) -> None:
        """Initializes color pairs for 256-color terminals."""
        C = EditorConstants
        curses.init_pair(C.COLOR_PAIR_DEFAULT, C.NCURSES_COLOR_DEFAULT_TEXT, bg_color)
        curses.init_pair(C.COLOR_PAIR_COMMENT, C.NCURSES_COLOR_COMMENT_FG, bg_color)
        curses.init_pair(C.COLOR_PAIR_STRING, C.NCURSES_COLOR_STRING_FG, bg_color)
        curses.init_pair(C.COLOR_PAIR_NUMBER, C.NCURSES_COLOR_NUMBER_FG, bg_color)
        curses.init_pair(C.COLOR_PAIR_KEYWORD_MAIN, C.NCURSES_COLOR_KEYWORD_MAIN_FG, bg_color)
        curses.init_pair(C.COLOR_PAIR_KEYWORD_SECONDARY, C.NCURSES_COLOR_KEYWORD_SECONDARY_FG, bg_color)
        curses.init_pair(C.COLOR_PAIR_OPERATOR, C.NCURSES_COLOR_OPERATOR_FG, bg_color)
        curses.init_pair(C.COLOR_PAIR_FUNCTION_NAME, C.NCURSES_COLOR_FUNCTION_NAME_FG, bg_color)
        curses.init_pair(C.COLOR_PAIR_CLASS_NAME, C.NCURSES_COLOR_CLASS_NAME_FG, bg_color)
        curses.init_pair(C.COLOR_PAIR_IDENTIFIER_DEFAULT, C.NCURSES_COLOR_IDENTIFIER_DEFAULT_FG, bg_color)
        curses.init_pair(C.COLOR_PAIR_LINE_NUMBER, C.NCURSES_COLOR_DEFAULT_TEXT, bg_color)

    def _init_basic_color_pairs(self, bg_color: int) -> None:
        """Initializes color pairs for basic 8/16-color terminals."""
        C = EditorConstants
        curses.init_pair(C.COLOR_PAIR_DEFAULT, curses.COLOR_WHITE, bg_color)
        curses.init_pair(C.COLOR_PAIR_COMMENT, curses.COLOR_GREEN, bg_color)
        curses.init_pair(C.COLOR_PAIR_STRING, curses.COLOR_RED, bg_color)
        curses.init_pair(C.COLOR_PAIR_NUMBER, curses.COLOR_CYAN, bg_color)
        curses.init_pair(C.COLOR_PAIR_KEYWORD_MAIN, curses.COLOR_MAGENTA, bg_color)
        curses.init_pair(C.COLOR_PAIR_KEYWORD_SECONDARY, curses.COLOR_BLUE, bg_color)
        curses.init_pair(C.COLOR_PAIR_OPERATOR, curses.COLOR_WHITE, bg_color) # Basic fallback
        curses.init_pair(C.COLOR_PAIR_FUNCTION_NAME, curses.COLOR_YELLOW, bg_color)
        curses.init_pair(C.COLOR_PAIR_CLASS_NAME, curses.COLOR_CYAN, bg_color) # Basic fallback
        curses.init_pair(C.COLOR_PAIR_IDENTIFIER_DEFAULT, curses.COLOR_WHITE, bg_color)
        curses.init_pair(C.COLOR_PAIR_LINE_NUMBER, curses.COLOR_WHITE, bg_color)

    def get_pair(self, pair_id: int) -> int:
        """Gets the curses attribute for a defined color pair."""
        if curses.has_colors():
            return curses.color_pair(pair_id)
        return self.default_attr


class SyntaxHighlighter:
    """Provides syntax highlighting for Python code."""
    def __init__(self, color_manager: ColorManager) -> None:
        self.color_manager = color_manager

    def get_styled_segments(self, line_text: str) -> List[Tuple[str, int]]:
        """
        Tokenizes a line of text and returns segments with their style attributes.

        Args:
            line_text: The line of text to highlight.

        Returns:
            A list of (text_segment, style_attribute) tuples.
        """
        styled_segments: List[Tuple[str, int]] = []
        
        if not line_text.strip() and line_text: # Line with only whitespace
            return [(line_text, self.color_manager.default_attr)]

        try:
            line_bytes = line_text.encode('utf-8')
            tokens = list(tokenize.tokenize(io.BytesIO(line_bytes).readline))
        except tokenize.TokenError: # Incomplete syntax, return as default
            return [(line_text, self.color_manager.default_attr)]
        except Exception: # Catch other potential tokenization errors
             return [(line_text, self.color_manager.default_attr)]


        last_col = 0
        for i, token_info in enumerate(tokens):
            token_type, token_str, (srow, scol), (erow, ecol), line_logic = token_info

            if token_type == tokenize.ENCODING or token_type == tokenize.ENDMARKER:
                continue
            if token_type == tokenize.NL or token_type == tokenize.NEWLINE:
                continue

            # Add part before token (whitespace or untokenized)
            if scol > last_col:
                prefix = line_text[last_col:scol]
                styled_segments.append((prefix, self.color_manager.default_attr))

            color_attr = self._get_token_color_attr(token_type, token_str, tokens, i)
            styled_segments.append((token_str, color_attr))
            last_col = ecol
        
        # Add any remaining part of the line after the last token
        if last_col < len(line_text):
            suffix = line_text[last_col:]
            styled_segments.append((suffix, self.color_manager.default_attr))
            
        return styled_segments

    def _get_token_color_attr(self, token_type: int, token_str: str, tokens: List[tokenize.TokenInfo], current_token_index: int) -> int:
        """Determines the color attribute for a given token."""
        C = EditorConstants
        CM = self.color_manager

        if not curses.has_colors():
            return CM.default_attr

        is_keyword_token = token_type == tokenize.SOFT_KEYWORD or \
                           (token_type == tokenize.NAME and keyword.iskeyword(token_str))

        if is_keyword_token:
            if token_str in C.KEYWORDS_MAIN:
                return CM.get_pair(C.COLOR_PAIR_KEYWORD_MAIN)
            elif token_str in C.KEYWORDS_SECONDARY:
                return CM.get_pair(C.COLOR_PAIR_KEYWORD_SECONDARY)
            return CM.get_pair(C.COLOR_PAIR_KEYWORD_MAIN) # Fallback for other keywords
        elif token_type == tokenize.NAME:
            if token_str in C.LANGUAGE_CONSTANTS_AND_SPECIAL_VARS:
                return CM.get_pair(C.COLOR_PAIR_KEYWORD_SECONDARY)
            
            # Context check for function/class names
            if current_token_index > 0:
                prev_token_info = tokens[current_token_index - 1]
                is_prev_keyword_def_class = prev_token_info.type == tokenize.SOFT_KEYWORD or \
                                           (prev_token_info.type == tokenize.NAME and keyword.iskeyword(prev_token_info.string))
                
                if is_prev_keyword_def_class:
                    if prev_token_info.string == "def":
                        return CM.get_pair(C.COLOR_PAIR_FUNCTION_NAME)
                    elif prev_token_info.string == "class":
                        return CM.get_pair(C.COLOR_PAIR_CLASS_NAME)
            return CM.get_pair(C.COLOR_PAIR_IDENTIFIER_DEFAULT)
        elif token_type == tokenize.STRING:
            return CM.get_pair(C.COLOR_PAIR_STRING)
        elif token_type == tokenize.COMMENT:
            return CM.get_pair(C.COLOR_PAIR_COMMENT)
        elif token_type == tokenize.NUMBER:
            return CM.get_pair(C.COLOR_PAIR_NUMBER)
        elif token_type == tokenize.OP:
            return CM.get_pair(C.COLOR_PAIR_OPERATOR)
        
        return CM.default_attr # Fallback for other token types


class Buffer:
    """Manages the text content of the editor."""
    def __init__(self, filepath: Optional[str] = None) -> None:
        self.lines: List[str] = [""]
        self.filepath: Optional[str] = filepath
        self.text_changed: bool = False
        if filepath:
            self.load_file(filepath)

    def load_file(self, filepath: str) -> None:
        """Loads content from a file into the buffer."""
        self.filepath = filepath
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                self.lines = [line.rstrip('\n') for line in f.readlines()]
            if not self.lines: # Ensure at least one empty line if file was empty
                self.lines = [""]
        except FileNotFoundError:
            self.lines = [""] # Start with an empty line if file not found
        self.text_changed = False

    def save_file(self, filepath: Optional[str] = None) -> Tuple[bool, Optional[str]]:
        """
        Saves the buffer content to a file.
        Returns (success_status, error_message_or_None).
        """
        target_path = filepath if filepath else self.filepath
        if not target_path:
            return False, "No filepath specified for saving."
        
        try:
            with open(target_path, "w", encoding="utf-8") as f:
                for line_text in self.lines:
                    f.write(line_text + "\n")
            self.filepath = target_path # Update if saved to a new path
            self.text_changed = False
            return True, None
        except Exception as e:
            return False, str(e)

    def get_line_count(self) -> int:
        return len(self.lines)

    def get_line(self, index: int) -> str:
        if 0 <= index < len(self.lines):
            return self.lines[index]
        return "" # Should not happen with proper bounds checks

    def get_line_length(self, line_index: int) -> int:
        return len(self.get_line(line_index))

    def find_all(self, term: str) -> List[Tuple[int, int]]:
        """Finds all occurrences of a term in the buffer."""
        if not term:
            return []
        
        results: List[Tuple[int, int]] = []
        for line_idx, line_content in enumerate(self.lines):
            start_col = 0
            while True:
                pos = line_content.find(term, start_col)
                if pos == -1:
                    break
                results.append((line_idx, pos))
                start_col = pos + 1 # Start next search after this match
        return results

    def insert_char(self, y: int, x: int, char: str) -> None:
        """Inserts a character at the given buffer coordinates."""
        line = self.get_line(y)
        self.lines[y] = line[:x] + char + line[x:]
        self.text_changed = True

    def delete_char(self, y: int, x: int) -> None: # Deletes char before cursor (backspace)
        """Deletes a character at (y, x-1) in the buffer."""
        if x > 0:
            line = self.get_line(y)
            self.lines[y] = line[:x-1] + line[x:]
            self.text_changed = True
        elif y > 0: # Backspace at start of line, merge with previous
            current_line_content = self.lines.pop(y)
            self.lines[y-1] += current_line_content
            self.text_changed = True
    
    def delete_forward_char(self, y: int, x: int) -> None: # Deletes char at cursor (delete key)
        """Deletes a character at (y, x) in the buffer."""
        line = self.get_line(y)
        if x < len(line):
            self.lines[y] = line[:x] + line[x+1:]
            self.text_changed = True
        elif y < self.get_line_count() - 1: # Delete EOL, merge with next line
            next_line_content = self.lines.pop(y+1)
            self.lines[y] += next_line_content
            self.text_changed = True


    def split_line(self, y: int, x: int) -> None:
        """Splits a line at (y,x), creating a new line."""
        line = self.get_line(y)
        before_cursor = line[:x]
        after_cursor = line[x:]
        
        # Auto-indent for the new line
        leading_whitespace = ""
        for char_in_line in before_cursor: # Indent based on current line's start
            if char_in_line.isspace():
                leading_whitespace += char_in_line
            else:
                break # Stop at first non-whitespace
        
        self.lines[y] = before_cursor
        self.lines.insert(y + 1, leading_whitespace + after_cursor)
        self.text_changed = True


class EditorState:
    """Manages editor state like cursor, viewport, and screen dimensions."""
    def __init__(self) -> None:
        self.cursor_y: int = 0  # Buffer line index
        self.cursor_x: int = 0  # Buffer column index
        self.top_line: int = 0  # First visible line index in buffer
        self.view_start_col: int = 0  # First visible column index for horizontal scroll

        self.screen_rows: int = 0
        self.screen_cols: int = 0
        self.text_area_height: int = 0
        self.text_content_display_width: int = 0
        
        self.status_message: Optional[str] = None
        self.status_message_is_error: bool = False

        # Find functionality state
        self.is_finding: bool = False  # True when find mode is active (results shown, navigating)
        self.find_input_active: bool = False  # True when user is actively typing the search term
        self.search_term: str = ""
        self.last_searched_term: str = "" # Stores the most recent term for re-search (F3 on empty)
        self.search_prompt: str = "Find: "
        self.search_results: List[Tuple[int, int]] = []  # List of (line_idx, col_idx)
        self.current_search_result_idx: int = -1  # Index in search_results, -1 if no current match


    def update_screen_dimensions(self, screen_rows: int, screen_cols: int) -> None:
        """Updates screen dimensions and recalculates view-dependent properties."""
        self.screen_rows = screen_rows
        self.screen_cols = screen_cols
        self.text_area_height = self.screen_rows - EditorConstants.STATUS_BAR_HEIGHT
        if self.text_area_height < 0: self.text_area_height = 0
        
        self.text_content_display_width = self.screen_cols - EditorConstants.LINE_NUMBER_AREA_WIDTH
        if self.text_content_display_width < 0: self.text_content_display_width = 0
    
    def clamp_cursor(self, buffer: Buffer) -> None:
        """Ensures cursor position is valid within the buffer."""
        self.cursor_y = max(0, min(self.cursor_y, buffer.get_line_count() - 1))
        self.cursor_x = max(0, min(self.cursor_x, buffer.get_line_length(self.cursor_y)))

    def scroll_viewport_to_cursor(self) -> None:
        """Adjusts viewport (top_line, view_start_col) to keep cursor visible."""
        # Vertical scroll
        if self.cursor_y < self.top_line:
            self.top_line = self.cursor_y
        elif self.cursor_y >= self.top_line + self.text_area_height:
            self.top_line = self.cursor_y - self.text_area_height + 1
        if self.top_line < 0: self.top_line = 0

        # Horizontal scroll
        if self.cursor_x < self.view_start_col:
            self.view_start_col = self.cursor_x
        elif self.text_content_display_width > 0 and \
             self.cursor_x >= self.view_start_col + self.text_content_display_width:
            self.view_start_col = self.cursor_x - self.text_content_display_width + 1
        elif self.text_content_display_width == 0 and self.cursor_x > self.view_start_col:
            self.view_start_col = self.cursor_x # Keep cursor at start if no text area
        if self.view_start_col < 0: self.view_start_col = 0

    def set_status_message(self, message: str, is_error: bool = False) -> None:
        self.status_message = message
        self.status_message_is_error = is_error

    def clear_status_message(self) -> None:
        self.status_message = None
        self.status_message_is_error = False

    def get_current_search_match_coords(self) -> Optional[Tuple[int, int]]:
        """Returns (line_idx, col_idx) of the current search match, if any."""
        if self.is_finding and self.search_results and 0 <= self.current_search_result_idx < len(self.search_results):
            return self.search_results[self.current_search_result_idx]
        return None


class EditorView:
    """Handles rendering the editor UI to the curses screen."""
    def __init__(self, color_manager: ColorManager, syntax_highlighter: SyntaxHighlighter) -> None:
        self.color_manager = color_manager
        self.syntax_highlighter = syntax_highlighter

    def render_screen(self, stdscr: 'curses._CursesWindow', buffer: Buffer, state: EditorState) -> None:
        """Renders the entire editor screen."""
        stdscr.erase()
        self._draw_text_area(stdscr, buffer, state)
        self._draw_status_bar(stdscr, buffer, state) # Status bar drawn before cursor positioning for find input
        self._position_cursor_on_screen(stdscr, state)
        stdscr.refresh()

    def _draw_text_area(self, stdscr: 'curses._CursesWindow', buffer: Buffer, state: EditorState) -> None:
        """Draws the main text editing area, including line numbers and content."""
        line_num_attr = self.color_manager.get_pair(EditorConstants.COLOR_PAIR_LINE_NUMBER)
        
        for screen_row_idx in range(state.text_area_height):
            buffer_line_idx = state.top_line + screen_row_idx
            
            # Clear entire line (line numbers + text)
            stdscr.addstr(screen_row_idx, 0, " " * state.screen_cols, self.color_manager.default_attr)

            if buffer_line_idx < buffer.get_line_count():
                line_text = buffer.get_line(buffer_line_idx)
                self._draw_line_number(stdscr, screen_row_idx, buffer_line_idx, line_num_attr, state)
                if state.text_content_display_width > 0:
                    self._draw_line_content(stdscr, screen_row_idx, line_text, state)
            else:
                # Draw tilde for lines not part of the buffer
                tilde_display = "~".rjust(EditorConstants.LINE_NUMBER_AREA_WIDTH - 1) + " "
                stdscr.addstr(screen_row_idx, 0, tilde_display[:min(state.screen_cols, EditorConstants.LINE_NUMBER_AREA_WIDTH)], line_num_attr)

    def _draw_line_number(self, stdscr: 'curses._CursesWindow', screen_row: int, buffer_line_num: int, attr: int, state: EditorState) -> None:
        """Draws the line number for a given screen row."""
        actual_line_num = buffer_line_num + 1
        ln_width = EditorConstants.LINE_NUMBER_AREA_WIDTH
        line_num_str = (f"{actual_line_num}".rjust(ln_width - 1) + " ")
        stdscr.addstr(screen_row, 0, line_num_str[:min(state.screen_cols, ln_width)], attr)

    def _draw_line_content(self, stdscr: 'curses._CursesWindow', screen_row: int, line_text: str, state: EditorState) -> None:
        """Draws the syntax-highlighted content of a single line, with current search match highlighting."""
        text_to_render_fully = line_text[state.view_start_col:]
        styled_segments = self.syntax_highlighter.get_styled_segments(text_to_render_fully)
        
        current_screen_x = EditorConstants.LINE_NUMBER_AREA_WIDTH
        max_render_x = EditorConstants.LINE_NUMBER_AREA_WIDTH + state.text_content_display_width

        current_match_coords = state.get_current_search_match_coords()
        buffer_line_idx = state.top_line + screen_row
        
        highlight_info = None
        if current_match_coords and current_match_coords[0] == buffer_line_idx and state.search_term:
            match_line, match_col = current_match_coords
            term_len = len(state.search_term)
            
            # Calculate highlight start/end relative to text_to_render_fully
            highlight_rel_start = match_col - state.view_start_col
            highlight_rel_end = highlight_rel_start + term_len
            if highlight_rel_end > 0 and highlight_rel_start < len(text_to_render_fully): # Ensure some part is visible
                highlight_info = (max(0, highlight_rel_start), min(len(text_to_render_fully), highlight_rel_end))

        char_offset_in_rendered_text = 0
        for segment_text, original_segment_attr in styled_segments:
            if not segment_text: continue

            current_pos_on_screen = current_screen_x
            
            # Process this segment potentially in three parts: before, during, after highlight
            # All coordinates are relative to the start of `segment_text`
            
            seg_highlight_start = -1
            seg_highlight_end = -1

            if highlight_info:
                # Convert highlight_info (relative to text_to_render_fully) to be relative to current segment_text
                h_start, h_end = highlight_info
                
                # Check for overlap between segment [char_offset_in_rendered_text, char_offset_in_rendered_text + len(segment_text))
                # and highlight [h_start, h_end)
                
                max_start = max(char_offset_in_rendered_text, h_start)
                min_end = min(char_offset_in_rendered_text + len(segment_text), h_end)

                if max_start < min_end: # Overlap exists
                    seg_highlight_start = max_start - char_offset_in_rendered_text
                    seg_highlight_end = min_end - char_offset_in_rendered_text
            
            parts_to_draw = [] # List of (text, attr)
            if seg_highlight_start != -1 : # Highlight applies to this segment
                if seg_highlight_start > 0:
                    parts_to_draw.append((segment_text[:seg_highlight_start], original_segment_attr))
                
                parts_to_draw.append((segment_text[seg_highlight_start:seg_highlight_end], original_segment_attr | curses.A_REVERSE))
                
                if seg_highlight_end < len(segment_text):
                    parts_to_draw.append((segment_text[seg_highlight_end:], original_segment_attr))
            else: # No highlight in this segment
                parts_to_draw.append((segment_text, original_segment_attr))

            for part_text, part_attr in parts_to_draw:
                if not part_text: continue
                remaining_space_on_line = max_render_x - current_pos_on_screen
                if remaining_space_on_line <= 0: break 

                drawable_text = part_text[:remaining_space_on_line]
                try:
                    stdscr.addstr(screen_row, current_pos_on_screen, drawable_text, part_attr)
                    current_pos_on_screen += len(drawable_text)
                except curses.error: break
            
            if current_pos_on_screen >= max_render_x : break # Line fully rendered or overflowed
            char_offset_in_rendered_text += len(segment_text)
            current_screen_x = current_pos_on_screen # Update for next segment based on actual drawn length


    def _draw_status_bar(self, stdscr: 'curses._CursesWindow', buffer: Buffer, state: EditorState) -> None:
        """Draws the status bar at the bottom of the screen."""
        status_y = state.screen_rows - 1
        if status_y < 0: return # No space for status bar

        attr = curses.A_REVERSE # Default status bar attribute
        status_text = ""

        if state.find_input_active:
            status_text = f"{state.search_prompt}{state.search_term}"
            # Cursor for find input is handled by _position_cursor_on_screen if needed,
            # or a simple visual cue like appending '_' can be added here.
            # status_text += "_" # Simple visual cue for input
        elif state.is_finding:
            if state.search_results:
                match_count = len(state.search_results)
                current_match_num = state.current_search_result_idx + 1
                status_text = f"Found {match_count} for '{state.search_term}'. Match {current_match_num}/{match_count}. (F3 Next, Ctrl+R Prev, Esc Exit)"
            else: # Searched, but no results
                status_text = f"Phrase not found: '{state.last_searched_term}'. (Esc Exit)"
        elif state.status_message: # General status messages (Save, Error, etc.)
            status_text = state.status_message
            if state.status_message_is_error and curses.has_colors():
                 attr |= self.color_manager.get_pair(EditorConstants.COLOR_PAIR_STRING)
        else: # Default editor status
            filename = os.path.basename(buffer.filepath) if buffer.filepath else "[No Name]"
            modified_indicator = "MODIFIED | " if buffer.text_changed else ""
            pos_indicator = f"L:{state.cursor_y + 1} C:{state.cursor_x + 1} V:{state.top_line+1},{state.view_start_col+1}"
            status_text = f"{filename} | {modified_indicator}{pos_indicator} | Ctrl+F:Find Ctrl+S:Save Ctrl+Q:Quit"
            if buffer.text_changed and curses.has_colors():
                attr |= self.color_manager.get_pair(EditorConstants.COLOR_PAIR_KEYWORD_MAIN)

        stdscr.attron(attr)
        
        # Prepare the string: ljust and then truncate to screen_cols
        # This ensures the text is exactly state.screen_cols characters long.
        prepared_text = status_text.ljust(state.screen_cols)[:state.screen_cols]

        if state.screen_cols > 0:
            # Write all characters up to the second to last using addstr.
            # If screen_cols is 1, prepared_text[:-1] will be an empty string.
            stdscr.addstr(status_y, 0, prepared_text[:-1], attr)
            
            # Write the very last character using insch to avoid the common curses bug
            # at the bottom-right corner of the screen. insch doesn't auto-advance cursor.
            stdscr.insch(status_y, state.screen_cols - 1, prepared_text[-1], attr)
        # If state.screen_cols is 0, nothing is drawn, which is correct.
        
        stdscr.attroff(attr)
        
    def _position_cursor_on_screen(self, stdscr: 'curses._CursesWindow', state: EditorState) -> None:
        """Positions the curses cursor based on editor state."""
        screen_cursor_y = state.cursor_y - state.top_line
        
        cursor_x_in_text_segment = state.cursor_x - state.view_start_col
        screen_cursor_x_on_text = EditorConstants.LINE_NUMBER_AREA_WIDTH + cursor_x_in_text_segment

        # Clamp cursor to be within visible text area bounds
        min_x = EditorConstants.LINE_NUMBER_AREA_WIDTH
        max_x = EditorConstants.LINE_NUMBER_AREA_WIDTH + state.text_content_display_width -1
        if state.text_content_display_width == 0 : # No text area visible
             max_x = EditorConstants.LINE_NUMBER_AREA_WIDTH -1 # End of line number area
        
        final_screen_x = max(min_x, min(screen_cursor_x_on_text, max_x))
        final_screen_x = max(0, min(final_screen_x, state.screen_cols - 1)) # Ensure within physical screen
        final_screen_y = max(0, min(screen_cursor_y, state.text_area_height -1)) # Ensure within physical screen

        if state.find_input_active: # Position cursor at end of search prompt in status bar
            status_bar_y = state.screen_rows - 1
            if status_bar_y >= 0:
                prompt_len = len(state.search_prompt)
                term_len = len(state.search_term)
                # Ensure cursor stays within screen bounds
                cursor_x_in_status = min(prompt_len + term_len, state.screen_cols -1)
                final_screen_y, final_screen_x = status_bar_y, cursor_x_in_status

        if 0 <= final_screen_y < state.screen_rows and 0 <= final_screen_x < state.screen_cols:
            try:
                stdscr.move(final_screen_y, final_screen_x)
            except curses.error:
                pass # Ignore if cursor can't be placed (e.g. tiny terminal)


class InputHandler:
    """Processes keyboard and mouse input, and triggers editor actions."""
    def __init__(self, buffer: Buffer, state: EditorState, view: EditorView) -> None:
        self.buffer = buffer
        self.state = state
        self.view = view
        self.pending_quit_confirmation: bool = False

    def _start_find_input_mode(self, reuse_term: bool = True) -> None:
        """Activates find input mode."""
        self.state.is_finding = True
        self.state.find_input_active = True
        if reuse_term:
            self.state.search_term = self.state.last_searched_term
        else:
            self.state.search_term = ""
        self.state.search_results = []
        self.state.current_search_result_idx = -1
        # Status message will be handled by view based on find_input_active

    def _exit_find_mode(self, clear_status: bool = True) -> None:
        """Deactivates all find states."""
        self.state.is_finding = False
        self.state.find_input_active = False
        # self.state.search_term = "" # Keep for quick re-Ctrl+F
        self.state.search_results = []
        self.state.current_search_result_idx = -1
        if clear_status:
            self.state.clear_status_message()

    def _execute_search(self) -> None:
        """Executes the search based on state.search_term."""
        self.state.find_input_active = False # Exiting input mode
        if not self.state.search_term:
            self._exit_find_mode(clear_status=True)
            self.state.set_status_message("Search term cleared.")
            return

        self.state.last_searched_term = self.state.search_term
        self.state.search_results = self.buffer.find_all(self.state.search_term)
        
        if self.state.search_results:
            self.state.current_search_result_idx = 0
            self._navigate_to_match(0)
            # Status message handled by view based on is_finding and results
        else:
            self.state.current_search_result_idx = -1
            # Status message handled by view
        # is_finding remains true to show results or "not found"

    def _navigate_to_match(self, match_idx: int) -> None:
        """Moves cursor to the specified search result index."""
        if not self.state.search_results or not (0 <= match_idx < len(self.state.search_results)):
            return
        
        self.state.current_search_result_idx = match_idx
        line_idx, col_idx = self.state.search_results[match_idx]
        self.state.cursor_y = line_idx
        self.state.cursor_x = col_idx
        self.state.clamp_cursor(self.buffer) # Ensure still valid after potential buffer changes
        self.state.scroll_viewport_to_cursor()

    def _find_next_or_previous(self, direction: int) -> None:
        """Navigates to the next (1) or previous (-1) search result."""
        if not self.state.search_results: # No results to navigate
            if self.state.last_searched_term: # Try to re-search
                self.state.search_term = self.state.last_searched_term
                self._execute_search() # This will navigate if results found
            else: # No previous search term, nothing to do
                self.state.set_status_message("No search term for F3/Ctrl+R. Use Ctrl+F first.")
            return

        num_results = len(self.state.search_results)
        new_idx = (self.state.current_search_result_idx + direction + num_results) % num_results
        self._navigate_to_match(new_idx)

    def _handle_find_input_key(self, stdscr: 'curses._CursesWindow', key: int) -> bool:
        """Handles key presses when in find_input_active mode. Returns True to exit app."""
        if key == curses.KEY_ENTER or key == 10 or key == 13:
            self._execute_search()
        elif key == curses.KEY_BACKSPACE or key == 127 or key == curses.ascii.BS:
            self.state.search_term = self.state.search_term[:-1]
        elif key == curses.ascii.ESC: # Escape
            self._exit_find_mode(clear_status=True)
            self.state.set_status_message("Find cancelled.") # Provide feedback
        elif curses.ascii.isprint(key):
            self.state.search_term += chr(key)
        # Other keys (arrows, etc.) are ignored in find input mode for now.
        return False # Do not exit app

    def process_key(self, stdscr: 'curses._CursesWindow', key: int) -> bool:
        """
        Processes a single key press.
        Returns True if the application should exit, False otherwise.
        """
        # Handle quit confirmation first
        if self.pending_quit_confirmation:
            if key == ord('y') or key == ord('Y'):
                return True # Confirm quit
            self.pending_quit_confirmation = False
            self.state.clear_status_message() # Clear "Quit anyway?"
            return False # Cancel quit

        # Handle find input mode if active
        if self.state.find_input_active:
            return self._handle_find_input_key(stdscr, key)

        # Clear general status messages, unless a find operation will set one
        # This needs to be nuanced. If find is active, its status should persist.
        # If a non-find key is pressed, find should exit and status cleared.
        
        action_exits_find_implicitly = False

        # --- Find Mode Operations (Not find_input_active) ---
        CTRL_F = 6 # ASCII STX
        CTRL_R = 18 # ASCII DC2 (Often Ctrl+R)

        if key == CTRL_F:
            self._start_find_input_mode(reuse_term=True)
            return False # Handled
        
        if self.state.is_finding: # Passive find mode (navigating results)
            if key == curses.KEY_F3:
                self._find_next_or_previous(1)
                return False # Handled
            elif key == CTRL_R: # Placeholder for Shift+F3 (Find Previous)
                self._find_next_or_previous(-1)
                return False # Handled
            elif key == curses.ascii.ESC:
                self._exit_find_mode(clear_status=True)
                self.state.set_status_message("Find exited.")
                return False # Handled
            else:
                # Any other key while passively finding exits find mode.
                action_exits_find_implicitly = True
        
        # If an action implies exiting find mode, do it now before processing the action.
        if action_exits_find_implicitly:
            self._exit_find_mode(clear_status=True) # Clear find status as we are moving away

        # Clear general status messages if no find operation just occurred and set one
        # And if we are not currently in a find state (it would have its own status)
        if not self.state.is_finding and not self.state.find_input_active:
             # Only clear if it's not a pending quit message
            if not self.pending_quit_confirmation:
                 self.state.clear_status_message()


        # --- Standard Editor Operations ---
        # Navigation
        if key == curses.KEY_UP: self._move_cursor(dy=-1)
        elif key == curses.KEY_DOWN: self._move_cursor(dy=1)
        elif key == curses.KEY_LEFT: self._move_cursor(dx=-1)
        elif key == curses.KEY_RIGHT: self._move_cursor(dx=1)
        elif key == curses.KEY_HOME: self.state.cursor_x = 0
        elif key == curses.KEY_END: self.state.cursor_x = self.buffer.get_line_length(self.state.cursor_y)
        elif key == curses.KEY_PPAGE: self._move_page(direction=-1)
        elif key == curses.KEY_NPAGE: self._move_page(direction=1)
        
        # Editing
        elif key == curses.KEY_BACKSPACE or key == 127 or key == curses.ascii.BS:
            self._handle_backspace()
        elif key == curses.KEY_DC: # Delete key
            self._handle_delete()
        elif key == curses.KEY_ENTER or key == 10 or key == 13:
            self._handle_enter()
        elif key == ord('\t') or key == 9: # Tab key
            self._handle_tab()
        elif curses.ascii.isprint(key):
            self.buffer.insert_char(self.state.cursor_y, self.state.cursor_x, chr(key))
            self.state.cursor_x += 1
        
        # Commands
        elif key == 19: # Ctrl+S (ASCII for Save)
            self._save_file(stdscr)
        elif key == 17: # Ctrl+Q (ASCII for Quit)
            if self.buffer.text_changed:
                self.state.set_status_message("Unsaved changes! Quit anyway? (y/n)", is_error=True)
                self.pending_quit_confirmation = True
            else:
                return True # Quit immediately

        elif key == curses.KEY_RESIZE:
             pass # Handled by EditorApplication main loop re-getting dimensions

        elif key == curses.KEY_MOUSE:
            self._handle_mouse_event()
        
        # After any action, ensure cursor is valid and viewport is updated
        self.state.clamp_cursor(self.buffer)
        self.state.scroll_viewport_to_cursor()
        return False # Do not exit by default

    def _move_cursor(self, dx: int = 0, dy: int = 0) -> None:
        """Helper for cursor movement keys."""
        if dx != 0:
            if dx < 0 and self.state.cursor_x == 0 and self.state.cursor_y > 0: # Left at line start
                self.state.cursor_y -= 1
                self.state.cursor_x = self.buffer.get_line_length(self.state.cursor_y)
            elif dx > 0 and self.state.cursor_x == self.buffer.get_line_length(self.state.cursor_y) and \
                 self.state.cursor_y < self.buffer.get_line_count() - 1: # Right at line end
                self.state.cursor_y += 1
                self.state.cursor_x = 0
            else:
                self.state.cursor_x += dx
        
        if dy != 0:
            self.state.cursor_y += dy

    def _move_page(self, direction: int) -> None:
        """Helper for PageUp/PageDown."""
        page_amount = self.state.text_area_height
        self.state.cursor_y += direction * page_amount
        self.state.top_line += direction * page_amount
        
        # Clamp top_line
        self.state.top_line = max(0, min(self.state.top_line, self.buffer.get_line_count() - self.state.text_area_height))
        if self.state.top_line < 0: self.state.top_line = 0


    def _handle_backspace(self) -> None:
        """Handles backspace key press."""
        original_cursor_y = self.state.cursor_y
        original_cursor_x = self.state.cursor_x

        self.buffer.delete_char(self.state.cursor_y, self.state.cursor_x)
        
        if self.state.cursor_x > 0:
            self.state.cursor_x -= 1
        elif self.state.cursor_y > 0 : # Merged with previous line
            self.state.cursor_y -=1
            self.state.cursor_x = self.buffer.get_line_length(self.state.cursor_y)
        # Ensure cursor_y has not changed if it was already 0 and no merge happened
        elif original_cursor_x == 0 and original_cursor_y == self.state.cursor_y: 
            pass # No change if at (0,0) and backspace pressed

    def _handle_delete(self) -> None:
        """Handles delete key press."""
        self.buffer.delete_forward_char(self.state.cursor_y, self.state.cursor_x)
        # Cursor position does not change unless a line merge happened (handled by buffer method)
        # or if at end of file. Clamp cursor will fix it.

    def _handle_enter(self) -> None:
        """Handles enter key press."""
        self.buffer.split_line(self.state.cursor_y, self.state.cursor_x)
        self.state.cursor_y += 1
        self.state.cursor_x = self.buffer.get_line(self.state.cursor_y).index(self.buffer.get_line(self.state.cursor_y).lstrip()) \
                                if self.buffer.get_line(self.state.cursor_y).strip() else 0 # To start of indent
        self.state.cursor_x = len(self.buffer.get_line(self.state.cursor_y)) - len(self.buffer.get_line(self.state.cursor_y).lstrip())


    def _handle_tab(self) -> None:
        """Handles tab key press."""
        tab_str = " " * EditorConstants.TAB_WIDTH
        self.buffer.insert_char(self.state.cursor_y, self.state.cursor_x, tab_str)
        self.state.cursor_x += len(tab_str)
        
    def _save_file(self, stdscr: 'curses._CursesWindow') -> None:
        """Handles file saving."""
        success, msg = self.buffer.save_file()
        if success:
            self.state.set_status_message("File saved successfully!")
        else:
            self.state.set_status_message(f"Error saving: {msg}", is_error=True)
        # The message will be displayed by the view on the next render.
        # For immediate feedback of "File saved!", one might force a temporary render here.
        # However, the current design clears status messages on next input, so this is okay.

    def _handle_mouse_event(self) -> None:
        """Handles mouse click events."""
        try:
            _, mx, my, _, bstate = curses.getmouse()
            if bstate & curses.BUTTON1_CLICKED:
                if 0 <= my < self.state.text_area_height: # Click in text area
                    target_buffer_y = self.state.top_line + my
                    if 0 <= target_buffer_y < self.buffer.get_line_count():
                        self.state.cursor_y = target_buffer_y
                        
                        effective_mx_in_text_area = mx - EditorConstants.LINE_NUMBER_AREA_WIDTH
                        if effective_mx_in_text_area < 0: # Click in line number area
                            self.state.cursor_x = 0
                        else:
                            self.state.cursor_x = self.state.view_start_col + effective_mx_in_text_area
                        
                        self.state.clamp_cursor(self.buffer) # Ensure x is valid for the new line
        except curses.error:
            pass # Ignore mouse errors


class EditorApplication:
    """Main application class orchestrating all editor components."""
    def __init__(self, stdscr: 'curses._CursesWindow', filepath: Optional[str]) -> None:
        self.stdscr = stdscr
        self.filepath = filepath

        self.color_manager = ColorManager() # Initializes colors
        self.syntax_highlighter = SyntaxHighlighter(self.color_manager)
        self.buffer = Buffer(filepath)
        self.state = EditorState()
        self.view = EditorView(self.color_manager, self.syntax_highlighter)
        self.input_handler = InputHandler(self.buffer, self.state, self.view)
        
        self._configure_curses()

    def _configure_curses(self) -> None:
        """Basic curses configurations."""
        curses.curs_set(1)  # Show cursor
        self.stdscr.nodelay(False)  # Blocking input
        # Enter raw mode to handle Ctrl+S, Ctrl+Q, Ctrl+C etc. directly
        # curses.wrapper puts terminal in cbreak mode, raw() is more fundamental.
        curses.raw()
        self.stdscr.keypad(True) # Ensure special keys like arrows are processed
        curses.mousemask(curses.ALL_MOUSE_EVENTS | curses.REPORT_MOUSE_POSITION)
        # `start_color` and `use_default_colors` are called in ColorManager

    def run(self) -> None:
        """Runs the main editor loop."""
        while True:
            # Update screen dimensions and recalculate view properties
            max_y, max_x = self.stdscr.getmaxyx()
            self.state.update_screen_dimensions(max_y, max_x)

            # Ensure cursor and viewport are valid after potential resize or operations
            self.state.clamp_cursor(self.buffer)
            self.state.scroll_viewport_to_cursor() # Adjusts viewport based on cursor & screen

            # Render screen
            self.view.render_screen(self.stdscr, self.buffer, self.state)
            
            try:
                key = self.stdscr.getch()
            except curses.error: # Interrupted system call (e.g. window resize)
                continue 
            except KeyboardInterrupt: # Fallback, less likely for Ctrl+C in raw mode
                key = 17 # Simulate Ctrl+Q (DC1)
            
            if key == 3: # In raw mode, Ctrl+C often sends ETX (ASCII 3)
                key = 17 # Map to our standard Ctrl+Q keycode

            if self.input_handler.process_key(self.stdscr, key):
                break # Exit loop if process_key signals to quit


def main_curses_wrapper(stdscr: 'curses._CursesWindow', filepath: Optional[str]) -> None:
    """
    The core curses application logic. This function is called BY curses.wrapper.
    Assumes curses is initialized. The calling wrapper should handle locale.
    """
    app = EditorApplication(stdscr, filepath)
    app.run()

def launch_editor_cli(filepath: Optional[str]) -> None:
    """
    Entry point for launching the editor from an external Python script (like tinycoder).
    Handles locale setup before invoking curses.wrapper.
    """

    try:
        # Set locale to the user's preference. Essential for curses to handle
        # character encoding correctly, especially for input and display of non-ASCII.
        locale.setlocale(locale.LC_ALL, '')
    except locale.Error:
        # If locale cannot be set, print a warning to stderr
        print("Warning: Could not set system locale for the editor. Unicode characters may not display/input correctly.", file=os.sys.stderr)
    except Exception as e:
        # Catch any other unexpected error during locale setup
        print(f"Warning: An unexpected error ({type(e).__name__}) occurred while setting locale for the editor: {e}", file=os.sys.stderr)

    curses.wrapper(main_curses_wrapper, filepath)
    
if __name__ == "__main__":
    # This block is for running editor.py directly as a script
    _initial_filepath: Optional[str] = None
    if len(os.sys.argv) > 1:
        _initial_filepath = os.sys.argv[1]
    else:
        # If no file specified, could default to this source file for demo
        _initial_filepath = __file__ 

    try:
        launch_editor_cli(_initial_filepath) # Use the new entry point
    except Exception as e:
        # This print is outside curses, so it should be visible
        print("An error occurred running the editor standalone:")
        print(f"{type(e).__name__}: {e}")
        traceback.print_exc()
