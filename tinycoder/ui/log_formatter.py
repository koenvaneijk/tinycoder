import logging
import sys
import os
from typing import Dict, Optional

# ANSI escape codes
# Check if NO_COLOR environment variable is set
_NO_COLOR = os.environ.get("NO_COLOR") is not None

# Basic foreground colors
COLORS = {
    "BLACK": "\033[30m",
    "RED": "\033[31m",
    "GREEN": "\033[32m",
    "YELLOW": "\033[33m",
    "BLUE": "\033[34m",
    "MAGENTA": "\033[35m",
    "CYAN": "\033[36m",
    "WHITE": "\033[37m",
    "GREY": "\033[90m",  # Bright Black often appears as Grey
}

# Bright foreground colors
BRIGHT_COLORS = {
    "BRIGHT_BLACK": "\033[90m",
    "BRIGHT_RED": "\033[91m",
    "BRIGHT_GREEN": "\033[92m",
    "BRIGHT_YELLOW": "\033[93m",
    "BRIGHT_BLUE": "\033[94m",
    "BRIGHT_MAGENTA": "\033[95m",
    "BRIGHT_CYAN": "\033[96m",
    "BRIGHT_WHITE": "\033[97m",
}

# Standard background colors
BG_COLORS = {
    "BLACK_BG": "\033[40m",
    "RED_BG": "\033[41m",
    "GREEN_BG": "\033[42m",
    "YELLOW_BG": "\033[43m",
    "BLUE_BG": "\033[44m",
    "MAGENTA_BG": "\033[45m",
    "CYAN_BG": "\033[46m",
    "WHITE_BG": "\033[47m",
    "GREY_BG": "\033[100m", # Bright Black background
}

# Bright background colors
BRIGHT_BG_COLORS = {
    "BRIGHT_BLACK_BG": "\033[100m",
    "BRIGHT_RED_BG": "\033[101m",
    "BRIGHT_GREEN_BG": "\033[102m",
    "BRIGHT_YELLOW_BG": "\033[103m",
    "BRIGHT_BLUE_BG": "\033[104m",
    "BRIGHT_MAGENTA_BG": "\033[105m",
    "BRIGHT_CYAN_BG": "\033[106m",
    "BRIGHT_WHITE_BG": "\033[107m",
}

# Styles
STYLES = {
    "BOLD": "\033[1m",
    "DIM": "\033[2m",
    "ITALIC": "\033[3m",
    "UNDERLINE": "\033[4m",
    "BLINK": "\033[5m",  # Often not supported
    "REVERSE": "\033[7m",
    "HIDDEN": "\033[8m",
}

# Reset code
RESET = "\033[0m"


class ColorLogFormatter(logging.Formatter):
    """
    A logging formatter that adds ANSI color and style codes based on log level.

    Automatically disables color if output is not a TTY or NO_COLOR is set.

    Usage:
        formatter = ColorLogFormatter(
            fmt="%(levelname)s:%(name)s:%(message)s", # Default format
            level_formats={
                logging.INFO: f"{COLORS['GREEN']}%(message)s{RESET}",
                logging.WARNING: f"{STYLES['BOLD']}{COLORS['YELLOW']}WARNING:{RESET} %(message)s",
                # Add other levels as needed
            },
            use_color=None # Auto-detect TTY if None
        )
    """

    def __init__(
        self,
        fmt: str = "%(levelname)s:%(name)s:%(message)s",
        datefmt: Optional[str] = None,
        style: str = '%',
        validate: bool = True,
        *,
        defaults: Optional[Dict] = None,
        level_formats: Optional[Dict[int, str]] = None,
        use_color: Optional[bool] = None
    ):
        """
        Initializes the formatter.

        Args:
            fmt: The default format string used if a level-specific format is not found.
            datefmt: The date format string passed to the base Formatter.
            style: The formatting style ('%', '{', '$') passed to the base Formatter.
            validate: Whether to validate the format string (passed to base Formatter).
            defaults: Default values for record attributes (passed to base Formatter).
            level_formats: A dictionary mapping logging levels (e.g., logging.INFO)
                           to specific format strings for those levels. ANSI codes
                           can be embedded here.
            use_color: Force color on/off. If None (default), auto-detect based on TTY
                       and NO_COLOR environment variable.
        """
        # Initialize the base Formatter. We don't pass fmt here initially,
        # as the format method will select the correct format string later.
        super().__init__(fmt=None, datefmt=datefmt, style=style, validate=False, defaults=defaults)

        self.default_fmt = fmt
        self.level_formats = level_formats or {}
        self.style = style
        self.datefmt = datefmt
        self.validate = validate
        self.defaults = defaults

        # Determine if color should be used
        if use_color is False or _NO_COLOR:
            self._use_color = False
        elif use_color is True:
            self._use_color = True
        else:
            # Auto-detect: Check if standard output is a TTY
            # Note: Handlers might write to stderr, but stdout is a common check.
            self._use_color = sys.stdout.isatty()

        # Create actual Formatter instances for each level format for efficiency
        self._formatters: Dict[int, logging.Formatter] = {}
        if self._use_color:
            # Create formatters using the provided level formats
            for level, fmt_str in self.level_formats.items():
                self._formatters[level] = logging.Formatter(
                    fmt=fmt_str, datefmt=datefmt, style=style, validate=validate, defaults=defaults
                )
            # Create a formatter for the default format (colored)
            self._formatters['default'] = logging.Formatter(
                fmt=self.default_fmt, datefmt=datefmt, style=style, validate=validate, defaults=defaults
            )
        else:
            # Create plain formatters (strip potential ANSI codes - basic approach)
            # A more robust approach might involve regex to remove all ANSI codes
            def _strip_ansi(s: str) -> str:
                import re
                # Basic ANSI code removal (might need refinement for complex cases)
                return re.sub(r'\033\[[0-9;]*m', '', s)

            for level, fmt_str in self.level_formats.items():
                plain_fmt = _strip_ansi(fmt_str)
                self._formatters[level] = logging.Formatter(
                    fmt=plain_fmt, datefmt=datefmt, style=style, validate=validate, defaults=defaults
                )
            # Create a formatter for the default format (plain)
            plain_default_fmt = _strip_ansi(self.default_fmt)
            self._formatters['default'] = logging.Formatter(
                fmt=plain_default_fmt, datefmt=datefmt, style=style, validate=validate, defaults=defaults
            )


    def format(self, record: logging.LogRecord) -> str:
        """
        Formats the specified record using the appropriate level-specific formatter.

        Args:
            record: The log record to format.

        Returns:
            The formatted log string.
        """
        # Get the formatter for the specific level, or the default one
        formatter = self._formatters.get(record.levelno, self._formatters['default'])

        # Let the chosen formatter do the actual formatting
        return formatter.format(record)