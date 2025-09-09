import logging
import sys
from pathlib import Path
from typing import List, Optional

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.styles import Style

from tinycoder.app import App
from tinycoder.chat_history import ChatHistoryManager
from tinycoder.edit_parser import EditParser
from tinycoder.file_manager import FileManager
from tinycoder.git_manager import GitManager
from tinycoder.input_preprocessor import InputPreprocessor
from tinycoder.llms import create_llm_client
from tinycoder.prompt_builder import PromptBuilder
from tinycoder.repo_map import RepoMap
from tinycoder.rule_manager import RuleManager
from tinycoder.shell_executor import ShellExecutor
from tinycoder.ui.command_completer import PTKCommandCompleter
from tinycoder.ui.console_interface import prompt_user_input
from tinycoder.ui.log_formatter import (
    ColorLogFormatter,
    PromptToolkitLogHandler,
    STYLES,
    COLORS as FmtColors,
    RESET,
)
import tinycoder.config as config
from tinycoder.docker_manager import DockerManager


class AppBuilder:
    """Builds the App instance and all its dependencies."""
    def __init__(self, model: Optional[str], files: List[str], continue_chat: bool, verbose: bool = False):
        self.model_arg = model
        self.files = files
        self.continue_chat = continue_chat
        self.verbose = verbose

    def build(self) -> App:
        """Constructs and returns a fully initialized App instance."""
        self._setup_logging()
        self._init_llm_client()
        self._setup_git()
        self._init_core_managers()
        self._setup_docker()
        self._init_prompt_builder()
        self._setup_rules_manager()
        self._init_prompt_session_and_style()
        self._reconfigure_logging_for_ptk()
        self._init_input_preprocessor()
        self._init_simple_components()

        app = App(
            logger=self.logger,
            client=self.client,
            model=self.model,
            git_manager=self.git_manager,
            git_root=self.git_root,
            file_manager=self.file_manager,
            history_manager=self.history_manager,
            repo_map=self.repo_map,
            docker_manager=self.docker_manager,
            prompt_builder=self.prompt_builder,
            rule_manager=self.rule_manager,
            input_preprocessor=self.input_preprocessor,
            edit_parser=self.edit_parser,
            shell_executor=self.shell_executor,
            prompt_session=self.prompt_session,
            style=self.style,
        )

        app._add_initial_files(self.files)
        self._log_final_status(app)
        return app

    def _setup_logging(self) -> None:
        root_logger = logging.getLogger()
        root_logger.setLevel(logging.DEBUG if self.verbose else logging.INFO)
        for handler in root_logger.handlers[:]:
            root_logger.removeHandler(handler)
        ch = logging.StreamHandler(sys.stdout)
        ch.setLevel(logging.DEBUG if self.verbose else logging.INFO)
        formatter = ColorLogFormatter(
            fmt="%(levelname)s: %(message)s",
            level_formats={
                logging.DEBUG: f"{FmtColors['GREY']}DEBUG:{RESET} %(message)s",
                logging.INFO: "%(message)s",
                logging.WARNING: f"{STYLES['BOLD']}{FmtColors['YELLOW']}WARNING:{RESET} %(message)s",
                logging.ERROR: f"{STYLES['BOLD']}{FmtColors['RED']}ERROR:{RESET} {FmtColors['RED']}%(message)s{RESET}",
                logging.CRITICAL: f"{STYLES['BOLD']}{FmtColors['RED']}CRITICAL:{RESET} {STYLES['BOLD']}{FmtColors['RED']}%(message)s{RESET}",
            },
            use_color=None
        )
        ch.setFormatter(formatter)
        root_logger.addHandler(ch)
        self.logger = logging.getLogger(__name__)
        self.logger.debug("Logging setup complete.")

    def _init_llm_client(self) -> None:
        try:
            self.client = create_llm_client(self.model_arg)
            self.model = self.client.model
            self.logger.debug(f"LLM Client initialized with model: {self.model}")
        except ValueError as e:
            self.logger.error(f"Failed to initialize LLM client: {e}", exc_info=True)
            print(f"{FmtColors['RED']}Error: Failed to initialize LLM client. {e}{RESET}", file=sys.stderr)
            print("Please check model name or API key environment variables.", file=sys.stderr)
            sys.exit(1)

    def _setup_git(self) -> None:
        self.git_manager = GitManager()
        self.git_root = None
        if not self.git_manager.is_git_available():
            self.logger.warning("Git command not found. Proceeding without Git integration.")
            return
        self.git_root = self.git_manager.get_root()
        if self.git_root is None:
            self.logger.warning(f"Git is available, but no .git directory found starting from {Path.cwd()}.")
            response = prompt_user_input(f"{FmtColors['YELLOW']}Initialize a new Git repository here? (y/N): {RESET}")
            if response.lower() == 'y':
                if self.git_manager.initialize_repo():
                    self.git_root = self.git_manager.get_root()
                    if self.git_root:
                        self.logger.info(f"Git repository initialized. Root: {FmtColors['CYAN']}{self.git_root}{RESET}")
                    else:
                        self.logger.error("Git initialization reported success, but failed to find root afterwards.")
                else:
                    self.logger.error("Git initialization failed.")
            else:
                self.logger.warning("Proceeding without Git integration.")
        else:
            self.logger.debug(f"Found existing Git repository. Root: {FmtColors['CYAN']}{self.git_root}{RESET}")

    def _init_core_managers(self) -> None:
        self.file_manager = FileManager(self.git_root, prompt_user_input)
        self.history_manager = ChatHistoryManager(continue_chat=self.continue_chat)
        self.repo_map = RepoMap(self.git_root)
        self.logger.debug("Core managers (File, History, RepoMap) initialized.")

    def _setup_docker(self) -> None:
        project_root = Path(self.git_root) if self.git_root else Path.cwd()
        try:
            self.docker_manager = DockerManager(project_root, self.logger)
            if not self.docker_manager.is_available:
                self.docker_manager = None
                self.logger.debug("Docker integration disabled.")
            else:
                self.logger.debug("DockerManager initialized successfully.")
        except Exception as e:
            self.logger.warning(f"Could not initialize Docker integration: {e}", exc_info=self.verbose)
            self.docker_manager = None

    def _init_prompt_builder(self) -> None:
        self.prompt_builder = PromptBuilder(self.file_manager, self.repo_map)
        self.logger.debug("PromptBuilder initialized.")

    def _get_project_identifier(self) -> str:
        return str(Path(self.git_root).resolve()) if self.git_root else str(Path.cwd().resolve())

    def _setup_rules_manager(self) -> None:
        project_identifier = self._get_project_identifier()
        config_dir = config.get_config_dir()
        rules_config_path = config_dir / "rules_config.json"
        base_dir_for_rules = Path(self.git_root) if self.git_root else Path.cwd()
        self.rule_manager = RuleManager(
            project_identifier=project_identifier,
            rules_config_path=rules_config_path,
            base_dir=base_dir_for_rules,
            logger=self.logger
        )
        self.logger.debug("RuleManager initialized.")

    def _init_prompt_session_and_style(self) -> None:
        self.style = Style.from_dict({
            'prompt.mode': 'bold fg:ansigreen', 'prompt.separator': 'fg:ansibrightblack',
            'rprompt.tokens.low': 'fg:ansigreen', 'rprompt.tokens.medium': 'fg:ansiyellow',
            'rprompt.tokens.high': 'fg:ansired', 'rprompt.text': 'fg:ansibrightblack',
            'bottom-toolbar': 'bg:#222222 fg:#aaaaaa', 'bottom-toolbar.low': 'bg:#222222 fg:ansigreen bold',
            'bottom-toolbar.medium': 'bg:#222222 fg:ansiyellow bold', 'bottom-toolbar.high': 'bg:#222222 fg:ansired bold',
            'assistant.header': 'bold fg:ansicyan', 'markdown.h1': 'bold fg:ansiblue',
            'markdown.h2': 'bold fg:ansimagenta', 'markdown.h3': 'bold fg:ansicyan',
            'markdown.bold': 'bold', 'markdown.code': 'fg:ansiyellow',
            'markdown.code-block': 'fg:ansigreen', 'markdown.list': 'fg:ansicyan',
            'diff.header': 'bold', 'diff.plus': 'fg:ansigreen', 'diff.minus': 'fg:ansired',
            'log.debug': 'fg:#888888', 'log.info': '', 'log.warning': 'fg:ansiyellow',
            'log.error': 'fg:ansired', 'log.critical': 'bold fg:ansired',
            'placeholder': 'fg:#666666',
        })
        self.logger.debug("Application style defined.")
        history_file = config.get_history_file_path()
        completer = PTKCommandCompleter(self.file_manager, self.git_manager)
        import platform
        is_mac = platform.system() == "Darwin"
        is_windows = platform.system() == "Windows"
        
        if is_mac:
            enter_key = "⌘"
            modifier = "Cmd"
        elif is_windows:
            enter_key = "↵"
            modifier = "Alt+Shift"
        else:  # Linux and others
            enter_key = "↵"
            modifier = "Alt"
        
        placeholder_text = f"Write your instructions and submit with {modifier}+{enter_key}"
        
        self.prompt_session = PromptSession(
            history=FileHistory(str(history_file)), completer=completer,
            multiline=True, prompt_continuation="... ",
            placeholder=placeholder_text
        )
        self.logger.debug("Prompt session initialized with history and completer.")

    def _reconfigure_logging_for_ptk(self) -> None:
        root_logger = logging.getLogger()
        old_handler = next((h for h in root_logger.handlers if isinstance(h, logging.StreamHandler)), None)
        if not old_handler:
            self.logger.debug("No existing StreamHandler to replace. Skipping log reconfiguration.")
            return
        ptk_handler = PromptToolkitLogHandler(self.style)
        ptk_handler.setFormatter(old_handler.formatter)
        ptk_handler.setLevel(old_handler.level)
        root_logger.removeHandler(old_handler)
        root_logger.addHandler(ptk_handler)
        self.logger.debug("Logging reconfigured to use PromptToolkitLogHandler.")

    def _init_input_preprocessor(self) -> None:
        self.input_preprocessor = InputPreprocessor(
            logger=self.logger, file_manager=self.file_manager,
            git_manager=self.git_manager, repo_map=self.repo_map
        )
        self.logger.debug("InputPreprocessor initialized.")

    def _init_simple_components(self) -> None:
        self.edit_parser = EditParser()
        self.shell_executor = ShellExecutor(
            logger=self.logger, history_manager=self.history_manager, git_root=self.git_root
        )
        self.logger.debug("Simple components (Parser, ShellExecutor) initialized.")

    def _log_final_status(self, app: App) -> None:
        if not self.git_manager.is_git_available():
            self.logger.debug("Final check: Git is unavailable.")
        elif not self.git_root:
            self.logger.warning("Final check: Not inside a git repository. Git integration disabled.")
        else:
            self.logger.debug(f"Final check: Git repository root confirmed: {FmtColors['CYAN']}{self.git_root}{RESET}")
        
        if self.docker_manager and self.docker_manager.is_available:
            self.logger.debug("Final check: Docker integration is active.")
            if self.docker_manager.compose_file:
                self.logger.debug(f"Using compose file: {FmtColors['CYAN']}{self.docker_manager.compose_file}{RESET}")
            if app.file_manager.get_files():
                files_in_context_abs = [app.file_manager.get_abs_path(f) for f in app.file_manager.get_files() if app.file_manager.get_abs_path(f)]
                self.docker_manager.check_for_missing_volume_mounts(files_in_context_abs)
        else:
            self.logger.debug("Final check: Docker integration is disabled.")