
def print_color(text: str, color: str) -> None:
    """Prints text in a specified ANSI color.

    Args:
        text: The string to print.
        color: The name of the color to use (e.g., "red", "green", "blue").
               If the color name is not recognized, default terminal color is used.
    """
    color_codes = {
        "red": "\033[91m",
        "green": "\033[92m",
        "yellow": "\033[93m",
        "blue": "\033[94m",
        "magenta": "\033[95m",
        "cyan": "\033[96m",
        "reset": "\033[0m",
    }
    code = color_codes.get(color.lower(), "")
    reset = color_codes["reset"]
    print(f"{code}{text}{reset}")
