import logging
import os
import platform
import re # Added for markdown formatting
import sys
import traceback
from pathlib import Path
from typing import List, Set, Dict, Optional
import atexit

# readline is not available on all platforms (e.g., standard Windows cmd)
try:
    import readline
    READLINE_AVAILABLE = True
except ImportError:
    READLINE_AVAILABLE = False

from tinycoder.chat_history import ChatHistoryManager
from tinycoder.code_applier import CodeApplier
from tinycoder.command_handler import CommandHandler
from tinycoder.edit_parser import EditParser
from tinycoder.file_manager import FileManager
from tinycoder.git_manager import GitManager
from tinycoder.file_manager import FileManager
from tinycoder.llms.base import LLMClient
from tinycoder.llms import create_llm_client
from tinycoder.prompt_builder import PromptBuilder
from tinycoder.repo_map import RepoMap
from tinycoder.rule_manager import RuleManager
from tinycoder.shell_executor import ShellExecutor
from tinycoder.input_preprocessor import InputPreprocessor
from tinycoder.ui.console_interface import ring_bell, ConsoleInterface
from tinycoder.ui.command_completer import CommandCompleter, READLINE_AVAILABLE as COMPLETION_READLINE_AVAILABLE
from tinycoder.ui.log_formatter import ColorLogFormatter, STYLES, COLORS as FmtColors, RESET
from tinycoder.ui.spinner import Spinner

COMMIT_PREFIX = "🤖 tinycoder: "
HISTORY_FILE = ".tinycoder_history"
APP_NAME = "tinycoder"


class App:
    def __init__(self, model: Optional[str], files: List[str], continue_chat: bool, verbose: bool = False):
        """Initializes the TinyCoder application."""
        self.verbose = verbose
        self._setup_logging()
        self._init_llm_client(model)
        self._init_spinner()
        self._setup_git()
        self._init_core_managers(continue_chat)
        self._init_prompt_builder()
        self._setup_rules_manager()
        self._init_input_preprocessor() # Initialize InputPreprocessor
        self._init_console_interface() # Initialize ConsoleInterface
        self._init_app_state()
        self._init_command_handler()
        self._configure_readline()
        self._init_app_components()
        self._log_final_status()
        self._add_initial_files(files)


    def _setup_logging(self) -> None:
        """Configures the root logger with colored output."""
        root_logger = logging.getLogger()

        # Set root logger level based on verbose flag
        root_logger.setLevel(logging.DEBUG if self.verbose else logging.INFO)

        # Remove existing handlers to prevent duplicates
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)

        ch = logging.StreamHandler(sys.stdout)
        # Set stream handler level based on verbose flag
        ch.setLevel(logging.DEBUG if self.verbose else logging.INFO)

        # Use terminal default color for INFO level messages
        log_format_info = "%(message)s"
        log_format_debug = f"{FmtColors['GREY']}DEBUG:{RESET} %(message)s"
        log_format_warn = f"{STYLES['BOLD']}{FmtColors['YELLOW']}WARNING:{RESET} %(message)s"
        log_format_error = f"{STYLES['BOLD']}{FmtColors['RED']}ERROR:{RESET} {FmtColors['RED']}%(message)s{RESET}"
        log_format_critical = f"{STYLES['BOLD']}{FmtColors['RED']}CRITICAL:{RESET} {STYLES['BOLD']}{FmtColors['RED']}%(message)s{RESET}"
        default_log_format = "%(levelname)s: %(message)s"

        formatter = ColorLogFormatter(
            fmt=default_log_format,
            level_formats={
                logging.DEBUG: log_format_debug,
                logging.INFO: log_format_info,
                logging.WARNING: log_format_warn,
                logging.ERROR: log_format_error,
                logging.CRITICAL: log_format_critical,
            },
            use_color=None # Auto-detect TTY and NO_COLOR env var
        )
        ch.setFormatter(formatter)
        root_logger.addHandler(ch)

        self.logger = logging.getLogger(__name__)
        self.logger.debug("Logging setup complete.")

    def _init_llm_client(self, model: Optional[str]) -> None:
        """Initializes the LLM client based on the provided model name."""
        try:
            self.client: LLMClient = create_llm_client(model)
            self.model: Optional[str] = self.client.model # Get actual model used
            self.logger.debug(f"LLM Client initialized with model: {self.model}")
        except ValueError as e:
            self.logger.error(f"Failed to initialize LLM client: {e}", exc_info=True)
            print(f"{FmtColors['RED']}Error: Failed to initialize LLM client. {e}{RESET}", file=sys.stderr)
            print("Please check model name or API key environment variables.", file=sys.stderr)
            sys.exit(1)

    def _init_spinner(self) -> None:
        """Initializes the console spinner."""
        self.spinner = Spinner("💭 Thinking...")
        self.logger.debug("Spinner initialized.")

    def _setup_git(self) -> None:
        """Initializes GitManager, checks for Git, finds root, and optionally initializes a repo."""
        self.git_manager = GitManager()
        self.git_root: Optional[str] = None # Initialize git_root to None

        if not self.git_manager.is_git_available():
            self.logger.warning("Git command not found. Proceeding without Git integration.")
            return # Early exit if Git is not available

        # Git is available, check for repo
        self.git_root = self.git_manager.get_root()

        if self.git_root is None:
            # Git is available, but no .git found in CWD or parents
            self.logger.warning(
                f"Git is available, but no .git directory found starting from {Path.cwd()}."
            )
            try:
                print("Initialize a new Git repository here? (y/N): ", end="", flush=True)
                response = input()
            except EOFError: # Handle non-interactive scenarios
                response = "n"
                print() # Newline after simulated EOF

            if response.lower() == 'y':
                initialized = self.git_manager.initialize_repo()
                if initialized:
                    self.git_root = self.git_manager.get_root() # Re-fetch the root after init
                    if self.git_root:
                        self.logger.info(f"Git repository initialized. Root: {self.git_root}")
                    else:
                        # Should not happen if initialize_repo succeeded, but handle defensively
                        self.logger.error("Git initialization reported success, but failed to find root afterwards. Proceeding without Git integration.")
                else:
                    self.logger.error("Git initialization failed. Proceeding without Git integration.")
            else:
                self.logger.warning("Proceeding without Git integration.")
        else:
            self.logger.debug(f"Found existing Git repository. Root: {self.git_root}")
            # If git_root was found initially, we don't need to prompt or initialize

        # self.git_root is now set correctly (or None)

    def _init_core_managers(self, continue_chat: bool) -> None:
        """Initializes FileManager, ChatHistoryManager, and RepoMap."""
        # These depend on self.git_root potentially being set by _setup_git()
        self.file_manager = FileManager(self.git_root, input)
        self.history_manager = ChatHistoryManager(continue_chat=continue_chat)
        self.repo_map = RepoMap(self.git_root) # Pass the final git_root
        self.logger.debug("Core managers (File, History, RepoMap) initialized.")

    def _init_prompt_builder(self) -> None:
        """Initializes the PromptBuilder."""
        # Depends on FileManager and RepoMap
        self.prompt_builder = PromptBuilder(self.file_manager, self.repo_map)
        self.logger.debug("PromptBuilder initialized.")

    def _setup_rules_manager(self) -> None:
        """Initializes the RuleManager."""
        project_identifier = self._get_project_identifier()
        self.logger.debug(f"Project identifier for rules: {project_identifier}")

        if platform.system() == "Windows":
            config_dir = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / APP_NAME
        elif platform.system() == "Darwin":  # macOS
            config_dir = Path.home() / "Library" / "Application Support" / APP_NAME
        else:  # Linux and other Unix-like systems
            config_dir = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / APP_NAME
        
        rules_config_path = config_dir / "rules_config.json"
        self.logger.debug(f"Rules configuration path: {rules_config_path}")

        # Determine base directory for custom rules (git_root or cwd)
        base_dir_for_rules = Path(self.git_root) if self.git_root else Path.cwd()

        self.rule_manager = RuleManager(
            project_identifier=project_identifier,
            rules_config_path=rules_config_path,
            base_dir=base_dir_for_rules,
            logger=self.logger # Pass the App's logger instance
        )
        self.logger.debug("RuleManager initialized.")

    def _init_input_preprocessor(self) -> None:
        """Initializes the InputPreprocessor."""
        self.input_preprocessor = InputPreprocessor(
            logger=self.logger,
            file_manager=self.file_manager,
            git_manager=self.git_manager,
            repo_map=self.repo_map
        )
        self.logger.debug("InputPreprocessor initialized.")

    def _init_console_interface(self) -> None:
        """Initializes the ConsoleInterface."""
        self.console_interface = ConsoleInterface(
            logger=self.logger,
            get_app_mode_func=lambda: self.mode, # Pass a callable to get current mode
            readline_available=READLINE_AVAILABLE # Pass the app-level constant
        )
        self.logger.debug("ConsoleInterface initialized.")

    def _init_app_state(self) -> None:
        """Initializes basic application state variables."""
        self.coder_commits: Set[str] = set()
        self.coder_commits: Set[str] = set()
        self.mode = "code" # Default mode
        self.lint_errors_found: Dict[str, str] = {}
        self.reflected_message: Optional[str] = None
        self.include_repo_map: bool = True # Default to including the repo map
        self.logger.debug("Basic app state initialized (commits, mode, lint status, repo map toggle).")

    def toggle_repo_map(self, state: bool) -> None:
        """Sets the state for including the repo map in prompts."""
        self.include_repo_map = state
        status = "enabled" if state else "disabled"
        self.logger.info(f"Repository map inclusion in prompts is now {status}.")

    def _get_current_repo_map_string(self) -> str:
        """Generates and returns the current repository map string."""
        chat_files_rel = self.file_manager.get_files() # Set[str] of relative paths
        # Ensure repo_map is initialized and has a root before generating
        if self.repo_map and self.repo_map.root:
            return self.repo_map.generate_map(chat_files_rel)
        else:
            self.logger.warning("RepoMap not fully initialized, cannot generate map string.")
            return "Repository map is not available at this moment."

    def _ask_llm_for_files_based_on_context(self, custom_instruction: Optional[str] = None) -> None:
        """
        Handles the /suggest_files command.
        Asks the LLM for file suggestions based on custom instruction or last user message.
        Then, prompts the user to add these files.
        """
        instruction = ""
        if custom_instruction and custom_instruction.strip():
            instruction = custom_instruction.strip()
            self.logger.info(f"Suggesting files based on your query: '{instruction}'")
        else:
            history = self.history_manager.get_history()
            # Find the last actual user message, skipping any tool messages or placeholders
            last_user_message = next((msg['content'] for msg in reversed(history) if msg['role'] == 'user' and msg['content'] and not msg['content'].startswith("(placeholder)")), None)
            if last_user_message:
                instruction = last_user_message
                self.logger.info("Suggesting files based on the last user message in history.")
            else:
                self.logger.warning("No custom instruction provided and no suitable user history found to base suggestions on.")
                return

        if not instruction:
            self.logger.warning("Cannot suggest files without a valid instruction.")
            return

        suggested_files = self._ask_llm_for_files(instruction) # This method already logs its own findings

        if suggested_files:
            self.logger.info("LLM suggested the following files (relative to project root):")
            for i, fname in enumerate(suggested_files):
                self.logger.info(f"  {i+1}. {fname}")

            try:
                confirm_prompt = "Add files to context? (y/N, or list indices like '1,3'): "
                confirm = input(confirm_prompt).strip().lower()
            except EOFError:
                confirm = "n"
                print() 
            except KeyboardInterrupt:
                self.logger.info("\nFile addition cancelled by user.")
                return

            files_to_add = []
            if confirm == 'y':
                files_to_add = suggested_files
            elif confirm and confirm != 'n':
                try:
                    indices_to_add = [int(x.strip()) - 1 for x in confirm.split(',') if x.strip().isdigit()]
                    files_to_add = [suggested_files[i] for i in indices_to_add if 0 <= i < len(suggested_files)]
                except (ValueError, IndexError):
                    self.logger.warning("Invalid selection. No files will be added from suggestions.")

            if files_to_add:
                added_count = 0
                successfully_added_fnames = []
                for fname in files_to_add:
                    if self.file_manager.add_file(fname): # add_file handles logging success/failure per file
                        added_count += 1
                        successfully_added_fnames.append(fname)
                
                if added_count > 0:
                    self.history_manager.save_message_to_file_only(
                        "tool",
                        f"Added {added_count} file(s) to context from LLM suggestion: {', '.join(successfully_added_fnames)}"
                    )
                    self.logger.info(f"Added {added_count} file(s) to context: {', '.join(successfully_added_fnames)}")
            else:
                self.logger.info("No suggested files were added to the context.")
        elif instruction: # _ask_llm_for_files was called but returned no files
            self.logger.info("LLM did not suggest any files based on the provided instruction.")
        # If instruction was empty, it's logged before calling _ask_llm_for_files


    def _init_command_handler(self) -> None:
        """Initializes the CommandHandler."""
        # Depends on several managers and methods
        self.command_handler = CommandHandler(
            file_manager=self.file_manager,
            git_manager=self.git_manager,
            clear_history_func=self.history_manager.clear,
            write_history_func=self.history_manager.save_message_to_file_only,
            get_mode=lambda: self.mode,
            set_mode=lambda mode: setattr(self, "mode", mode),
            git_commit_func=self._git_add_commit,
            git_undo_func=self._git_undo,
            app_name=APP_NAME,
            enable_rule_func=self.rule_manager.enable_rule, 
            disable_rule_func=self.rule_manager.disable_rule,
            list_rules_func=self.rule_manager.list_rules,
            toggle_repo_map_func=self.toggle_repo_map,
            get_repo_map_str_func=self._get_current_repo_map_string,
            suggest_files_func=self._ask_llm_for_files_based_on_context,
            add_repomap_exclusion_func=self.repo_map.add_user_exclusion,
            remove_repomap_exclusion_func=self.repo_map.remove_user_exclusion,
            get_repomap_exclusions_func=self.repo_map.get_user_exclusions,
        )
        self.logger.debug("CommandHandler initialized.")

    def _init_app_components(self) -> None:
        """Initializes EditParser, CodeApplier, and determines input function."""
        self.edit_parser = EditParser()
        self.code_applier = CodeApplier(
            file_manager=self.file_manager,
            git_manager=self.git_manager,
            input_func=input, # Use built-in input for confirmations within applier
        )
        # Initialize ShellExecutor
        self.shell_executor = ShellExecutor(
            logger=self.logger,
            history_manager=self.history_manager,
            git_root=self.git_root
        )
        # Determine primary input function for main loop using ConsoleInterface
        self.input_func = self.console_interface.determine_input_function()
        self.logger.debug("App components (Parser, Applier, ShellExecutor, Input Func from ConsoleInterface) initialized.")

    def _log_final_status(self) -> None:
        """Logs the final Git integration status after all setup."""
        if not self.git_manager.is_git_available():
            # Warning already logged during init
            self.logger.debug("Final check: Git is unavailable. Git integration disabled.")
        elif not self.git_root:
            # Git is available, but no repo was found or initialized
            self.logger.warning("Final check: Not inside a git repository. Git integration disabled.")
        else:
            # Git is available and we have a root
            self.logger.debug(f"Final check: Git repository root confirmed: {self.git_root}")
            # Ensure RepoMap knows the root (should be set by _init_core_managers)
            if self.repo_map.root is None: # Defensive check
                 self.logger.warning("RepoMap root was unexpectedly None, attempting to set.")
                 self.repo_map.root = Path(self.git_root)
            elif str(self.repo_map.root.resolve()) != str(Path(self.git_root).resolve()):
                self.logger.warning(f"Mismatch between GitManager root ({self.git_root}) and RepoMap root ({self.repo_map.root}). Using GitManager root.")
                self.repo_map.root = Path(self.git_root)


    def _add_initial_files(self, files: List[str]) -> None:
        """Adds initial files specified via command line arguments."""
        if files:
            self.logger.info(f"Adding initial files to context: {', '.join(files)}")
            added_count = 0
            for fname in files:
                if self.file_manager.add_file(fname):
                    added_count += 1
            self.logger.info(f"Successfully added {added_count} initial file(s).")
        else:
            self.logger.debug("No initial files specified.")


    def _get_project_identifier(self) -> str:
        """Returns the git root path if available, otherwise the current working directory path."""
        if self.git_root:
            return str(Path(self.git_root).resolve())
        else:
            return str(Path.cwd().resolve())
        
    def _configure_readline(self):
        """Configures readline for history and command completion if available."""
        # Use the local READLINE_AVAILABLE for history, and the imported one for completer
        if not READLINE_AVAILABLE: # This is the one defined in __init__.py for history
            self.logger.info("Readline module not available for history features.")
            # No return here yet, completion might still be attempted if COMPLETION_READLINE_AVAILABLE is true

        if not COMPLETION_READLINE_AVAILABLE: # This is from command_completer.py
            self.logger.info("Readline module not available for command completion features.")
        
        if not READLINE_AVAILABLE and not COMPLETION_READLINE_AVAILABLE:
            self.logger.info("Readline module not available. Skipping history and completion setup.")
            return

        self.logger.debug("Readline available. Configuring...")

        # --- Completion Setup ---
        if COMPLETION_READLINE_AVAILABLE:
            try:
                completer_instance = CommandCompleter(self.file_manager, self.git_manager)
                readline.set_completer(completer_instance.complete)

                # Set delimiters for completion. Crucially, DO NOT include path separators like '/' or '.'
                # if you want to complete segments containing them. Let's stick to whitespace and typical shell separators.
                # Space is the most important delimiter here to separate `/add` from the path.
                readline.set_completer_delims(' \t\n`~!@#$%^&*()=+[{]}|;:\'",<>?') # Removed \ . /

                # Configure Tab key binding
                if 'libedit' in readline.__doc__: # macOS/libedit
                    readline.parse_and_bind("bind -e") # Ensure emacs mode
                    readline.parse_and_bind("bind '\t' rl_complete")
                    self.logger.debug("Using libedit Tab binding.")
                else: # GNU readline
                    readline.parse_and_bind("tab: complete")
                    self.logger.debug("Using standard readline Tab binding.")

            except Exception as e:
                self.logger.error(f"Failed to configure readline completion: {e}", exc_info=True)


        # --- History Setup ---
        if READLINE_AVAILABLE: # Guard history setup with the local READLINE_AVAILABLE
            # Use project identifier for potentially project-specific history
            # Or use a generic one in the user's home directory
            hist_dir = Path.home() / ".local" / "share" / APP_NAME
            hist_dir.mkdir(parents=True, exist_ok=True) # Ensure directory exists
            # Use a consistent history filename
            self.history_file = hist_dir / HISTORY_FILE

            try:
                # Set history length (optional)
                readline.set_history_length(1000)
                # Read history file *after* setting bindings and completer, *before* registering save
                if self.history_file.exists():
                    readline.read_history_file(self.history_file)
                    self.logger.debug(f"Read history from {self.history_file}")
                else:
                    self.logger.debug(f"History file {self.history_file} not found, starting fresh.")

                # Register saving history on exit
                atexit.register(self._save_readline_history)
                self.logger.debug("Readline history configured and loaded.")
            except Exception as e:
                self.logger.error(f"Failed to configure readline history: {e}", exc_info=True)
        else:
            self.logger.debug("Skipping readline history setup as readline is not available.")


    def _save_readline_history(self):
        """Saves the readline history to the designated file."""
        if not READLINE_AVAILABLE: # Use local READLINE_AVAILABLE
            return
        try:
            readline.write_history_file(self.history_file)
            self.logger.debug(f"Readline history saved to {self.history_file}")
        except Exception as e:
            self.logger.error(f"Failed to save readline history to {self.history_file}: {e}")

    def _send_to_llm(self) -> Optional[str]:
        """Sends the current chat history and file context to the LLM."""
        current_history = self.history_manager.get_history()
        if not current_history or current_history[-1]["role"] != "user":
            self.logger.error("Cannot send to LLM without a user message.")
            return None

        # Use PromptBuilder to build the system prompt
        # Pass the loaded active rules content and the repo map state
        active_rules = self.rule_manager.get_active_rules_content() # Get from RuleManager
        system_prompt_content = self.prompt_builder.build_system_prompt(
            self.mode,
            active_rules,
            self.include_repo_map      # Pass the toggle state
        )
        system_prompt_msg = {"role": "system", "content": system_prompt_content}

        # Use PromptBuilder to get the file content message
        file_context_message = self.prompt_builder.get_file_content_message()
        file_context_messages = [file_context_message] if file_context_message else []

        # Combine messages: System Prompt, Chat History (excluding last user msg), File Context, Last User Msg
        # Place file context right before the last user message for relevance
        messages_to_send = (
            [system_prompt_msg]
            + current_history[:-1]
            + file_context_messages
            + [current_history[-1]]
        )

        # Simple alternation check (might need refinement for edge cases)
        final_messages = []
        last_role = "system"  # Start assuming system
        for msg in messages_to_send:
            if msg["role"] == "system":  # Allow system messages anywhere
                final_messages.append(msg)
                # Don't update last_role for system message
                continue
            if msg["role"] == last_role:
                # Insert placeholder if consecutive non-system roles are the same
                if last_role == "user":
                    final_messages.append(
                        {"role": "assistant", "content": "(placeholder)"}
                    )
                else:
                    final_messages.append({"role": "user", "content": "(placeholder)"})
            final_messages.append(msg)
            last_role = msg["role"]

        try:
            # --- Use the selected LLM client ---
            # The client interface expects system_prompt and history separately.
            system_prompt_text = ""
            history_to_send = []

            # Extract system prompt if present
            if final_messages and final_messages[0]["role"] == "system":
                system_prompt_text = final_messages[0]["content"]
                history_to_send = final_messages[
                    1:
                ]  # Exclude system prompt from history
            else:
                # If no system prompt was built (e.g., empty history?), send history as is
                history_to_send = final_messages
                self.logger.warning(
                    "System prompt not found at the beginning of messages for LLM."
                )

            total_tokens = (sum(len(msg["content"]) for msg in history_to_send) + len(system_prompt_text))/4
            
            self.logger.debug(f"Approx. total tokens to send: {total_tokens}") # Changed to debug for less noise

            self.spinner.start()
            response_content, error_message = self.client.generate_content(
                system_prompt=system_prompt_text, history=history_to_send
            )
            self.spinner.stop()

            # --- Handle response ---
            if error_message:
                self.logger.error(
                    f"Error calling LLM API ({self.client.__class__.__name__}): {error_message}",
                )
                return None
            elif response_content is None:
                # Should be covered by error_message, but handle defensively
                self.logger.error(
                    f"LLM API ({self.client.__class__.__name__}) returned no content and no error message.",
                )
                return None
            else:
                # Format for display if in ask mode and not an edit block
                if self.mode == "ask" and response_content and not response_content.strip().startswith("<"):
                    display_response = self._format_markdown_for_terminal(response_content)
                    self.logger.info(f"\n{FmtColors['CYAN']}{STYLES['BOLD']}ASSISTANT{RESET}:\n" + display_response + "\n")
                else:
                    self.logger.info(f"\n{FmtColors['CYAN']}{STYLES['BOLD']}ASSISTANT{RESET}:\n" + response_content + "\n")
                
                n_tokens = len(response_content)/4 # Based on raw response
                self.logger.debug("Approx. response tokens: %d", n_tokens) # Changed to debug
            
                return response_content

        except Exception as e:
            # Catch any unexpected errors during the process
            self.logger.error(
                f"An unexpected error occurred preparing for or handling LLM API call ({self.client.__class__.__name__}): {e}",
            )
            # Print traceback for debugging unexpected issues
            traceback.print_exc()
            return None  # Indicate error

    def _git_add_commit(self, paths_to_commit: Optional[List[str]] = None):
        """
        Stage changes and commit them using GitManager.

        Args:
            paths_to_commit: If provided, only these relative paths will be committed.
                             If None, commits changes to all files currently in the FileManager context.
        """
        if not self.git_manager.is_repo(): # is_repo() also implicitly checks if git is available
            self.logger.info("Not in a git repository or Git is unavailable, skipping commit.")
            return

        files_to_commit_abs = []
        files_to_commit_rel = []

        target_fnames = (
            paths_to_commit
            if paths_to_commit is not None
            else self.file_manager.get_files()
        )

        if not target_fnames:
            self.logger.info("No target files specified or in context to commit.")
            return

        # Ensure provided paths actually exist and resolve them
        for fname in target_fnames:  # fname is relative path
            abs_path = self.file_manager.get_abs_path(fname)
            if abs_path and abs_path.exists():
                files_to_commit_abs.append(str(abs_path))
                files_to_commit_rel.append(fname)
            else:
                # Warn if a specifically requested path doesn't exist
                if paths_to_commit is not None:
                    self.logger.warning(
                        f"Requested commit path {fname} does not exist on disk, skipping.",
                    )
                # Don't warn if iterating all context files and one is missing (it might have been deleted)

        if not files_to_commit_abs:
            self.logger.info("No existing files found for the commit.")
            return

        # Prepare commit message
        commit_message = (
            f"{COMMIT_PREFIX} Changes to {', '.join(sorted(files_to_commit_rel))}"
        )

        # Call GitManager to commit
        commit_hash = self.git_manager.commit_files(
            files_to_commit_abs, files_to_commit_rel, commit_message
        )

        if commit_hash:
            self.coder_commits.add(commit_hash)
            # Success message printed by GitManager
        # else: # Failure messages printed by GitManager

    def _git_undo(self):
        """Undo the last commit made by this tool using GitManager."""
        if not self.git_manager.is_repo(): # is_repo() also implicitly checks if git is available
            self.logger.error("Not in a git repository or Git is unavailable.")
            return

        last_hash = self.git_manager.get_last_commit_hash()
        if not last_hash:
            # Error already printed by GitManager
            return

        if last_hash not in self.coder_commits:
            self.logger.error(f"Last commit {last_hash} was not made by {APP_NAME}.")
            self.logger.info("You can manually undo with 'git reset HEAD~1'")
            return

        # Call GitManager to undo
        success = self.git_manager.undo_last_commit(last_hash)

        if success:
            self.coder_commits.discard(last_hash)  # Remove hash if undo succeeded
            # Use history manager to log the undo action to the file only
            self.history_manager.save_message_to_file_only(
                "tool", f"Undid commit {last_hash}"
            )

    def _handle_llm_file_requests(self, requested_files_from_llm: List[str]) -> bool:
        """
        Handles LLM's request for additional files.
        Checks existence, prompts user, adds files, and sets up reflection.
        Returns True if a reflection message was set (meaning files were added or action taken
        that requires an LLM follow-up), False otherwise.
        """
        if not requested_files_from_llm:
            return False

        self.logger.info(f"{STYLES['BOLD']}LLM requested additional file context.{RESET}")
        
        valid_files_to_potentially_add = []
        non_existent_files_requested = []
        already_in_context_files = []

        for fname_rel in requested_files_from_llm:
            abs_path = self.file_manager.get_abs_path(fname_rel)
            if abs_path and abs_path.exists():
                if fname_rel not in self.file_manager.get_files():
                     valid_files_to_potentially_add.append(fname_rel)
                else:
                    already_in_context_files.append(fname_rel)
            else:
                non_existent_files_requested.append(fname_rel)

        if non_existent_files_requested:
            formatted_non_existent = [f"{FmtColors['RED']}{fname}{RESET}" for fname in non_existent_files_requested]
            self.logger.warning(
                f"LLM requested non-existent files: {', '.join(formatted_non_existent)}"
            )
        
        if already_in_context_files:
            formatted_already_in_context = [f"{FmtColors['GREY']}{fname}{RESET}" for fname in already_in_context_files]
            self.logger.info(
                f"Requested files already in context: {', '.join(formatted_already_in_context)}"
            )

        if not valid_files_to_potentially_add:
            # This covers the case where all requested files were either non-existent or already in context.
            # The messages above would have informed the user.
            if requested_files_from_llm and not non_existent_files_requested and not already_in_context_files:
                # This case should ideally not be hit if logic is correct,
                # but as a fallback if all files requested were valid but somehow not new.
                self.logger.info("LLM requested files, but none are new and existing to add.")
            elif not requested_files_from_llm: # Should be caught by the first check, but for completeness.
                 pass # No request made initially.
            else:
                 # Info/warnings about non-existent or already-in-context files have been printed.
                 # If there are no *new* files to add, we can inform.
                 self.logger.info("No new, existing files to add from LLM's request.")
            return False

        self.logger.info(f"{FmtColors['BLUE']}LLM suggests adding these existing files to context:{RESET}")
        for i, fname in enumerate(valid_files_to_potentially_add):
            self.logger.info(f"  {i+1}. {FmtColors['CYAN']}{fname}{RESET}")
        
        try:
            confirm_prompt = "Add these files to context? (y/N, or list indices like '1,3'): "
            confirm = input(confirm_prompt).strip().lower()
        except EOFError:
            confirm = "n"
            print() 
        except KeyboardInterrupt:
            self.logger.info("\nFile addition (from LLM request) cancelled by user.")
            self.reflected_message = "User cancelled the addition of requested files. Please advise on how to proceed or if you can continue without them."
            return True

        files_to_add_confirmed = []
        if confirm == 'y':
            files_to_add_confirmed = valid_files_to_potentially_add
        elif confirm and confirm != 'n':
            try:
                indices_to_add = [int(x.strip()) - 1 for x in confirm.split(',') if x.strip().isdigit()]
                files_to_add_confirmed = [valid_files_to_potentially_add[i] for i in indices_to_add if 0 <= i < len(valid_files_to_potentially_add)]
            except (ValueError, IndexError):
                self.logger.warning("Invalid selection. No files will be added from LLM request.")

        if files_to_add_confirmed:
            added_count = 0
            successfully_added_fnames = []
            for fname in files_to_add_confirmed:
                if self.file_manager.add_file(fname): 
                    added_count += 1
                    successfully_added_fnames.append(fname)
            
            if added_count > 0:
                tool_message = f"Added {added_count} file(s) to context from LLM request: {', '.join(successfully_added_fnames)}"
                self.history_manager.save_message_to_file_only("tool", tool_message)
                reflection_content = (
                    f"The following files have been added to the context as per your request: {', '.join(successfully_added_fnames)}. "
                    "Please proceed with the original task based on the updated context."
                )
                self.reflected_message = reflection_content
                return True
            else:
                self.logger.info("No files were ultimately added from LLM's request despite confirmation.")
        else: 
            self.logger.info("User chose not to add files requested by LLM, or selection was invalid.")
            self.reflected_message = "User declined to add the requested files. Please advise on how to proceed or if you can continue without them."
            return True

        return False

    def process_user_input(self):
        """Processes the latest user input (already in history), sends to LLM, handles response."""
        response = self._send_to_llm()

        if response:
            self.history_manager.add_message("assistant", response)
            
            # Assuming edit_parser.parse now returns a dict: {"edits": [...], "requested_files": [...]}
            parsed_llm_output = self.edit_parser.parse(response)
            edits = parsed_llm_output.get("edits", [])
            requested_files = parsed_llm_output.get("requested_files", [])

            # --- Handle File Requests First ---
            if requested_files:
                if self._handle_llm_file_requests(requested_files):
                    # A reflection message is set (e.g., files added, user cancelled).
                    # The run_one loop will pick this up. We are done for this turn.
                    return 
                # If it returns False, it means no new files were added to prompt reflection,
                # so we can potentially proceed to edits if any were also sent.

            # --- Process Edits (only if not already handling a file request reflection and in code mode) ---
            if not self.reflected_message and self.mode == "code":
                if edits:
                    all_succeeded, failed_indices, modified_files, lint_errors = (
                        self.code_applier.apply_edits(edits)
                    )
                    self.lint_errors_found = lint_errors 

                    if all_succeeded:
                        if modified_files:
                            self.logger.info("All edits applied successfully.")
                            self._git_add_commit(list(modified_files))
                        else:
                            self.logger.info("Edits processed, but no files were changed.")
                    elif failed_indices:
                        failed_indices_str = ", ".join(map(str, sorted(failed_indices)))
                        error_message = (
                            f"Some edits failed to apply. No changes have been committed.\n"
                            f"Please review and provide corrected edit blocks for the failed edits.\n\n"
                            f"Failed edit block numbers (1-based): {failed_indices_str}\n\n"
                            f"Successfully applied edits (if any) have modified the files in memory, "
                            f"but you should provide corrections for the failed ones before proceeding."
                        )
                        self.logger.error(error_message)
                        self.reflected_message = error_message 
                    
                else:  # No edits found by parser (and no file requests were actioned to cause reflection)
                    self.logger.info("No actionable edit blocks found in the response.")

                # --- Check for Lint Errors (related to edits) ---
                # Only trigger lint reflection if no other more critical reflection (like edit failure) is already set.
                if self.lint_errors_found and not self.reflected_message: 
                    error_messages = ["Found syntax errors after applying edits:"]
                    for fname, error in self.lint_errors_found.items():
                        error_messages.append(f"\n--- Errors in {fname} ---\n{error}")
                    combined_errors = "\n".join(error_messages)
                    self.logger.error(combined_errors)

                    ring_bell()
                    fix_lint = input("Attempt to fix lint errors? (y/N): ")
                    if fix_lint.lower() == "y":
                        self.reflected_message = combined_errors
            
        # Mode reversion (if any) is handled in run_one after this function returns

    def _ask_llm_for_files(self, instruction: str) -> List[str]:
        """Asks the LLM to identify files needed for a given instruction."""
        self.logger.info("Asking LLM to identify relevant files...")

        # Use PromptBuilder to build the identify files prompt, passing repo map state
        system_prompt = self.prompt_builder.build_identify_files_prompt(
            include_map=self.include_repo_map
        )

        history_for_files = [{"role": "user", "content": instruction}]
        self.spinner.start()
        response_content, error_message = self.client.generate_content(
            system_prompt=system_prompt, history=history_for_files
        )
        self.spinner.stop()

        if error_message:
            self.logger.error(f"Error asking LLM for files: {error_message}")
            return []
        if not response_content:
            self.logger.warning("LLM did not suggest any files.")
            return []

        # Parse the response: one file per line
        potential_files = [
            line.strip()
            for line in response_content.strip().split("\n")
            if line.strip()
        ]
        # Basic filtering: remove backticks or quotes if LLM included them
        potential_files = [f.strip("`\"' ") for f in potential_files]

        # Filter out files that don't exist in the repository
        existing_files = []
        for fname in potential_files:
            abs_path = self.file_manager.get_abs_path(fname)
            if abs_path and abs_path.exists():
                existing_files.append(fname)
            else:
                self.logger.warning(
                    f"Ignoring non-existent file suggested by LLM: {fname}"
                )

        self.logger.info(
            f"LLM suggested files (after filtering): {', '.join(existing_files)}",
        )
        return existing_files

    def init_before_message(self):
        """Resets state before processing a new user message."""
        self.lint_errors_found = {}
        self.reflected_message = None

    def _format_markdown_for_terminal(self, markdown_text: str) -> str:
        """Applies simple ANSI styling to markdown text for terminal readability."""
        processed_lines = []
        in_code_block = False
        # Code block language is not used yet, but could be for syntax highlighting in future
        # code_block_lang = "" 

        for line in markdown_text.splitlines():
            stripped_line = line.lstrip() # Use lstrip for checking prefixes, keep original indent for code blocks

            # Handle Fenced Code Blocks
            if stripped_line.startswith("```"):
                if in_code_block:
                    in_code_block = False
                    # Color the fence itself
                    processed_lines.append(FmtColors['GREY'] + line + RESET)
                else:
                    in_code_block = True
                    # code_block_lang = stripped_line[3:].strip()
                    # lang_display = f" ({code_block_lang})" if code_block_lang else ""
                    processed_lines.append(FmtColors['GREY'] + line + RESET)
                continue

            if in_code_block:
                # Preserve original line including leading spaces for indentation
                processed_lines.append(FmtColors['GREEN'] + line + RESET)
                continue

            # Handle Headers (e.g., # H1, ## H2)
            if stripped_line.startswith("#"):
                level = 0
                temp_line = stripped_line
                while temp_line.startswith('#'):
                    level += 1
                    temp_line = temp_line[1:]
                
                if temp_line.startswith(' '): # Make sure it's a header, not just a line starting with #
                    header_text = temp_line[1:]
                    original_indent = line[:-len(stripped_line)] # Get leading whitespace
                    if level == 1: # H1
                        line = f"{original_indent}{STYLES['BOLD']}{FmtColors['BLUE']}# {header_text}{RESET}"
                    elif level == 2: # H2
                        line = f"{original_indent}{STYLES['BOLD']}{FmtColors['MAGENTA']}## {header_text}{RESET}"
                    else: # H3+
                        line = f"{original_indent}{STYLES['BOLD']}{FmtColors['CYAN']}{'#' * level} {header_text}{RESET}"
            else:
                # Handle Bold (**text** or __text__)
                # Apply bold and then immediately reset. The reset also turns off previous colors if any.
                # If we want to keep surrounding colors, this would need to be more complex.
                # Using a non-greedy match (.*?)
                line = re.sub(r'\*\*(.*?)\*\*', rf'{STYLES["BOLD"]}\1{RESET}', line)
                line = re.sub(r'__(.*?)__', rf'{STYLES["BOLD"]}\1{RESET}', line) # STYLES.NORMAL might be needed if terminal holds bold

                # Handle Inline Code (`code`) - apply after bold to allow `**bold code**`
                # (though typical markdown `**`code`**` would be `code` bolded)
                # For simplicity, this colors the content of `...`
                line = re.sub(r'`(.*?)`', rf'{FmtColors["YELLOW"]}\1{RESET}', line)
                
                # Handle Lists (* item, - item, 1. item)
                # Simple coloring of the marker. Preserves leading whitespace.
                line = re.sub(r'^(\s*)(\* |\- |\+ )', rf'\1{FmtColors["CYAN"]}\2{RESET}', line, 1)
                line = re.sub(r'^(\s*)([0-9]+\. )', rf'\1{FmtColors["CYAN"]}\2{RESET}', line, 1)
            
            processed_lines.append(line)

        return "\n".join(processed_lines)

    def _handle_command(self, user_message: str) -> bool:
        """
        Handles a command input. Returns False if the command is to exit, True otherwise.
        May modify self.mode.
        """
        # Use CommandHandler to process the command
        status, prompt_arg = self.command_handler.handle(user_message)

        if not status:
            return False  # Exit signal

        if prompt_arg:
            # If command included a prompt (e.g., /ask "What?"), process it *now*
            # Don't preprocess command arguments (e.g., URL check)
            if not self.run_one(prompt_arg, preproc=False):
                return False  # Exit signal from processing the prompt

        return True  # Continue processing

    def run_one(self, user_message, preproc, non_interactive=False):
        """
        Processes a single user message, including potential reflection loops in interactive mode.

        Args:
            user_message: The message from the user.
            preproc: Whether to preprocess the input (commands, URLs, file mentions).
            non_interactive: If True, disables interactive features like the lint reflection prompt.
        """
        self.init_before_message()

        if preproc:
            if user_message.startswith("/"):
                if not self._handle_command(user_message):
                    return False  # Exit signal
                else:
                    return True  # Command handled, stop further processing for this input cycle

            elif user_message.startswith("!"):
                # Delegate to ShellExecutor
                if self.shell_executor.execute(user_message, non_interactive):
                    return True # Command handled by ShellExecutor, stop further processing
                # If execute returned False (though current design is always True),
                # it would mean it wasn't a shell command or some other unhandled case.
                # For now, assume execute always returns True.
            else:
                message = self.input_preprocessor.process(user_message)
                if (
                    message is False # This was a defensive check, `process` returns str
                ):  # Should not happen from preproc, but check defensively
                    return False  # Exit signal
        else:
            message = user_message

        # If message is None or empty after potential command handling/preprocessing, stop
        # (Handles cases like only running a ! command or a /command without a prompt arg)
        if not message:
            return True  # Nothing more to process for this input cycle

        # --- Check if we need to ask LLM for files (code mode, no files yet) ---
        if self.mode == "code" and not self.file_manager.get_files():
            self.logger.info("No files in context for 'code' mode.")
            suggested_files = self._ask_llm_for_files(message)
            added_files_count = 0
            if suggested_files:
                self.logger.info("Attempting to add suggested files to context...")
                for fname in suggested_files:
                    if self.file_manager.add_file(
                        fname
                    ):  # add_file returns True on success, prints errors otherwise
                        added_files_count += 1
                if added_files_count > 0:
                    self.logger.info(
                        f"Added {added_files_count} file(s) suggested by LLM."
                    )
                else:
                    self.logger.warning(
                        "Could not add any of the files suggested by the LLM.",
                    )
            else:
                self.logger.warning(
                    "LLM did not suggest files, or failed to retrieve suggestions. Proceeding without file context.",
                )
            # Proceed even if no files were added, the LLM might still respond or ask for them again.

        # --- Main Processing & Optional Reflection ---
        num_reflections = 0
        max_reflections = 3

        # Initial processing of the user message
        self.history_manager.add_message("user", message)  # Use history manager
        self.process_user_input()  # This now handles LLM call, edits, linting

        # Check if reflection is needed *and* allowed (interactive mode)
        while not non_interactive and self.reflected_message:
            if num_reflections >= max_reflections:
                self.logger.warning(
                    f"Reached max reflection limit ({max_reflections}). Stopping reflection.",
                )
                self.reflected_message = None  # Prevent further loops
                break  # Exit reflection loop

            num_reflections += 1
            self.logger.info(
                f"Reflection {num_reflections}/{max_reflections}: Sending feedback to LLM..."
            )
            message = (
                self.reflected_message
            )  # Use the reflected message as the next input
            self.reflected_message = (
                None  # Clear before potentially being set again by process_user_input
            )

            # Add the reflected message to history *before* processing
            self.history_manager.add_message("user", message)
            self.process_user_input()  # Process the reflected input

        return True  # Indicate normal processing occurred (or finished reflection loop)

    def run(self):
        """Main loop for the chat application."""
        # Determine repo map status string with more detail
        repo_map_status_output_str: str
        if self.include_repo_map:
            user_exclusions = self.repo_map.get_user_exclusions()
            if user_exclusions:
                num_exclusions = len(user_exclusions)
                exclusions_details = f"with {num_exclusions} exclusion"
                if num_exclusions > 1:
                    exclusions_details += "s"
                # Using YELLOW for enabled with exclusions
                repo_map_status_output_str = f"{FmtColors['YELLOW']}{STYLES['BOLD']}Enabled ({exclusions_details}){RESET}"
            else:
                # Using GREEN for standard enabled (no exclusions)
                repo_map_status_output_str = f"{FmtColors['GREEN']}{STYLES['BOLD']}Enabled{RESET}"
        else:
            # Using default terminal color (bolded) for disabled
            repo_map_status_output_str = f"{STYLES['BOLD']}Disabled{RESET}"
        
        # Use FmtColors and STYLES for the welcome message
        # Apply specific color (GREEN) before BOLD, then RESET immediately after.
        # The rest of the message will use the default INFO format (terminal default color).
        
        # Constructing the welcome message parts
        model_line = f"  Model: {FmtColors['GREEN']}{STYLES['BOLD']}{self.model}{RESET}"
        repo_map_line = f"  Repo Map: {repo_map_status_output_str}"

        # Active Rules status
        num_active_rules = len(self.rule_manager.last_loaded_rule_names)
        active_rules_names_sorted = sorted(list(self.rule_manager.last_loaded_rule_names))
        
        active_rules_status_output_str: str
        if num_active_rules > 0:
            max_names_to_show = 2 # Be concise for welcome message
            names_str = ", ".join(active_rules_names_sorted[:max_names_to_show])
            if num_active_rules > max_names_to_show:
                names_str += f", ... ({num_active_rules - max_names_to_show} more)"
            
            active_rules_status_output_str = f"{FmtColors['GREEN']}{STYLES['BOLD']}Enabled ({num_active_rules}){RESET} [{names_str}]"
        else:
            # Using default terminal color (bolded) for none
            active_rules_status_output_str = f"{STYLES['BOLD']}None{RESET}"
        
        active_rules_line = f"  Rules: {active_rules_status_output_str}"
        help_line = f"  Type {FmtColors['CYAN']}{STYLES['BOLD']}/help{RESET} for commands, or {FmtColors['CYAN']}{STYLES['BOLD']}!<cmd>{RESET} to run shell commands. \n"

        # Log each part on a new line for clarity
        self.logger.info(model_line)
        self.logger.info(repo_map_line)
        self.logger.info(active_rules_line)
        self.logger.info(help_line)
        
        ctrl_c_pressed_once = False # Initialize flag outside the loop
        while True:
            try:
                # DO NOT reset ctrl_c_pressed_once = False here anymore

                ring_bell()  # Ring the bell before input
                inp = self.input_func() # This function handles its own KeyboardInterrupt by returning None

                if inp is None:
                    # Input was cancelled (Ctrl+C in readline loop or stdin read)
                    if ctrl_c_pressed_once:
                        print("\nExiting.", file=sys.stderr)
                        break # Exit on second consecutive Ctrl+C during input
                    else:
                        ctrl_c_pressed_once = True
                        print("\nInput cancelled. Press Ctrl+C again to exit.", file=sys.stderr)
                        # Continue the loop to prompt for input again
                        continue # Go to next loop iteration

                # --- If we get here, input was successful (not None) ---
                # Reset the flag *after* successful input, before processing
                ctrl_c_pressed_once = False

                # Strip leading/trailing whitespace
                processed_inp = inp.strip()
                if not processed_inp:
                    continue  # Skip empty input

                # Process the valid input
                status = self.run_one(processed_inp, preproc=True)
                if not status:
                    break  # Exit signal from run_one (e.g., /exit command)

            except KeyboardInterrupt:  # Handle Ctrl+C pressed *outside* the input function
                if ctrl_c_pressed_once:
                    print("\nExiting.", file=sys.stderr)
                    break # Exit on second consecutive Ctrl+C (one outside input, one before/during)
                else:
                    ctrl_c_pressed_once = True
                    print("\nOperation interrupted. Press Ctrl+C again to exit.", file=sys.stderr)
                    # Continue the loop to prompt for input again
                    continue
            except EOFError:  # Handle Ctrl+D (still treated as exit)
                print("\nExiting (EOF).", file=sys.stderr)
                break  # Exit on Ctrl+D

        self.logger.info("Goodbye! 👋")
