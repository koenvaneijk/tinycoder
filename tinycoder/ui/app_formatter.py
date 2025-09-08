"""UI formatting utilities for the main application."""

from typing import Dict, Any, Optional, Sequence
from prompt_toolkit.formatted_text import FormattedText
from tinycoder.ui.log_formatter import COLORS as FmtColors, RESET, STYLES


class AppFormatter:
    """Handles UI formatting logic for the main application."""
    
    def __init__(self):
        """Initialize the formatter with default styles."""
        self._toolbar_styles = {
            'class:bottom-toolbar.low': 'ansigreen',
            'class:bottom-toolbar.medium': 'ansiyellow', 
            'class:bottom-toolbar.high': 'ansired',
            'class:bottom-toolbar': 'ansibrightblack',
            'class:prompt.mode': 'ansicyan bold',
            'class:prompt.separator': 'ansibrightblack'
        }
    
    def get_toolbar_styles(self) -> Dict[str, str]:
        """Get the toolbar style definitions."""
        return self._toolbar_styles
    
    def format_bottom_toolbar(self, token_breakdown: Dict[str, Any]) -> str:
        """
        Generates the plain text for the bottom toolbar from cached token context.
        This function must be extremely fast as it's called on every redraw.
        """
        total = token_breakdown.get("total", 0)
        
        # Determine color based on total tokens
        total_color_class = 'class:bottom-toolbar.low'
        if total > 25000:
            total_color_class = 'class:bottom-toolbar.high'
        elif total > 15000:
            total_color_class = 'class:bottom-toolbar.medium'
        
        # Build plain string
        toolbar_str = (
            f"  Context: {total:,}"
            f" (Prompt: {token_breakdown.get('prompt_rules', 0):,} | "
            f"Map: {token_breakdown.get('repo_map', 0):,} | "
            f"Files: {token_breakdown.get('files', 0):,} | "
            f"History: {token_breakdown.get('history', 0):,})  "
        )
        return toolbar_str
    
    def format_mode_prompt(self, mode: str) -> FormattedText:
        """Format the mode indicator for the prompt."""
        mode_str = mode.upper()
        return FormattedText([
            ('class:prompt.mode', f'{mode_str}'),
            ('class:prompt.separator', ' > '),
        ])
    
    def format_file_list(self, files: list, color: str = 'CYAN') -> str:
        """Format a list of files with color coding."""
        color_code = FmtColors.get(color, '')
        return ', '.join(f"{color_code}{f}{RESET}" for f in files)
    
    def format_error_indices(self, indices: list) -> str:
        """Format error indices with bold red styling."""
        indices_str = ", ".join(map(str, sorted(indices)))
        return f"{STYLES['BOLD']}{FmtColors['RED']}{indices_str}{RESET}"
    
    def format_success_files(self, files: list) -> str:
        """Format successfully processed files with cyan color."""
        return self.format_file_list(files, 'CYAN')
    
    def format_warning_files(self, files: list) -> str:
        """Format warning files with yellow color."""
        return self.format_file_list(files, 'YELLOW')
    
    def format_error_files(self, files: list) -> str:
        """Format error files with red color."""
        return self.format_file_list(files, 'RED')
    
    def format_info_message(self, message: str, highlight: Optional[str] = None) -> str:
        """Format an info message with optional highlight."""
        if highlight:
            highlight_text = f"{FmtColors['BLUE']}{highlight}{RESET}"
            return message.replace(highlight, highlight_text)
        return message
    
    def format_status_message(self, enabled: bool, feature: str) -> str:
        """Format a status message for enabled/disabled features."""
        status_str = f"{FmtColors['GREEN']}enabled{RESET}" if enabled else f"{FmtColors['YELLOW']}disabled{RESET}"
        return f"{feature} is now {status_str}."

    # --- semantic helpers that hide colour literals from the rest of the code-base ---
    def format_filename(self, fname: str) -> str:
        """Return a file name styled for user output."""
        return f"{FmtColors['CYAN']}{fname}{RESET}"

    def format_filename_list(self, fnames: Sequence[str]) -> str:
        """Return a comma-separated list of file names styled for user output."""
        return ", ".join(self.format_filename(f) for f in fnames)

    def format_error(self, text: str) -> str:
        """Return error text styled for user output."""
        return f"{FmtColors['RED']}{text}{RESET}"

    def format_warning(self, text: str) -> str:
        """Return warning text styled for user output."""
        return f"{FmtColors['YELLOW']}{text}{RESET}"

    def format_success(self, text: str) -> str:
        """Return success text styled for user output."""
        return f"{FmtColors['GREEN']}{text}{RESET}"

    def format_info(self, text: str) -> str:
        """Return info text styled for user output."""
        return f"{FmtColors['BLUE']}{text}{RESET}"

    def format_bold(self, text: str) -> str:
        """Return bold text styled for user output."""
        return f"{STYLES['BOLD']}{text}{RESET}"