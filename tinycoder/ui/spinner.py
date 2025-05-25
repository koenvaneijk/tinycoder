import time
import itertools
import sys
import threading


class Spinner:
    """
    A simple terminal spinner class using threading.

    Usage:
        spinner = Spinner("Working...")
        spinner.start()
        # Do some work...
        time.sleep(5)
        spinner.stop()
        print("Done!")
    """

    def __init__(self, message: str = "Loading...", delay: float = 0.1):
        """
        Initializes the Spinner.

        Args:
            message (str): The message to display before the spinner.
            delay (float): The delay between spinner character updates in seconds.
        """
        # Use Braille patterns for a smoother spinner
        self.spinner = itertools.cycle(
            ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"]
        )
        self.delay = delay
        self.message = message
        self._running = False
        self._thread = None

    def _spin(self):
        """The actual spinning loop."""
        while self._running:
            char = next(self.spinner)
            # Write message, spinner character, and flush
            sys.stdout.write(f"{self.message} {char}")
            sys.stdout.flush()
            time.sleep(self.delay)
            # Erase the line using carriage return and spaces
            sys.stdout.write("\r" + " " * (len(self.message) + 2) + "\r")

    def start(self):
        """Starts the spinner in a separate thread."""
        if self._thread is not None and self._thread.is_alive():
            return  # Already running

        self._running = True
        # Make the thread a daemon so it exits when the main program exits
        self._thread = threading.Thread(target=self._spin, daemon=True)
        self._thread.start()

    def stop(self):
        """Stops the spinner and cleans up the line."""
        if not self._running:
            return  # Already stopped

        self._running = False
        if self._thread:
            self._thread.join(
                timeout=self.delay * 2
            )  # Wait briefly for thread to finish

        # Clear the line completely after stopping (message + space + spinner char)
        sys.stdout.write("\r" + " " * (len(self.message) + 3) + "\r")
        sys.stdout.flush()
        self._thread = None  # Reset thread

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

    # Method 1: Manual start/stop
    spinner1 = Spinner("Task 1 running...")
    spinner1.start()
    try:
        # Simulate work
        time.sleep(3)
    finally:
        spinner1.stop()
    print("Task 1 finished.")

    print("-" * 20)

    # Method 2: Using context manager
    print("Starting Task 2...")
    with Spinner("Task 2 in progress..."):
        # Simulate work
        time.sleep(4)
    print("Task 2 finished.")

    print("-" * 20)

    print("Starting Task 3 (quick)...")
    with Spinner("Task 3...") as s:
        time.sleep(1)
        # You can update the message mid-spin if needed,
        # but it requires stopping and starting or a more complex setup.
        # For simplicity, this basic version doesn't support live message updates.
    print("Task 3 finished.")

    print("\nAll examples complete.")
