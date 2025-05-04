import os
import sys
import glob


def input_with_path_completion(prompt=""):
    """
    An input alternative with path completion using only standard libraries.
    Works on macOS, Linux, and Windows.

    Args:
        prompt: The prompt string to display before getting input

    Returns:
        The user's input string
    """
    # For Unix-like systems (macOS, Linux)
    if sys.platform != "win32":
        try:

            def complete(text, state):
                # text is the current input text (what user has typed so far)
                # Only the last part of the input is used for completion

                # When user types a path like "./t", text will be "./t"
                if state == 0:
                    # Get directory prefix and partial filename
                    dirname = os.path.dirname(text) if text else "."
                    if (
                        not dirname
                    ):  # Handle case when text is just a filename without path
                        dirname = "."
                    basename = os.path.basename(text)

                    # Get all matching files
                    if os.path.isdir(dirname):
                        try:
                            matches = []
                            # Look for files/directories that start with basename
                            for name in sorted(os.listdir(dirname)):
                                if name.startswith(basename):
                                    path = os.path.join(dirname, name)
                                    if os.path.isdir(path):
                                        matches.append(f"{path}{os.sep}")
                                    else:
                                        matches.append(path)
                            complete.matches = matches
                        except OSError:
                            complete.matches = []
                    else:
                        complete.matches = []

                # Return the state-th match
                try:
                    return complete.matches[state]
                except (IndexError, AttributeError):
                    return None

            return ""

        except ImportError:
            return input(prompt)

    # For Windows, use a custom implementation without external libraries
    else:
        import msvcrt

        print(prompt, end="", flush=True)

        # Initialize variables
        input_text = ""
        cursor_pos = 0
        last_key = None
        completions = []
        completion_index = 0
        completion_mode = False

        # Function to find matching paths
        def find_completions(text):
            if not text:
                pattern = "./*"
            else:
                pattern = text + "*"

            matches = sorted(glob.glob(pattern))
            return [p + os.sep if os.path.isdir(p) else p for p in matches]

        # Function to display the current text
        def refresh_display():
            # Clear current line
            sys.stdout.write("\r" + " " * (len(prompt) + len(input_text) + 10))
            sys.stdout.write("\r" + prompt + input_text)
            # Move cursor to the right position
            if cursor_pos < len(input_text):
                sys.stdout.write("\b" * (len(input_text) - cursor_pos))
            sys.stdout.flush()

        while True:
            # Get key press
            key = msvcrt.getch()

            # Handle backspace (8 is ASCII for backspace)
            if key == b"\x08":
                if cursor_pos > 0:
                    input_text = input_text[: cursor_pos - 1] + input_text[cursor_pos:]
                    cursor_pos -= 1
                    completion_mode = False

            # Handle Enter (13 is ASCII for carriage return)
            elif key == b"\r":
                sys.stdout.write("\n")
                break

            # Handle Tab (9 is ASCII for tab)
            elif key == b"\t":
                if not completion_mode:
                    # First tab press - find completions
                    completion_text = input_text[:cursor_pos]
                    completions = find_completions(completion_text)
                    completion_index = 0
                    completion_mode = True

                if completions:
                    # Get next completion
                    completion = completions[completion_index % len(completions)]
                    # Replace current text with completion
                    input_text = completion + input_text[cursor_pos:]
                    cursor_pos = len(completion)
                    # Move to next completion for next tab
                    completion_index += 1

            # Handle arrow keys and other special keys
            elif key == b"\xe0":
                # Arrow keys are two bytes, with the second byte determining direction
                direction = msvcrt.getch()
                if direction == b"K":  # Left arrow
                    if cursor_pos > 0:
                        cursor_pos -= 1
                elif direction == b"M":  # Right arrow
                    if cursor_pos < len(input_text):
                        cursor_pos += 1

                completion_mode = False

            # Handle regular characters
            elif key.isascii() and 32 <= ord(key) < 127:  # Printable ASCII
                char = key.decode("ascii")
                input_text = input_text[:cursor_pos] + char + input_text[cursor_pos:]
                cursor_pos += 1
                completion_mode = False

            # Refresh the display
            refresh_display()

            # Store the last key
            last_key = key

        return input_text


# Example usage
if __name__ == "__main__":
    user_input = input_with_path_completion("Enter a file path: ")
    print(f"You entered: {user_input}")
