import os
import re
from typing import List, Dict, Callable

# --- Configuration ---
HISTORY_FILE = ".tinycoder.chat.history.md"

class ChatHistoryManager:
    """Manages the chat history, including loading and saving."""

    def __init__(self, print_info: Callable[[str], None], print_error: Callable[[str], None]):
        """
        Initializes the ChatHistoryManager.

        Args:
            print_info: Function to print informational messages.
            print_error: Function to print error messages.
        """
        self.history: List[Dict[str, str]] = []
        self._print_info = print_info
        self._print_error = print_error
        # self._load_history() # Load history on initialization

    def _load_history(self):
        """Loads chat history from the markdown file (Simplified)."""
        if not os.path.exists(HISTORY_FILE):
            return

        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                content = f.read()
            # Super simple parsing: Assume blocks separated by #### or > are messages
            # This won't perfectly reconstruct Coder's complex history but gives a basic load
            potential_messages = re.split(r'\n\n(?:#### |> )', content)
            current_role = "assistant" # Assume first non-meta block is assistant
            for block in potential_messages:
                block = block.strip()
                if not block or block.startswith("# coder chat started at"):
                    continue
                # Basic check if it looks like user input (starts without special prefix)
                # This is fragile.
                is_user = not block.startswith(("Assistant:", "Tool:", "Error:", "Info:", "Warning:", "> ", "#### "))
                role = "user" if is_user else "assistant"

                # Crude role alternation if the simple check fails
                if role == current_role :
                    role = "user" if current_role == "assistant" else "assistant"

                # Unescape markdown code fences
                block_content = block.replace("\\```", "```")
                self.history.append({"role": role, "content": block_content})
                current_role = "user" if role == "assistant" else "assistant"

            self._print_info(f"Loaded ~{len(self.history)} messages from {HISTORY_FILE} (basic parsing)")
        except Exception as e:
            self._print_error(f"Could not load/parse history file {HISTORY_FILE}: {e}")

    def _append_to_file(self, role: str, content: str):
        """Appends a single message to the history markdown file."""
        try:
            with open(HISTORY_FILE, "a", encoding="utf-8") as f:
                prefix = "> " if role == "tool" else "#### " if role == "user" else ""
                # Basic escaping of ``` for markdown history
                content_md = content.replace("```", "\\```")
                f.write(f"{prefix}{content_md.strip()}\n\n")
        except Exception as e:
            self._print_error(f"Could not write to history file {HISTORY_FILE}: {e}")

    def add_message(self, role: str, content: str):
        """Adds a message to the in-memory history and appends it to the file."""
        self.history.append({"role": role, "content": content})
        self._append_to_file(role, content)

    def get_history(self) -> List[Dict[str, str]]:
        """Returns the current in-memory chat history."""
        return self.history

    def clear(self):
        """Clears the in-memory history and optionally the history file."""
        self.history.clear()
        # Optionally, clear the file as well, or handle it differently (e.g., backup)
        try:
            # Simple clear: overwrite the file. Consider backup/rename instead.
            with open(HISTORY_FILE, "w", encoding="utf-8") as f:
                f.write(f"# {HISTORY_FILE} cleared at {__import__('datetime').datetime.now()}\n\n")
            self._print_info(f"Cleared chat history and file {HISTORY_FILE}.")
        except Exception as e:
            self._print_error(f"Could not clear history file {HISTORY_FILE}: {e}")

    def save_message_to_file_only(self, role: str, content: str):
        """
        Appends a message only to the history file, not the in-memory list.
        Useful for recording events like '/undo' without adding them to the LLM context.
        """
        self._append_to_file(role, content)
