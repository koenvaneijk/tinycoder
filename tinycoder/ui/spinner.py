import sys
import time

class Spinner:
    """
    A simple, non-threaded terminal message displayer for synchronous operations.
    It prints a message and provides a method to clear it.

    Usage:
        spinner = Spinner("Working...")
        spinner.start()
        # Do some synchronous work...
        time.sleep(2)
        spinner.stop()
        print("Done!")
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
        """Displays the message."""
        if self._visible:
            return
        sys.stdout.write(self.message)
        sys.stdout.flush()
        self._visible = True

    def stop(self):
        """Stops the spinner by erasing the message from the line."""
        if not self._visible:
            return
        # Erase the line using carriage return and spaces
        sys.stdout.write("\r" + " " * len(self.message) + "\r")
        sys.stdout.flush()
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
    print("Starting example task...")
    with Spinner("Task in progress..."):
        time.sleep(3)
    print("Task finished.")
