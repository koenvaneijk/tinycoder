#!/usr/bin/env python3

import sys
import os
import termios
import fcntl
import io
from typing import List, Optional

def inject_text(text_to_inject: str) -> bool:
    """
    Injects the given text into the controlling terminal's input buffer.

    Temporarily modifies terminal settings (disables echo) during injection.

    Args:
        text_to_inject: The string to inject.

    Returns:
        True if injection was successful, False otherwise. Prints errors
        to stderr on failure.
    """
    fd = -1
    original_settings = None

    try:
        # Get the file descriptor for standard input
        try:
            fd = sys.stdin.fileno()
        except io.UnsupportedOperation:
             print("Error: Standard input is not connected to a file descriptor (e.g., redirected).", file=sys.stderr)
             return False

        # Check if stdin is connected to a terminal
        if not os.isatty(fd):
            print("Error: Standard input is not a terminal. Injection via TIOCSTI is typically for ttys.", file=sys.stderr)
            return False

        original_settings = termios.tcgetattr(fd)
        new_settings = termios.tcgetattr(fd) # Get a fresh copy
        new_settings[3] &= ~termios.ECHO # Turn off echo (lflags, index 3)
        termios.tcsetattr(fd, termios.TCSANOW, new_settings)

        # Inject characters one by one
        for char in text_to_inject:
            # TIOCSTI expects bytes.
            char_bytes = char.encode('utf-8') # Assuming UTF-8 terminal
            for byte_val in char_bytes:
                 # ioctl expects a bytes-like object for the third argument when dealing
                 # with TIOCSTI. Packing the single byte into a bytes object.
                 packed_byte = bytes([byte_val])
                 fcntl.ioctl(fd, termios.TIOCSTI, packed_byte)
        
        # Optional: Inject a newline character to simulate pressing Enter.
        # fcntl.ioctl(fd, termios.TIOCSTI, b'\n')

        return True # Injection successful

    except termios.error as e:
        print(f"Terminal settings error: {e}", file=sys.stderr)
        return False
    except OSError as e:
        # This could catch ioctl errors if TIOCSTI is not supported or fd is invalid.
        print(f"OS error (ioctl failed or other OS issue): {e}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"An unexpected error occurred during injection: {e}", file=sys.stderr)
        return False
    finally:
        # Ensure terminal settings are restored
        if fd != -1 and original_settings is not None and os.isatty(fd): # Check isatty again before restoring
            try:
                termios.tcsetattr(fd, termios.TCSANOW, original_settings)
            except termios.error as e:
                 # Non-fatal error during cleanup, but print a warning
                 print(f"\nWarning: Failed to restore terminal settings: {e}", file=sys.stderr)
            except Exception as e:
                 # Non-fatal error during cleanup
                 print(f"\nWarning: Unexpected error restoring terminal settings: {e}", file=sys.stderr)


def main_ask(argv: Optional[List[str]] = None) -> None:
    """
    Entry point for the 'ask' command.
    Parses command-line arguments and calls the inject_text function.
    """
    if argv is None:
        argv = sys.argv

    if len(argv) < 2: # sys.argv[0] is the command name, need at least one more arg part
        script_name = os.path.basename(argv[0])
        print(f"Usage: {script_name} <text to inject>", file=sys.stderr)
        print(f"Example: {script_name} echo hello world", file=sys.stderr)
        sys.exit(1)

    # Join all arguments after the command name to form the text to inject.
    text_to_inject = " ".join(argv[1:])

    if not inject_text(text_to_inject):
        sys.exit(1) # Exit with error status if injection failed

    # Successfully injected, exit cleanly.
    # Optional: print("Text injected successfully.", file=sys.stderr)
    sys.exit(0)


if __name__ == "__main__":
    main_ask()