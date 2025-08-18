import sys
import threading
import time
from itertools import cycle

class Spinner:
    """A simple terminal spinner that runs in a separate thread."""
    def __init__(self, message: str = "Loading...", delay: float = 0.1):
        self.spinner = cycle(['-', '/', '|', '\\'])
        self.delay = delay
        self.message = message
        self.running = False
        self.spinner_thread = None

    def start(self):
        """Starts the spinner in a separate thread."""
        self.running = True
        self.spinner_thread = threading.Thread(target=self._spin)
        self.spinner_thread.daemon = True
        self.spinner_thread.start()

    def _spin(self):
        """The private method that runs the spinner loop."""
        while self.running:
            # Use \r to return to the beginning of the line
            sys.stdout.write(f"\r{self.message} {next(self.spinner)}")
            sys.stdout.flush()
            time.sleep(self.delay)

    def stop(self):
        """Stops the spinner and cleans up the line."""
        if not self.running:
            return
            
        self.running = False
        if self.spinner_thread:
            self.spinner_thread.join(timeout=1.0)
        
        # Clear the line by writing spaces and returning to the beginning
        sys.stdout.write('\r' + ' ' * (len(self.message) + 2) + '\r')
        sys.stdout.flush()

    def __enter__(self):
        """Starts spinner when entering context manager."""
        self.start()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        """Stops spinner when exiting context manager."""
        self.stop()

# Example Usage:
if __name__ == "__main__":
    print("This spinner is a simple threaded CLI spinner.")
    with Spinner("Processing data..."):
        time.sleep(5)
    print("Done!")

    # Another example
    spinner = Spinner("Thinking hard...", 0.2)
    spinner.start()
    time.sleep(3)
    spinner.stop()
    print("Finished thinking.")
    