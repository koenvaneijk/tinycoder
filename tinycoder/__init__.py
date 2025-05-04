import argparse
import json
import logging
import os
import platform
import shlex
import subprocess
import sys
import traceback
from pathlib import Path
from typing import List, Set, Dict, Optional, Any, Tuple
import atexit # For readline history

try:
    import readline
    READLINE_AVAILABLE = True
except ImportError:
    # readline is not available on all platforms (e.g., standard Windows cmd)
    READLINE_AVAILABLE = False

from tinycoder.chat_history import ChatHistoryManager
from tinycoder.code_applier import CodeApplier
from tinycoder.command_handler import CommandHandler
from tinycoder.edit_parser import EditParser
from tinycoder.file_manager import FileManager
from tinycoder.git_manager import GitManager
# Ensure FileManager is imported if CommandCompleter uses it explicitly via type hint
from tinycoder.file_manager import FileManager
from tinycoder.llms import create_llm_client, LLMClient
from tinycoder.prompt_builder import PromptBuilder
from tinycoder.repo_map import RepoMap
from tinycoder.ui.console_interface import ring_bell
from tinycoder.ui.log_formatter import ColorLogFormatter, STYLES, COLORS as FmtColors, RESET
from tinycoder.ui.spinner import Spinner

import importlib.resources

APP_NAME = "tinycoder"
COMMIT_PREFIX = "tinycoder: "
HISTORY_FILE = ".tinycoder_history" # Define history file name


# --- Readline Configuration (only if available) ---

class CommandCompleter:
    """A readline completer class specifically for TinyCoder commands."""
    def __init__(self, file_manager: 'FileManager'):
        self.file_manager = file_manager
        self.file_options: List[str] = []
        self.matches: List[str] = []
        self._refresh_file_options() # Initial population
        # Add logger if not already present (assuming App passes it or it's globally accessible)
        self.logger = logging.getLogger(__name__) # Get logger instance


    def _refresh_file_options(self):
        """Fetches the list of relative file paths from the FileManager."""
        # Assuming FileManager has a method `get_all_repo_files`
        # If not, this needs to be added to FileManager.
        try:
            # Use file_manager's root for relativity if possible
            base_path = self.file_manager.root if self.file_manager.root else Path.cwd()
            # Attempt to get files relative to the repo/project root
            # TODO: Ensure get_all_repo_files() exists and returns relative paths.
            # For now, simulate with get_files() which might only contain added files.
            # Replace with a proper implementation later.
            # Placeholder using get_files() - needs update
            repo_files: Set[str] = set()
            base_path = self.file_manager.root if self.file_manager.root else Path.cwd()
            self.logger.debug(f"Refreshing file options for completion based on: {base_path}")

            # Use git_manager if available and in a repo
            if self.file_manager.git_manager and self.file_manager.git_manager.is_repo():
                tracked_files = self.file_manager.git_manager.get_tracked_files_relative()
                repo_files.update(tracked_files)
                self.logger.debug(f"Found {len(tracked_files)} tracked files via Git.")
            else:
                # Fallback: Walk the directory if not a git repo or git failed
                self.logger.debug("Not a Git repo or Git unavailable, walking the directory...")
                # Exclude common large/binary directories for performance
                excluded_dirs = {'.git', '__pycache__', 'node_modules', '.venv', 'venv'}
                for item in base_path.rglob('*'):
                    # Check if the item is within any excluded directory
                    if any(excluded in item.parts for excluded in excluded_dirs):
                        continue
                    if item.is_file():
                        try:
                            # Make path relative to the root used for walking
                            rel_path = item.relative_to(base_path)
                            # Normalize slashes for consistency
                            repo_files.add(str(rel_path).replace('\\', '/'))
                        except ValueError:
                            # Should not happen if item is from rglob relative to base_path
                            self.logger.warning(f"Could not make path relative: {item}")
                        except Exception as walk_err:
                            # Catch other potential errors during walk
                            self.logger.warning(f"Error processing path during walk: {item} - {walk_err}")
                self.logger.debug(f"Found {len(repo_files)} files via directory walk.")

            # Always include files explicitly added to the chat context,
            # even if they are untracked or outside the main discovery paths.
            context_files = self.file_manager.get_files()
            repo_files.update(context_files)
            if context_files:
                 self.logger.debug(f"Added {len(context_files)} files from current chat context.")

            self.file_options = sorted(list(repo_files))
            self.logger.debug(f"Total unique file options for completion: {len(self.file_options)}")

        except Exception as e:
            self.logger.error(f"Error refreshing file options for completion: {e}", exc_info=True)
            # Fallback to just the files currently in context in case of error
            self.file_options = sorted(list(self.file_manager.get_files()))


    def complete(self, text: str, state: int) -> Optional[str]:
        """Readline completion handler."""
        # Refresh file options on every completion attempt for dynamic updates
        # This might be slow for very large repos; consider caching if needed.
        if state == 0: # Refresh only on the first call for a new completion sequence
             self._refresh_file_options()

        line = readline.get_line_buffer()
        self.logger.debug(f"Readline complete called. Line: '{line}', Text: '{text}', State: {state}")

        # --- Completion logic for /add ---
        add_prefix = "/add "
        if line.startswith(add_prefix):
            # Path completion after /add
            path_text = line[len(add_prefix):] # The part after "/add "

            if state == 0:
                # First call for this completion
                # 'text' passed by readline is the word fragment it identified based on delimiters
                # For '/add src/m', text should ideally be 'src/m'
                # We need to find options that *start with* the path_text derived from the line
                self.matches = sorted([
                    p for p in self.file_options
                    if p.startswith(path_text)
                ])
                self.logger.debug(f"Path text: '{path_text}', Options: {len(self.file_options)}, Matches found: {len(self.matches)}")
                self.logger.debug(f"Matches: {self.matches[:5]}...") # Log first few matches

            try:
                # Readline expects the *completion* relative to 'text',
                # or the full word if 'text' was empty.
                # Since path_text is the part *after* '/add ', our matches ARE the full paths.
                # Readline will handle replacing 'text' with the returned match.
                match = self.matches[state]
                self.logger.debug(f"Returning match {state}: '{match}' (relative to path_text: '{path_text}')")
                # Return the full path match. Readline should handle the replacement correctly
                # if delimiters are set properly.
                return match
            except IndexError:
                # No more matches
                self.logger.debug(f"No more matches for state {state}")
                return None

        # --- Add completion for other commands if needed ---
        # Example: /drop
        # drop_prefix = "/drop "
        # if line.startswith(drop_prefix):
        #    ... (similar logic using self.file_manager.get_files())

        # --- Default: No completion if not a recognized command prefix ---
        # self.logger.debug("Line doesn't match known completion prefixes.")
        self.matches = []
        return None


# --- End Readline Configuration ---



class App:
    def __init__(self, model: Optional[str], files: List[str], continue_chat: bool):
        """Initializes the TinyCoder application."""
        self._setup_logging()
        self._init_llm_client(model)
        self._init_spinner()
        self._setup_git()
        self._init_core_managers(continue_chat)
        self._init_prompt_builder()
        self._setup_rules()
        self._init_app_state()
        self._init_command_handler()
        # Configure readline *after* core managers (like file_manager) are ready
        self._configure_readline()
        self._init_app_components() # Determines input func based on readline availability
        self._log_final_status()
        self._add_initial_files(files)


    def _setup_logging(self) -> None:
        """Configures the root logger with colored output."""
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.INFO) # Or logging.DEBUG for more verbosity

        # Remove existing handlers to prevent duplicates
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)

        ch = logging.StreamHandler(sys.stdout)
        ch.setLevel(logging.INFO) # Only INFO and above will be shown via this handler

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

    def _setup_rules(self) -> None:
        """Determines project identifier, config paths, discovers and loads rules."""
        # Determine project identifier based on final git_root status
        self.project_identifier = self._get_project_identifier()
        self.logger.debug(f"Project identifier set to: {self.project_identifier}")

        # Determine config path based on OS
        if platform.system() == "Windows":
            config_dir = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / APP_NAME
        elif platform.system() == "Darwin": # macOS
            config_dir = Path.home() / "Library" / "Application Support" / APP_NAME
        else: # Linux and other Unix-like systems
            config_dir = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / APP_NAME
        self.rules_config_path = config_dir / "rules_config.json"
        self.logger.debug(f"Rules configuration path: {self.rules_config_path}")

        # Discover and load rules
        self.discovered_rules: Dict[str, Dict[str, Any]] = {}
        self.active_rules_content: str = ""
        self._discover_rules() # Calls the discovery method
        self._load_active_rules() # Loads enabled rules based on discovery and config

    def _init_app_state(self) -> None:
        """Initializes basic application state variables."""
        self.coder_commits: Set[str] = set()
        self.mode = "code" # Default mode
        self.lint_errors_found: Dict[str, str] = {}
        self.reflected_message: Optional[str] = None
        self.logger.debug("Basic app state initialized (commits, mode, lint status).")

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
            enable_rule_func=self.enable_rule,
            disable_rule_func=self.disable_rule,
            list_rules_func=self.list_rules,
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
        # Determine primary input function for main loop
        self.input_func = self._get_input_function()
        self.logger.debug("App components (Parser, Applier, Input Func) initialized.")

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

    # --- Rule Management Methods ---

    def _load_rules_config(self) -> Dict[str, Any]:
        """Loads the global rules configuration from the JSON file."""
        if not self.rules_config_path.exists():
            return {}
        try:
            with open(self.rules_config_path, "r", encoding="utf-8") as f:
                config = json.load(f)
                # Basic validation: ensure it's a dictionary
                if not isinstance(config, dict):
                    self.logger.error(f"Invalid format in {self.rules_config_path}. Expected a JSON object. Ignoring config.")
                    return {}
                return config
        except json.JSONDecodeError:
            self.logger.error(f"Error decoding JSON from {self.rules_config_path}. Ignoring config.")
            return {}
        except Exception as e:
            self.logger.error(f"Failed to read rules config {self.rules_config_path}: {e}")
            return {}

    def _save_rules_config(self, config: Dict[str, Any]):
        """Saves the global rules configuration to the JSON file."""
        try:
            # Ensure the directory exists
            self.rules_config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.rules_config_path, "w", encoding="utf-8") as f:
                json.dump(config, f, indent=2)
        except Exception as e:
            self.logger.error(f"Failed to save rules config to {self.rules_config_path}: {e}")

    def _configure_readline(self):
        """Configures readline for history and command completion if available."""
        if not READLINE_AVAILABLE:
            self.logger.info("Readline module not available. Skipping history and completion setup.")
            # Optionally print a warning for the user if desired, but logger covers it.
            # print("Warning: readline not available. Tab completion and history disabled.", file=sys.stderr)
            return

        self.logger.debug("Readline available. Configuring...")

        # --- Completion Setup ---
        try:
            completer_instance = CommandCompleter(self.file_manager)
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

    def _save_readline_history(self):
        """Saves the readline history to the designated file."""
        if not READLINE_AVAILABLE:
            return
        try:
            readline.write_history_file(self.history_file)
            self.logger.debug(f"Readline history saved to {self.history_file}")
        except Exception as e:
            self.logger.error(f"Failed to save readline history to {self.history_file}: {e}")


    def _discover_rules(self):
        """Discovers built-in and custom rules."""
        self.discovered_rules = {}
        num_built_in = 0
        num_custom = 0

        # 1. Discover Built-in Rules
        try:
            builtin_rules_pkg = "tinycoder.rules"
            # Use files() for modern importlib.resources usage
            if sys.version_info >= (3, 9):
                resource_files = importlib.resources.files(builtin_rules_pkg)
                for item in resource_files.iterdir():
                    if item.is_file() and item.name.endswith(".md") and item.name != "__init__.py":
                        rule_name = item.stem
                        title = rule_name.replace("_", " ").title()
                        self.discovered_rules[rule_name] = {
                            "type": "builtin",
                            "path": item.name, # Store resource name relative to package
                            "title": title,
                        }
                        num_built_in += 1
            else: # Fallback for older Python versions (less direct)
                 # This path is less robust, relying on __path__ which might not always work perfectly
                 import tinycoder.builtin_rules as rules_module
                 if hasattr(rules_module, '__path__'):
                     pkg_path = Path(rules_module.__path__[0])
                     for rule_file in pkg_path.glob("*.md"):
                         if rule_file.is_file() and rule_file.name != "__init__.py":
                            rule_name = rule_file.stem
                            title = rule_name.replace("_", " ").title()
                            self.discovered_rules[rule_name] = {
                                "type": "builtin",
                                "path": rule_file.name, # Store filename relative to package dir
                                "title": title,
                             }
                            num_built_in += 1


        except (ModuleNotFoundError, FileNotFoundError, Exception) as e:
            self.logger.warning(f"Could not discover built-in rules: {e}")

        # 2. Discover Custom Rules
        base_dir = Path(self.git_root) if self.git_root else Path.cwd()
        custom_rules_dir = base_dir / ".tinycoder" / "rules"
        if custom_rules_dir.is_dir():
            for rule_file in custom_rules_dir.glob("*.md"):
                if rule_file.is_file():
                    rule_name = rule_file.stem
                    title = rule_name.replace("_", " ").title()
                    # Custom rules overwrite built-in ones if names clash
                    if rule_name in self.discovered_rules and self.discovered_rules[rule_name]['type'] == 'builtin':
                       self.logger.info(f"Custom rule '{rule_name}' overrides built-in rule.")
                       num_built_in -= 1 # Decrement built-in count as it's overridden

                    self.discovered_rules[rule_name] = {
                        "type": "custom",
                        "path": rule_file.resolve(), # Store absolute Path for custom rules
                        "title": title,
                    }
                    num_custom += 1

        self.logger.debug(f"Discovered {num_built_in} built-in rule(s) and {num_custom} custom rule(s).")


    def _get_enabled_rules_for_project(self) -> Set[str]:
        """Gets the set of enabled rule names for the current project from the config."""
        config = self._load_rules_config()
        project_config = config.get(self.project_identifier, {})
        # Ensure 'enabled_rules' exists and is a list, default to empty list
        enabled_rules = project_config.get("enabled_rules", [])
        if not isinstance(enabled_rules, list):
            self.logger.warning(f"Invalid 'enabled_rules' format for project {self.project_identifier} in config. Expected a list, found {type(enabled_rules)}. Using empty list.")
            return set()
        return set(enabled_rules)


    def _load_active_rules(self):
        """Loads content of enabled rules (built-in and custom) for the current project."""
        enabled_rule_names = self._get_enabled_rules_for_project()
        active_rules_content_parts = []
        loaded_rule_names = set() # Track loaded to ensure precedence

        # Load custom rules first to ensure they have precedence
        for rule_name, rule_info in self.discovered_rules.items():
             if rule_name in enabled_rule_names and rule_info["type"] == "custom":
                try:
                    content = rule_info["path"].read_text(encoding="utf-8")
                    active_rules_content_parts.append(
                        f"### Rule: {rule_info['title']}\n\n{content.strip()}\n"
                    )
                    loaded_rule_names.add(rule_name)
                except Exception as e:
                     self.logger.error(f"Failed to read custom rule file {rule_info['path']}: {e}")

        # Load enabled built-in rules only if not already loaded as custom
        for rule_name, rule_info in self.discovered_rules.items():
            if rule_name in enabled_rule_names and rule_info["type"] == "builtin" and rule_name not in loaded_rule_names:
                try:
                    # Use importlib.resources to read built-in content
                    builtin_rules_pkg = "tinycoder.rules"
                    # Ensure path is treated as resource name within package
                    resource_name = str(rule_info['path'])
                    content = importlib.resources.read_text(builtin_rules_pkg, resource_name, encoding="utf-8")
                    active_rules_content_parts.append(
                        f"### Rule: {rule_info['title']}\n\n{content.strip()}\n"
                    )
                    loaded_rule_names.add(rule_name)
                except Exception as e:
                    self.logger.error(f"Failed to read built-in rule resource {rule_info['path']}: {e}")


        self.active_rules_content = "\n".join(active_rules_content_parts)
        if loaded_rule_names:
             self.logger.info(f"Loaded {len(loaded_rule_names)} active rule(s) for this project: {', '.join(sorted(loaded_rule_names))}")
        else:
             self.logger.info("No active rules enabled or loaded for this project.")

    def _get_rule_content(self, rule_name: str) -> Optional[str]:
        """Reads the content of a specific rule (built-in or custom)."""
        if rule_name not in self.discovered_rules:
            self.logger.error(f"Attempted to get content for unknown rule: {rule_name}")
            return None

        rule_info = self.discovered_rules[rule_name]
        try:
            if rule_info["type"] == "custom":
                return rule_info["path"].read_text(encoding="utf-8")
            elif rule_info["type"] == "builtin":
                builtin_rules_pkg = "tinycoder.rules"
                resource_name = str(rule_info['path'])
                return importlib.resources.read_text(builtin_rules_pkg, resource_name, encoding="utf-8")
            else:
                self.logger.error(f"Unknown rule type '{rule_info['type']}' for rule '{rule_name}'")
                return None
        except Exception as e:
            self.logger.error(f"Failed to read content for rule '{rule_name}': {e}")
            return None


    def list_rules(self) -> str:
        """
        Returns a formatted string listing discovered rules and their status,
        separated by type, sorted alphabetically, and including token estimates.
        """
        if not self.discovered_rules:
            return "No rules (built-in or custom) discovered."

        enabled_rules = self._get_enabled_rules_for_project()
        builtin_lines = []
        custom_lines = []

        # Separate and sort rules
        sorted_rule_names = sorted(self.discovered_rules.keys())

        for rule_name in sorted_rule_names:
            rule_info = self.discovered_rules[rule_name]
            status_marker = "[✓]" if rule_name in enabled_rules else "[ ]"

            # Get content to calculate tokens
            content = self._get_rule_content(rule_name)
            token_estimate = len(content) // 4 if content else 0
            token_str = f" (~{token_estimate} tokens)"

            if rule_info['type'] == 'builtin':
                builtin_lines.append(f" {status_marker} {rule_name}{token_str}")
            elif rule_info['type'] == 'custom':
                # Show relative path for custom rules if possible
                try:
                    rel_path = rule_info['path'].relative_to(Path.cwd())
                    origin = f"(./{rel_path})"
                except ValueError: # If path is not relative to CWD
                    origin = f"({rule_info['path']})"
                custom_lines.append(f" {status_marker} {rule_name}{token_str} {origin}")
            else:
                 # Should not happen, but good to handle
                 self.logger.warning(f"Skipping rule '{rule_name}' with unknown type '{rule_info['type']}'.")

        output_lines = []
        if builtin_lines:
            output_lines.append("--- Built-in Rules ---")
            output_lines.extend(builtin_lines)
        if custom_lines:
            if output_lines: # Add separator if built-in rules were listed
                 output_lines.append("")
            output_lines.append("--- Custom Rules ---")
            output_lines.extend(custom_lines)

        if not output_lines: # Case where discovery finds something but it's an unknown type
            return "No valid built-in or custom rules discovered to list."

        return "\n".join(output_lines)


    def enable_rule(self, rule_name: str) -> bool:
        """Enables a rule for the current project and reloads active rules."""
        if rule_name not in self.discovered_rules:
            self.logger.error(f"Rule '{rule_name}' not found.")
            return False

        config = self._load_rules_config()
        project_config = config.setdefault(self.project_identifier, {"enabled_rules": []})
        # Ensure 'enabled_rules' is a list within the project config
        if not isinstance(project_config.get("enabled_rules"), list):
            project_config["enabled_rules"] = [] # Reset if invalid type found

        if rule_name not in project_config["enabled_rules"]:
            project_config["enabled_rules"].append(rule_name)
            self._save_rules_config(config)
            self._load_active_rules() # Reload active rules
            self.logger.info(f"Rule '{rule_name}' enabled for this project.")
        else:
            self.logger.info(f"Rule '{rule_name}' is already enabled.")
        return True


    def disable_rule(self, rule_name: str) -> bool:
        """Disables a rule for the current project and reloads active rules."""
        if rule_name not in self.discovered_rules:
            # Don't error if trying to disable a non-existent rule, just inform.
            self.logger.warning(f"Rule '{rule_name}' not found, cannot disable.")
            return False # Indicate rule wasn't found, though not strictly an error state

        config = self._load_rules_config()
        project_config = config.get(self.project_identifier)
        if not project_config or "enabled_rules" not in project_config or rule_name not in project_config["enabled_rules"]:
            self.logger.info(f"Rule '{rule_name}' is not currently enabled, nothing to disable.")
            return True # Indicate success as the rule is effectively disabled

        # Proceed with removal if the rule is present
        try:
            project_config["enabled_rules"].remove(rule_name)
            self._save_rules_config(config)
            self._load_active_rules() # Reload active rules
            self.logger.info(f"Rule '{rule_name}' disabled for this project.")
            return True
        except ValueError: # Should not happen with the 'in' check, but defensive
            self.logger.info(f"Rule '{rule_name}' was not found in the enabled list (concurrent modification?).")
            return True # Still effectively disabled
        except Exception as e:
            self.logger.error(f"Error disabling rule '{rule_name}': {e}")
            return False

    # --- End Rule Management Methods ---

    def _get_multiline_input_readline(self):
        """
        Gets multi-line input using readline (if available), terminated by Ctrl+D.
        Handles prompts and Ctrl+C cancellation.
        """
        lines = []
        # Determine the correct instruction based on the OS
        if platform.system() == "Windows":
             # Readline might be available via pyreadline3, but Ctrl+Z is more standard there
            finish_instruction = "(Ctrl+Z then Enter to finish on Windows)"
        else:
            finish_instruction = "(Ctrl+D to finish)" # Standard Unix-like

        print(f"Enter text {finish_instruction}:")

        # Mode prefix for the prompt
        mode_prefix = f"{STYLES['BOLD']}{FmtColors['GREEN']}({self.mode}){RESET} "
        prompt = f"{mode_prefix}> "

        while True:
            try:
                # Use input() to leverage readline's line editing, history, and completion
                line = input(prompt)
                lines.append(line)
                # Change prompt for subsequent lines (optional, but common)
                # Keep it simple for now
                # prompt = f"{mode_prefix}.. "
            except EOFError: # Handle Ctrl+D (or Ctrl+Z+Enter on Windows sometimes)
                print() # Print a newline for cleaner exit after EOF
                break
            except KeyboardInterrupt: # Handle Ctrl+C
                print("\nInput cancelled (Ctrl+C).")
                return None # Indicate cancellation

        return "\n".join(lines)

    # This function remains, but its logic is simplified by _get_multiline_input_readline
    def _get_multiline_input_stdin(self):
         """Gets multi-line input by reading stdin until EOF (fallback)."""
         # Determine the correct instruction based on the OS
         if platform.system() == "Windows":
             message = "Enter text (Ctrl+Z then Enter to finish):"
         else:
             message = "Enter text (Ctrl+D to finish):"

         print(message)
         # Mode prefix for the prompt - print once before stdin.read()
         mode_prefix = f"{STYLES['BOLD']}{FmtColors['GREEN']}({self.mode}){RESET} "
         print(f"{mode_prefix}> ", end="", flush=True)
         try:
             user_input = sys.stdin.read()
             # .read() often includes the final newline if the user pressed Enter
             # before Ctrl+D/Ctrl+Z. You might want to strip trailing whitespace.
             return user_input.rstrip()
         except KeyboardInterrupt:
             print("\nInput cancelled (Ctrl+C).")
             return None  # Return None to signal cancellation
         except Exception as e:
             print(f"\nAn unexpected error occurred reading stdin: {e}")
             return None  # Return None on error

    def _get_input_function(self):
        """Returns the appropriate input function based on readline availability and OS."""
        if READLINE_AVAILABLE and platform.system() != "Windows":
            # Use readline-based input on non-Windows where it's generally more reliable
            self.logger.debug("Using readline-based multi-line input function.")
            return self._get_multiline_input_readline
        elif platform.system() == "Windows":
             # On Windows, default to single-line input() if readline isn't working well,
             # or potentially use _get_multiline_input_stdin if that's preferred.
             # Let's stick with standard `input` for simplicity unless readline is confirmed robust.
             # Check if pyreadline3 might be installed and usable
             if READLINE_AVAILABLE:
                 self.logger.debug("Readline detected on Windows, using readline-based multi-line input.")
                 # Try using the readline function on Windows too, relies on pyreadline3 behaving well
                 return self._get_multiline_input_readline
             else:
                  self.logger.debug("Readline not available on Windows, falling back to single-line input().")
                  # Fallback to standard input for single lines
                  return input # Simple single-line input
        else:
            # Fallback for non-Windows non-readline scenarios (unlikely)
            self.logger.debug("Readline not available, falling back to basic multi-line stdin read.")
            return self._get_multiline_input_stdin

    def _send_to_llm(self) -> Optional[str]:
        """Sends the current chat history and file context to the LLM."""
        current_history = self.history_manager.get_history()
        if not current_history or current_history[-1]["role"] != "user":
            self.logger.error("Cannot send to LLM without a user message.")
            return None

        # Use PromptBuilder to build the system prompt
        # Pass the loaded active rules content instead of the old custom_rules_content
        system_prompt_content = self.prompt_builder.build_system_prompt(
            self.mode, self.active_rules_content # Use the loaded active rules
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
            
            self.logger.info(f"Total tokens: {total_tokens}")

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
                self.logger.info("ASSISTANT: " + response_content)  # Print the response
                n_tokens = len(response_content)/4
                self.logger.info("Response tokens: %d", n_tokens)
            
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

    def check_for_file_mentions(self, inp: str):
        """Placeholder: Checks for file mentions in user input."""
        # TODO: Implement logic to find potential file paths in `inp`
        # and maybe suggest adding them using self.add_file() or print a warning.
        pass  # Currently does nothing

    def check_for_urls(self, inp: str) -> str:
        """Placeholder: Checks for URLs in user input."""
        # TODO: Implement logic to find URLs. Could potentially fetch content
        # or just return the input string unchanged.
        return inp  # Currently returns input unchanged

    def preproc_user_input(self, inp):
        """Checks for file mentions and URLs in regular user input."""
        # This method is now separate from _handle_command
        # It should return the potentially modified input string
        self.check_for_file_mentions(inp)
        inp = self.check_for_urls(inp)
        return inp

    def process_user_input(self):
        """Processes the latest user input (already in history), sends to LLM, handles response."""
        # Note: is_command_context is removed as this function no longer handles commands directly
        response = self._send_to_llm()

        # Mode reversion is handled in run_one after this function returns

        if response:
            self.history_manager.add_message(
                "assistant", response
            )

            # Only try to parse and apply edits if in code mode
            if self.mode == "code":
                edits = self.edit_parser.parse(response)
                if edits:
                    # MODIFIED: Unpack new return values from apply_edits
                    all_succeeded, failed_indices, modified_files, lint_errors = (
                        self.code_applier.apply_edits(edits)
                    )
                    self.lint_errors_found = (
                        lint_errors  # Update App state for lint errors regardless
                    )

                    if all_succeeded:
                        # All edits processed successfully (though maybe no changes occurred)
                        if modified_files:
                            self.logger.info("All edits applied successfully.")
                            self._git_add_commit(
                                list(modified_files)
                            )  # Commit only the modified files
                        else:
                            self.logger.info("Edits processed, but no files were changed.")
                    elif failed_indices:
                        # Some edits failed
                        failed_indices_str = ", ".join(map(str, sorted(failed_indices)))
                        error_message = (
                            f"Some edits failed to apply. No changes have been committed.\n"
                            f"Please review and provide corrected edit blocks for the failed edits.\n\n"
                            f"Failed edit block numbers (1-based): {failed_indices_str}\n\n"
                            f"Successfully applied edits (if any) have modified the files in memory, "
                            f"but you should provide corrections for the failed ones before proceeding."
                        )
                        self.logger.error(error_message)
                        self.reflected_message = (error_message)
                        # DO NOT COMMIT
                    # else: # This case (not all_succeeded and not failed_indices) shouldn't happen

                else:  # No edits found by parser
                    # Check if the LLM just output code without the edit block format
                    # Use the parser's regex for consistency
                    code_block_match = self.edit_parser.edit_block_pattern.search(
                        response
                    )
                    # Check if the *whole* response is just a code block (allow it),
                    # but warn if code appears *within* text without the block format.
                    is_just_code = response.strip().startswith(
                        "```"
                    ) and response.strip().endswith("```")
                    if code_block_match and not is_just_code:
                        self.logger.warning(
                            "The LLM provided code but didn't use the required edit format. No changes applied.",
                        )
                    elif not code_block_match:  # No edits and no code blocks found
                        self.logger.info("No edit blocks found in the response.")

                # --- Check for Lint Errors ---
                if self.lint_errors_found:
                    error_messages = ["Found syntax errors after applying edits:"]
                    for fname, error in self.lint_errors_found.items():
                        error_messages.append(f"\n--- Errors in {fname} ---\n{error}")
                    combined_errors = "\n".join(error_messages)
                    self.logger.error(combined_errors)

                    ring_bell()
                    fix_lint = input("Attempt to fix lint errors? (y/N): ")
                    if fix_lint.lower() == "y":
                        self.reflected_message = (
                            combined_errors  # Set message for next LLM call
                        )
                        # The loop in run_one will handle sending this reflected message
                    # else: lint errors are ignored for this round

    def _ask_llm_for_files(self, instruction: str) -> List[str]:
        """Asks the LLM to identify files needed for a given instruction."""
        self.logger.info("Asking LLM to identify relevant files...")

        # Use PromptBuilder to build the identify files prompt
        system_prompt = self.prompt_builder.build_identify_files_prompt()

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
                cmd_str = user_message[1:].strip()
                if not cmd_str:
                    self.logger.error("Usage: !<shell_command>")
                    return True  # Continue main loop, don't process further

                self.logger.info(f"Executing command: {cmd_str}")
                try:
                    # Use shlex.split for safer argument handling
                    cmd_args = shlex.split(cmd_str)
                    # Determine working directory
                    cwd = Path(self.git_root) if self.git_root else Path.cwd()
                    # Execute the command
                    result = subprocess.run(
                        cmd_args,
                        capture_output=True,
                        text=True,
                        check=False,  # Don't raise exception on non-zero exit code
                        cwd=cwd,
                    )

                    # --- START MODIFICATION ---

                    # 1. Capture combined output
                    command_output_parts = []
                    stdout_content = result.stdout.strip() if result.stdout else ""
                    stderr_content = result.stderr.strip() if result.stderr else ""

                    if stdout_content:
                        command_output_parts.append(f"--- stdout ---\n{stdout_content}")
                    if stderr_content:
                        command_output_parts.append(f"--- stderr ---\n{stderr_content}")

                    combined_output = "\n".join(command_output_parts)
                    full_output_for_history = (
                        f"Output of command: `{cmd_str}`\n{combined_output}"
                    )

                    # Print output/error to console (as before)
                    print("--- Command Output ---")
                    if stdout_content:
                        print(stdout_content)  # Use plain print for console
                    if stderr_content:
                        self.logger.error(
                            f"stderr:\n{stderr_content}"
                        )  # Use helper for color
                    if result.returncode != 0:
                        self.logger.warning(
                            f"Command exited with code {result.returncode}"
                        )
                    print("--- End Command Output ---")

                    # 2. Prompt the user (only if there was output)
                    if (
                        combined_output and not non_interactive
                    ):  # Only ask in interactive mode
                        add_to_context = input(
                            "Add command output to chat context? (y/N): "
                        )
                        # 3. Conditionally add to history
                        if add_to_context.lower() == "y":
                            self.history_manager.add_message(
                                "tool", full_output_for_history
                            )
                            self.logger.info("Command output added to chat context.")

                    # --- END MODIFICATION ---

                except FileNotFoundError:
                    self.logger.error(f"Command not found: {cmd_args[0]}")
                except Exception as e:
                    self.logger.error(f"Error executing command: {e}")

                return True  # Command handled, stop further processing for this input cycle

            else:
                message = self.preproc_user_input(user_message)
                if (
                    message is False
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
                f"Reflection {num_reflections}: Sending feedback to LLM..."
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
        # Use FmtColors and STYLES for the welcome message
        # Apply specific color (GREEN) before BOLD, then RESET immediately after.
        # The rest of the message will use the default INFO format (terminal default color).
        self.logger.info(
            f"Welcome to {FmtColors['GREEN']}{STYLES['BOLD']}{APP_NAME}{RESET}! Model: {FmtColors['GREEN']}{STYLES['BOLD']}{self.model}{RESET}. Type /help for commands, !<cmd> to run shell commands.",
        )

        while True:
            try:
                ring_bell()  # Ring the bell before input

                # Get input using the determined function
                # The function itself now handles the prompt including the mode prefix
                inp = self.input_func()

                if inp is None:
                    # Input was cancelled (Ctrl+C in readline loop or stdin read)
                    # or failed. Let's exit gracefully if it was cancellation.
                    # Check if it was KeyboardInterrupt in the readline case
                    # For simplicity, let's assume None means exit requested or failed input.
                    print("Input cancelled or failed. Exiting.")
                    break # Exit main loop


                # Strip leading/trailing whitespace from the whole multi-line input
                processed_inp = inp.strip()
                if not processed_inp:
                    continue  # Skip empty input

                status = self.run_one(processed_inp, preproc=True)
                if not status:
                    break  # Exit signal from run_one (e.g., /exit command)

            except KeyboardInterrupt:  # Handle Ctrl+C
                print()
                break  # Exit on Ctrl+C
            except EOFError:  # Handle Ctrl+D (now treated as exit)
                print()
                break  # Exit on Ctrl+D

        self.logger.info("Goodbye! 👋")


def main():
    print(r"""  _   _                     _         
 | |_(_)_ _ _  _ __ ___  __| |___ _ _ 
 |  _| | ' \ || / _/ _ \/ _` / -_) '_|
  \__|_|_||_\_, \__\___/\__,_\___|_|  
            |__/                      
          """)

    parser = argparse.ArgumentParser(
        description=f"{APP_NAME} - A simplified AI coding assistant."
    )
    parser.add_argument(
        "files",
        metavar="FILE",
        nargs="*",
        help="Files to add to the chat context on startup.",
    )
    parser.add_argument(
        "--model",
        metavar="MODEL_NAME",
        default=None,
        help=(
            "LLM model to use. Determines the API provider. "
            "Prefix with 'gemini-' or 'deepseek-' for those providers. "
            "Any other name (or no prefix) assumes a locally running Ollama model (e.g., 'llama3', 'mistral:7b'). "
            "If completely unspecified, defaults to Gemini. "
            "Set OLLAMA_HOST environment variable if your Ollama server isn't at http://localhost:11434."
        ),
    )
    parser.add_argument(
        "--code",
        metavar="INSTRUCTION",
        default=None,
        help="Execute a code command directly without interactive mode. Applies edits and commits changes.",
    )
    parser.add_argument(
        "--continue-chat",
        action="store_true",
        help="Continue from previous chat history instead of starting fresh.",
    )
    args = parser.parse_args()

    # Readline configuration is now handled within App.__init__
    # No need for readline setup here anymore.

    coder = App(model=args.model, files=args.files, continue_chat=args.continue_chat)

    if args.code:
        coder.mode = "code"
        coder.run_one(args.code, preproc=False, non_interactive=True)

    else:
        coder.run()

if __name__ == "__main__":
    main()
