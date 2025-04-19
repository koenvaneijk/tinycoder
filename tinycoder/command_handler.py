import re
from typing import TYPE_CHECKING, Callable, Optional, Tuple, Set

if TYPE_CHECKING:
    from tinycoder.file_manager import FileManager
    from tinycoder.git_manager import GitManager
    # from tinycoder.history import ChatHistoryManager # Assuming this might exist later

# Define CommandHandlerReturn tuple for clarity
# status: bool (False to exit, True to continue)
# prompt: Optional[str] (A prompt string if the command included one, e.g., /ask prompt)
CommandHandlerReturn = Tuple[bool, Optional[str]]

class CommandHandler:
    """Handles parsing and execution of slash commands."""

    def __init__(
        self,
        file_manager: 'FileManager',
        git_manager: 'GitManager',
        # history_manager: 'ChatHistoryManager', # Use functions for now
        clear_history_func: Callable[[], None],
        write_history_func: Callable[[str, str], None],
        print_info: Callable[[str], None],
        print_error: Callable[[str], None],
        get_mode: Callable[[], str],
        set_mode: Callable[[str], None],
        git_commit_func: Callable[[], None],
        git_undo_func: Callable[[], None],
        app_name: str, # Pass APP_NAME for messages
    ):
        self.file_manager = file_manager
        self.git_manager = git_manager
        # self.history_manager = history_manager
        self.clear_history_func = clear_history_func
        self.write_history_func = write_history_func
        self.print_info = print_info
        self.print_error = print_error
        self.get_mode = get_mode
        self.set_mode = set_mode
        self.git_commit_func = git_commit_func
        self.git_undo_func = git_undo_func
        self.app_name = app_name


    def handle(self, inp: str) -> CommandHandlerReturn:
        """
        Parses and handles a slash command.

        Returns:
            Tuple[bool, Optional[str]]:
                (False, None) if the command signals to exit.
                (True, str) if the command includes a prompt to be processed immediately (e.g., /ask prompt).
                (True, None) if the command was handled successfully and the main loop should continue.
        """
        parts = inp.strip().split(maxsplit=1)
        command = parts[0]
        args = parts[1].strip() if len(parts) > 1 else "" # Strip args here

        if command == "/add":
            filenames = re.findall(r"\"(.+?)\"|(\S+)", args) # Handle quoted filenames
            filenames = [name for sublist in filenames for name in sublist if name]
            if not filenames:
                 self.print_error("Usage: /add <file1> [\"file 2\"] ...")
            else:
                 for fname in filenames:
                      # Use FileManager; it prints errors/info internally
                      self.file_manager.add_file(fname)
                      # Write history entry here, as FileManager doesn't do it
                      # Need to resolve fname to the stored relative path for accurate history
                      abs_path = self.file_manager.get_abs_path(fname)
                      if abs_path:
                          rel_path = self.file_manager._get_rel_path(abs_path)
                          if rel_path in self.file_manager.get_files(): # Check if add succeeded
                               self.write_history_func("tool", f"Added {rel_path} to the chat.")
            return True, None # Continue loop

        elif command == "/drop":
            filenames = re.findall(r"\"(.+?)\"|(\S+)", args) # Handle quoted filenames
            filenames = [name for sublist in filenames for name in sublist if name] # Flatten list of tuples
            if not filenames:
                 self.print_error("Usage: /drop <file1> [\"file 2\"] ...")
            else:
                initial_fnames = set(self.file_manager.get_files()) # Copy before dropping
                for fname in filenames:
                      # Use FileManager; it prints errors/info internally
                      self.file_manager.drop_file(fname)
                # Write history for files actually dropped
                dropped_fnames = initial_fnames - self.file_manager.get_files()
                for fname in dropped_fnames: # fname here is the relative path
                     self.write_history_func("tool", f"Removed {fname} from the chat.")
            return True, None # Continue loop

        elif command == "/clear":
            # self.history_manager.clear() # If using history manager
            self.clear_history_func()
            self.print_info("Chat history cleared.")
            self.write_history_func("tool", "Chat history cleared.")
            return True, None # Continue loop

        elif command == "/reset":
            self.file_manager.fnames = set() # Reset FileManager's set directly
            # self.history_manager.clear() # If using history manager
            self.clear_history_func()
            self.print_info("Chat history and file list cleared.")
            self.write_history_func("tool", "Chat history and file list cleared.")
            return True, None # Continue loop

        elif command == "/commit":
            self.git_commit_func() # Call the function passed from App
            return True, None # Continue loop

        elif command == "/undo":
             self.git_undo_func() # Call the function passed from App
             return True, None # Continue loop

        elif command == "/ask":
             self.set_mode("ask")
             self.print_info("Switched to ASK mode. I will answer questions but not edit files.")
             if args: # If user provided a prompt with /ask
                 return True, args # Return True to continue, and the prompt string
             else:
                 return True, None # Continue loop, mode is changed

        elif command == "/code":
             self.set_mode("code")
             self.print_info("Switched to CODE mode. I will try to edit files.")
             if args: # If user provided a prompt with /code
                 return True, args # Return True to continue, and the prompt string
             else:
                 return True, None # Continue loop, mode is changed

        elif command == "/files":
            current_fnames = self.file_manager.get_files()
            if not current_fnames:
                 self.print_info("No files are currently added to the chat.")
            else:
                 self.print_info("Files in chat:")
                 for fname in sorted(list(current_fnames)):
                      print(f"- {fname}") # Use standard print for clean list
            return True, None # Continue loop

        elif command == "/help":
             self.print_info(f"""Available commands:
  /add <file1> ["file 2"]...  Add file(s) to the chat context.
  /drop <file1> ["file 2"]... Remove file(s) from the chat context.
  /files                      List files currently in the chat.
  /clear                      Clear the chat history.
  /reset                      Clear chat history and drop all files.
  /commit                     Commit the current changes made by {self.app_name}.
  /undo                       Undo the last commit made by {self.app_name}.
  /ask [question]             Switch to ASK mode (answer questions, no edits) or ask a question directly.
  /code [instruction]         Switch to CODE mode (make edits) or give an instruction directly.
  /help                       Show this help message.
  /exit or /quit              Exit the application.""")
             return True, None # Continue loop

        elif command in ["/exit", "/quit"]:
            return False, None # Signal to exit main loop

        else:
            self.print_error(f"Unknown command: {command}. Try /help.")
            return True, None # Continue loop after showing error
