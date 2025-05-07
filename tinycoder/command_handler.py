import re
import logging
from typing import TYPE_CHECKING, Callable, Optional, Tuple

from tinycoder.test_runner import run_tests

if TYPE_CHECKING:
    from tinycoder.file_manager import FileManager
    from tinycoder.git_manager import GitManager

# Define CommandHandlerReturn tuple for clarity
CommandHandlerReturn = Tuple[bool, Optional[str]] # bool: continue_processing, Optional[str]: immediate_prompt_arg


class CommandHandler:
    """Handles parsing and execution of slash commands."""

    def __init__(
        self,
        file_manager: "FileManager",
        git_manager: "GitManager",
        clear_history_func: Callable[[], None],
        write_history_func: Callable[[str, str], None],
        get_mode: Callable[[], str],
        set_mode: Callable[[str], None],
        git_commit_func: Callable[[], None],
        git_undo_func: Callable[[], None],
        app_name: str,
        list_rules_func: Callable[[], str],
        enable_rule_func: Callable[[str], bool],
        disable_rule_func: Callable[[str], bool],
        toggle_repo_map_func: Callable[[bool], None],
        get_repo_map_str_func: Callable[[], str],
        suggest_files_func: Callable[[Optional[str]], None],
    ):
        """
        Initializes the CommandHandler.

        Args:
            file_manager: An instance of FileManager.
            git_manager: An instance of GitManager.
            clear_history_func: Function to clear chat history.
            write_history_func: Function to write to chat history.
            get_mode: Function to get current mode.
            set_mode: Function to set mode.
            git_commit_func: Function to commit changes.
            git_undo_func: Function to undo last commit.
            app_name: Name of the application.
            list_rules_func: Function to get formatted list of rules and status.
            enable_rule_func: Function to enable a rule by name.
            disable_rule_func: Function to disable a rule by name.
            toggle_repo_map_func: Function to toggle repo map inclusion in prompts.
            get_repo_map_str_func: Function to get the current repository map as a string.
            suggest_files_func: Function to ask LLM for file suggestions and handle adding them.
        """
        self.file_manager = file_manager
        self.git_manager = git_manager
        self.clear_history_func = clear_history_func
        self.write_history_func = write_history_func
        self.get_mode = get_mode
        self.set_mode = set_mode
        self.git_commit_func = git_commit_func
        self.git_undo_func = git_undo_func
        self.app_name = app_name
        self.list_rules = list_rules_func
        self.enable_rule = enable_rule_func
        self.disable_rule = disable_rule_func
        self.toggle_repo_map = toggle_repo_map_func
        self.get_repo_map_str_func = get_repo_map_str_func
        self.suggest_files_func = suggest_files_func
        self.logger = logging.getLogger(__name__)

    # _run_tests method removed

    def handle(self, inp: str) -> CommandHandlerReturn:
        """
        Parses and handles a slash command.

        Returns:
            Tuple[bool, Optional[str]]:
                (False, None) if the command signals to exit.
                (True, str) if the command includes a prompt to be processed immediately.
                (True, None) if the command was handled successfully.
        """
        parts = inp.strip().split(maxsplit=1)
        command = parts[0]
        args_str = parts[1].strip() if len(parts) > 1 else ""

        if command == "/add":
            filenames = re.findall(r"\"(.+?)\"|(\S+)", args_str)
            filenames = [name for sublist in filenames for name in sublist if name]
            if not filenames:
                self.logger.error('Usage: /add <file1> ["file 2"] ...')
            else:
                for fname in filenames:
                    if self.file_manager.add_file(fname):
                        abs_path = self.file_manager.get_abs_path(fname)
                        if abs_path:
                            rel_path = self.file_manager._get_rel_path(abs_path)
                            if rel_path in self.file_manager.get_files():
                                self.write_history_func("tool", f"Added {rel_path} to the chat.")
            return True, None

        elif command == "/drop":
            filenames = re.findall(r"\"(.+?)\"|(\S+)", args_str)
            filenames = [name for sublist in filenames for name in sublist if name]
            if not filenames:
                self.logger.error('Usage: /drop <file1> ["file 2"] ...')
            else:
                initial_fnames = set(self.file_manager.get_files())
                for fname in filenames:
                    self.file_manager.drop_file(fname)
                dropped_fnames = initial_fnames - self.file_manager.get_files()
                for fname in dropped_fnames:
                    self.write_history_func("tool", f"Removed {fname} from the chat.")
            return True, None

        elif command == "/clear":
            self.clear_history_func()
            self.logger.info("Chat history cleared.")
            self.write_history_func("tool", "Chat history cleared.")
            return True, None

        elif command == "/reset":
            self.file_manager.fnames = set()
            self.clear_history_func()
            self.logger.info("Chat history and file list cleared.")
            self.write_history_func("tool", "Chat history and file list cleared.")
            return True, None

        elif command == "/commit":
            self.git_commit_func()
            return True, None

        elif command == "/undo":
            self.git_undo_func()
            return True, None

        elif command == "/ask":
            if args_str:
                self.logger.warning("/ask command no longer accepts arguments. It only switches mode. Use /code or /ask then enter your query.")
            self.set_mode("ask")
            self.logger.info("Switched to ASK mode. I will answer questions but not edit files.")
            return True, None

        elif command == "/code":
            if args_str:
                self.logger.warning("/code command no longer accepts arguments. It only switches mode. Use /code or /ask then enter your query.")
            self.set_mode("code")
            self.logger.info("Switched to CODE mode. I will try to edit files.")
            return True, None
        
        elif command == "/suggest_files":
            # args_str contains the optional instruction from the user
            # The _ask_llm_for_files_based_on_context method handles if args_str is empty
            self.suggest_files_func(args_str if args_str else None)
            return True, None

        elif command == "/tests":
            if args_str:
                self.logger.warning("/tests command does not accept arguments.")
            run_tests(
                 self.write_history_func,
                 self.git_manager,
             )
            return True, None

        elif command == "/files":
            current_fnames = self.file_manager.get_files()
            if not current_fnames:
                self.logger.info("No files are currently added to the chat.")
            else:
                self.logger.info("Files in chat (estimated tokens):")
                for fname_rel in sorted(current_fnames):
                    abs_path = self.file_manager.get_abs_path(fname_rel)
                    if abs_path and abs_path.exists() and abs_path.is_file():
                        content = self.file_manager.read_file(abs_path)
                        if content is not None:
                            tokens = int(len(content) / 4)
                            self.logger.info(f"- {fname_rel} ({tokens} tokens)")
                        else:
                            self.logger.info(f"- {fname_rel} (Error reading file)")
                    elif abs_path and abs_path.exists() and not abs_path.is_file():
                        self.logger.info(f"- {fname_rel} (Not a file)")
                    else:
                        # This case might occur if a file was added then deleted from disk,
                        # or was a placeholder for a new file not yet created by CodeApplier
                        self.logger.info(f"- {fname_rel} (File not found or not yet created)")
            return True, None

        elif command == "/rules":
            rule_parts = args_str.split(maxsplit=1)
            sub_command = rule_parts[0] if rule_parts else "list" # Default to list
            rule_name = rule_parts[1].strip() if len(rule_parts) > 1 else None

            if sub_command == "list":
                if rule_name:
                    self.logger.warning("`/rules list` does not accept arguments.")
                rules_list_str = self.list_rules()
                self.logger.info(rules_list_str)
            elif sub_command == "enable":
                if not rule_name:
                    self.logger.error("Usage: /rules enable <rule_name>")
                else:
                    self.enable_rule(rule_name) # App logs success/failure
            elif sub_command == "disable":
                if not rule_name:
                    self.logger.error("Usage: /rules disable <rule_name>")
                else:
                    self.disable_rule(rule_name) # App logs success/failure
            else:
                self.logger.error(f"Unknown /rules sub-command: {sub_command}. Use 'list', 'enable', or 'disable'.")
            return True, None

        elif command == "/repomap":
            if args_str == "on":
                self.toggle_repo_map(True)
            elif args_str == "off":
                self.toggle_repo_map(False)
            elif args_str == "show":
                repo_map_content = self.get_repo_map_str_func()
                if repo_map_content and repo_map_content != "Repository map is not available at this moment." and repo_map_content.strip() != "Repository Map (other files):": # Check if map is truly empty

                    self.logger.info("--- Current Repository Map ---\n" + repo_map_content)
                else:
                    self.logger.info("Repository map is currently empty or contains no files to display (excluding files already in chat context).")
            elif not args_str:
                 self.logger.error("Usage: /repomap <on|off|show>")
            else:
                self.logger.error(f"Invalid argument for /repomap: '{args_str}'. Use 'on', 'off', or 'show'.")
            return True, None

        elif command == "/help":
            help_text = f"""Available commands:
  /add <file1> ["file 2"]...  Add file(s) to the chat context.
  /drop <file1> ["file 2"]... Remove file(s) from the chat context.
  /files                      List files currently in the chat.
  /suggest_files [instruction] Ask the LLM to suggest relevant files. Uses last user message if no instruction.
  /clear                      Clear the chat history.
  /reset                      Clear chat history and drop all files.
  /commit                     Commit the current changes made by {self.app_name}.
  /undo                       Undo the last commit made by {self.app_name}.
  /ask                        Switch to ASK mode (answer questions, no edits).
  /code                       Switch to CODE mode (make edits).
  /tests                      Run unit tests found in the ./tests directory.
  /rules list                 List available built-in and custom rules and their status for this project.
  /rules enable <rule_name>   Enable a rule for this project.
  /rules disable <rule_name>  Disable a rule for this project.
  /repomap [on|off|show]      Enable, disable, or show the inclusion of the repository map in prompts.
  /help                       Show this help message.
  /exit or /quit              Exit the application.
  !<shell_command>           Execute a shell command in the project directory."""
            self.logger.info(help_text)
            return True, None

        elif command in ["/exit", "/quit"]:
            return False, None

        else:
            self.logger.error(f"Unknown command: {command}. Try /help.")
            return True, None
