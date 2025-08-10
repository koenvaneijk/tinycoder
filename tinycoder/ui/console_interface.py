def ring_bell():
    """Ring the terminal bell."""
    print("\a", end="", flush=True)


def prompt_user_input(prompt: str) -> str:
    """
    Rings the terminal bell, displays a prompt, and returns user input.
    This is a simple wrapper around `input()` for confirmation dialogs
    that don't need the complexity of a `PromptSession`.
    """
    ring_bell()
    try:
        # Prompt the user and wait for input
        return input(prompt)
    except (KeyboardInterrupt, EOFError):
        # Handle cases where the user cancels the input (e.g., Ctrl+C, Ctrl+D)
        print()  # Add a newline for clean output
        return ""  # Return an empty string to signify cancellation
