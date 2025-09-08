"""Terminal-friendly session usage & cost summary."""

import re
from typing import Optional

from prompt_toolkit.formatted_text import FormattedText

from tinycoder.ui.log_formatter import STYLES, COLORS as FmtColors, RESET


def format_session_summary(
    model: str,
    input_tokens: int,
    output_tokens: int,
    cost_estimate: Optional[float],
) -> str:
    """
    Returns a boxed, coloured summary of token usage and cost.
    All ANSI styling is already embedded; callers can print it directly.
    """
    total_tokens = input_tokens + output_tokens
    if total_tokens == 0:
        return ""

    cost_line = ""
    if cost_estimate is not None:
        cost_line = f"Est. Cost:  {STYLES['BOLD']}{FmtColors['YELLOW']}${cost_estimate:.4f}{RESET}"
    else:
        cost_line = f"Est. Cost:  {FmtColors['GREY']}(price data unavailable for {model}){RESET}"

    title_line = f"{STYLES['BOLD']}Session Summary{RESET}"
    model_line = f"Model:      {STYLES['BOLD']}{FmtColors['GREEN']}{model}{RESET}"
    tokens_line = (
        f"Tokens:     {STYLES['BOLD']}{FmtColors['CYAN']}{total_tokens:,}{RESET} "
        f"{FmtColors['GREY']}(Input: {input_tokens:,} | Output: {output_tokens:,}){RESET}"
    )

    def visual_len(s: str) -> int:
        return len(re.sub(r"\x1b\[[0-9;]*m", "", s))

    width = 60
    border_char = "─"

    def pad(line: str) -> str:
        vis = visual_len(line)
        pad = " " * (width - vis)
        return f"{line}{pad}"

    def center(line: str) -> str:
        vis = visual_len(line)
        pad_total = width - vis
        left = " " * (pad_total // 2)
        right = " " * (pad_total - len(left))
        return f"{left}{line}{right}"

    summary = (
        f"\n{FmtColors['GREY']}┌{border_char * (width + 2)}┐{RESET}\n"
        f"{FmtColors['GREY']}│ {center(title_line)} {FmtColors['GREY']}│{RESET}\n"
        f"{FmtColors['GREY']}├{border_char * (width + 2)}┤{RESET}\n"
        f"{FmtColors['GREY']}│ {pad(model_line)} {FmtColors['GREY']}│{RESET}\n"
        f"{FmtColors['GREY']}│ {pad(tokens_line)} {FmtColors['GREY']}│{RESET}\n"
        f"{FmtColors['GREY']}│ {pad(cost_line)} {FmtColors['GREY']}│{RESET}\n"
        f"{FmtColors['GREY']}└{border_char * (width + 2)}┘{RESET}"
    )
    return summary