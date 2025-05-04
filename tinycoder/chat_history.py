import os
import re
import logging
import datetime
from typing import List, Dict

# Default filename for the chat history
HISTORY_FILE: str = ".tinycoder.chat.history.md"

class ChatHistoryManager:
    """
    Manages the chat history, including loading from and saving to a markdown file.

    Provides methods to add messages, retrieve history, clear history, and save
    messages specifically for logging without affecting the LLM context.
    """

    def __init__(
        self,
        continue_chat: bool = False,
        history_filename: str = HISTORY_FILE,
    ):
        """
        Initializes the ChatHistoryManager.

        Args:
            continue_chat: If True, attempts to load existing chat history from
                           `history_filename`. If False, starts with an empty history.
            logger_instance: An optional custom logger instance. If None, uses
                             the module logger.
            history_filename: The path to the chat history file. Defaults to
                              `HISTORY_FILE`.
        """
        self.history: List[Dict[str, str]] = []
        self.logger: logging.Logger = logging.getLogger(__name__)
        self.history_filename: str = history_filename

        if continue_chat:
            self._load_history()
        else:
            # Clear only if not continuing and file exists, otherwise ensure clean slate
            if os.path.exists(self.history_filename):
                 self.clear() # Overwrite existing file for a fresh start
            else:
                 self.history.clear() # Just clear in-memory if file doesn't exist

    def _load_history(self) -> None:
        """
        Loads chat history from the markdown file using simplified parsing.

        Attempts to reconstruct the conversation history from the markdown file.
        The parsing is basic and might not perfectly capture all nuances of a
        complex conversation structure. It assumes messages are separated by
        specific markdown markers.

        Side Effects:
            Populates `self.history` with messages loaded from the file.
            Logs errors if the file cannot be read or parsed.
        """
        if not os.path.exists(self.history_filename):
            self.logger.info(f"History file not found: {self.history_filename}. Starting fresh.")
            return

        try:
            with open(self.history_filename, "r", encoding="utf-8") as f:
                content: str = f.read()

            # Simple parsing: Assume blocks separated by specific markers are messages.
            # This heuristic parsing might misinterpret complex markdown.
            potential_messages: List[str] = re.split(r"\n\n(?:#### |> )", content)
            current_role: str = "assistant"  # Assume first block after header is assistant

            for block in potential_messages:
                block = block.strip()
                # Skip empty blocks or the initial header line
                if not block or block.startswith(f"# {os.path.basename(self.history_filename)}"):
                    continue

                # Heuristic check for user input (lacks common non-user prefixes)
                # This logic is fragile and best-effort.
                is_user: bool = not block.startswith(
                    ("Assistant:", "Tool:", "Error:", "Info:", "Warning:", "> ", "#### ")
                )
                role: str = "user" if is_user else "assistant"

                # Crude role alternation if the simple check fails (e.g., two user msgs)
                if role == current_role:
                    role = "user" if current_role == "assistant" else "assistant"
                    self.logger.debug(f"Applied heuristic role alternation to: {role}")


                # Unescape markdown code fences potentially escaped during saving
                block_content: str = block.replace("\\```", "```")
                self.history.append({"role": role, "content": block_content})
                # Update expected role for the next block
                current_role = "user" if role == "assistant" else "assistant"

            self.logger.info(
                f"Loaded ~{len(self.history)} messages from {self.history_filename} "
                "(basic parsing)"
            )
        except FileNotFoundError:
             self.logger.warning(f"History file not found during load attempt: {self.history_filename}")
        except IOError as e:
            self.logger.error(f"Could not read history file {self.history_filename}: {e}")
        except Exception as e: # Catch other potential errors during parsing
            self.logger.error(
                f"Could not load or parse history file {self.history_filename}: {e}",
                exc_info=True # Include traceback for unexpected errors
            )


    def _append_to_file(self, role: str, content: str) -> None:
        """
        Appends a single message to the history markdown file.

        Formats the message with a simple prefix based on the role and escapes
        markdown code fences before writing.

        Args:
            role: The role of the message sender (e.g., 'user', 'assistant').
            content: The message content.

        Side Effects:
            Writes to the file specified by `self.history_filename`.
            Logs errors if writing fails.
        """
        try:
            # Determine prefix based on role for basic markdown structure
            prefix: str = ""
            if role == "user":
                prefix = "#### "
            elif role == "tool": # Or potentially other non-assistant/user roles
                 prefix = "> "
            # Assistant messages have no prefix in this format

            # Basic escaping of ``` to prevent breaking markdown structure
            content_md: str = content.replace("```", "\\```")

            # Ensure the directory exists before trying to write
            # Although usually it should exist if we loaded/cleared
            history_dir = os.path.dirname(self.history_filename)
            if history_dir: # Ensure not trying to create dir for root-level file
                 os.makedirs(history_dir, exist_ok=True)

            with open(self.history_filename, "a", encoding="utf-8") as f:
                f.write(f"{prefix}{content_md.strip()}\n\n")
        except IOError as e:
            self.logger.error(f"Could not write to history file {self.history_filename}: {e}")
        except Exception as e: # Catch other potential errors
             self.logger.error(
                f"Unexpected error writing to history file {self.history_filename}: {e}",
                exc_info=True
             )

    def add_message(self, role: str, content: str) -> None:
        """
        Adds a message to the in-memory history and appends it to the file.

        This is the standard way to record conversation turns that should be
        part of the LLM context.

        Args:
            role: The role of the message sender ('user', 'assistant').
            content: The message content.

        Side Effects:
            Modifies `self.history`.
            Calls `_append_to_file` to write to the history file.
        """
        message: Dict[str, str] = {"role": role, "content": content}
        self.history.append(message)
        self._append_to_file(role, content)

    def get_history(self) -> List[Dict[str, str]]:
        """
        Returns the current in-memory chat history.

        Returns:
            A list of dictionaries, where each dictionary represents a message
            with 'role' and 'content' keys.
        """
        return self.history

    def clear(self) -> None:
        """
        Clears the in-memory history and overwrites the history file with a header.

        Side Effects:
            Clears the `self.history` list.
            Overwrites the content of the file specified by `self.history_filename`.
            Logs errors if the file cannot be written.
        """
        self.history.clear()
        self.logger.debug("Cleared in-memory chat history.")

        try:
            # Ensure directory exists before writing
            history_dir = os.path.dirname(self.history_filename)
            if history_dir:
                os.makedirs(history_dir, exist_ok=True)

            with open(self.history_filename, "w", encoding="utf-8") as f:
                now: datetime.datetime = datetime.datetime.now()
                timestamp: str = now.strftime("%Y-%m-%d %H:%M:%S")
                # Use basename for the header in case the path is long
                file_basename = os.path.basename(self.history_filename)
                f.write(f"# {file_basename} cleared at {timestamp}\n\n")
            self.logger.debug(f"Overwrote history file: {self.history_filename}")
        except IOError as e:
            self.logger.error(f"Could not clear/overwrite history file {self.history_filename}: {e}")
        except Exception as e:
             self.logger.error(
                f"Unexpected error clearing history file {self.history_filename}: {e}",
                exc_info=True
            )

    def save_message_to_file_only(self, role: str, content: str) -> None:
        """
        Appends a message only to the history file, not the in-memory list.

        Useful for recording events (like commands or tool usage) that should
        be logged in the history file but not sent as part of the context to
        the language model.

        Args:
            role: The role or type of the event ('user', 'tool', 'info', 'system').
            content: The content describing the event or message.

        Side Effects:
            Calls `_append_to_file` to write to the history file.
        """
        self.logger.debug(f"Saving message to file only (role: {role})")
        self._append_to_file(role, content)
