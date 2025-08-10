import time
from prompt_toolkit import print_formatted_text

class Spinner:
    """
    A simple, non-threaded terminal message displayer for synchronous operations,
    integrated with prompt_toolkit's printing system to avoid UI glitches.

    Usage:
        spinner = Spinner("Working...")
        spinner.start()
        # Do some synchronous work...
        time.sleep(2)
        spinner.stop()
    """
    def __init__(self, message: str = "Loading...", delay: float = 0.1):
        """
        Initializes the Spinner.

        Args:
            message (str): The message to display.
            delay (float): This is ignored in the non-threaded version but kept for compatibility.
        """
        self.message = message
        self._visible = False

    def start(self):
        """Displays the message using prompt_toolkit's printing function."""
        if self._visible:
            return
        # Use prompt_toolkit's print function but without a newline to keep it on the same line.
        print_formatted_text(self.message, end='')
        self._visible = True

    def stop(self):
        """Stops the spinner by erasing the message from the line using prompt_toolkit."""
        if not self._visible:
            return
        # Print carriage return and spaces to clear the line, without a newline.
        clear_line = '\r' + ' ' * len(self.message) + '\r'
        print_formatted_text(clear_line, end='')
        self._visible = False

    def __enter__(self):
        """Starts spinner when entering context manager."""
        self.start()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        """Stops spinner when exiting context manager."""
        self.stop()

# Example Usage:
if __name__ == "__main__":
    # This example won't work correctly standalone as it needs a prompt_toolkit app running.
    # It serves as a structural example.
    print("Starting example task...")
    with Spinner("Task in progress..."):
        time.sleep(3)
    print("\nTask finished.")
