import logging
import re
import sys
import traceback
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Set, Dict, Optional, Tuple

from prompt_toolkit import PromptSession, print_formatted_text
from prompt_toolkit.formatted_text import FormattedText
from prompt_toolkit.styles import Style

from tinycoder.chat_history import ChatHistoryManager
from tinycoder.code_applier import CodeApplier
from tinycoder.command_handler import CommandHandler
from tinycoder.edit_parser import EditParser
from tinycoder.file_manager import FileManager
from tinycoder.git_manager import GitManager
from tinycoder.input_preprocessor import InputPreprocessor
from tinycoder.llms.base import LLMClient
from tinycoder.llms.pricing import get_model_pricing
from tinycoder.prompt_builder import PromptBuilder
from tinycoder.repo_map import RepoMap
from tinycoder.rule_manager import RuleManager
from tinycoder.shell_executor import ShellExecutor
from tinycoder.ui.console_interface import ring_bell
from tinycoder.ui.log_formatter import STYLES, COLORS as FmtColors, RESET
import tinycoder.config as config
from tinycoder.docker_manager import DockerManager


@dataclass
class AppState:
    mode: str = "code"
    coder_commits: Set[str] = field(default_factory=set)
    lint_errors_found: Dict[str, str] = field(default_factory=dict)
    reflected_message: Optional[str] = None
    include_repo_map: bool = True
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    cached_token_breakdown: Dict[str, int] = field(default_factory=dict)


class App:
    """The main application class, responsible for runtime logic and orchestration."""
    def __init__(
        self,
        logger: logging.Logger,
        client: LLMClient,
        model: str,
        git_manager: GitManager,
        git_root: Optional[str],
        file_manager: FileManager,
        history_manager: ChatHistoryManager,
        repo_map: RepoMap,
        docker_manager: Optional[DockerManager],
        prompt_builder: PromptBuilder,
        rule_manager: RuleManager,
        input_preprocessor: InputPreprocessor,
        edit_parser: EditParser,
        shell_executor: ShellExecutor,
        prompt_session: PromptSession,
        style: Style,
    ):
        """Initializes the App with its dependencies."""
        self.state = AppState()
        self.logger = logger
        self.client = client
        self.model = model
        self.git_manager = git_manager
        self.git_root = git_root
        self.file_manager = file_manager
        self.history_manager = history_manager
        self.repo_map = repo_map
        self.docker_manager = docker_manager
        self.prompt_builder = prompt_builder
        self.rule_manager = rule_manager
        self.input_preprocessor = input_preprocessor
        self.edit_parser = edit_parser
        self.shell_executor = shell_executor
        self.prompt_session = prompt_session
        self.style = style

        # Initialize components that depend on the App instance (`self`)
        self._init_command_handler()
        self._init_code_applier()

        self.logger.debug("App instance fully initialized.")

    def toggle_repo_map(self, state: bool) -> None:
        """Sets the state for including the repo map in prompts."""
        self.state.include_repo_map = state
        status_str = f"{FmtColors['GREEN']}enabled{RESET}" if state else f"{FmtColors['YELLOW']}disabled{RESET}"
        self.logger.info(f"Repository map inclusion in prompts is now {status_str}.")

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
                self.logger.info(f"{FmtColors['BLUE']}Suggesting files based on the last user message in history.{RESET}")
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
                self.logger.info(f"  {i+1}. {FmtColors['CYAN']}{fname}{RESET}")

            confirm_prompt = f"{FmtColors['YELLOW']}Add files to context? (y/N, or list indices like '1,3'): {RESET}"
            confirm = prompt_user_input(confirm_prompt).strip().lower()
            if not confirm: # User cancelled
                self.logger.info(f"{FmtColors['YELLOW']}\nFile addition cancelled by user.{RESET}")
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
                    colored_fnames = [f"{FmtColors['CYAN']}{f}{RESET}" for f in successfully_added_fnames]
                    self.logger.debug(f"Added {added_count} file(s) to context: {', '.join(colored_fnames)}")
            else:
                self.logger.debug("No suggested files were added to the context.")
        elif instruction: # _ask_llm_for_files was called but returned no files
            self.logger.debug("LLM did not suggest any files based on the provided instruction.")
        # If instruction was empty, it's logged before calling _ask_llm_for_files


    def _init_command_handler(self) -> None:
        """Initializes the CommandHandler, which depends on the app instance."""
        self.command_handler = CommandHandler(
            file_manager=self.file_manager,
            git_manager=self.git_manager,
            docker_manager=self.docker_manager,
            logger=self.logger,
            clear_history_func=self.history_manager.clear,
            write_history_func=self.history_manager.save_message_to_file_only,
            get_mode=lambda: self.state.mode,
            set_mode=lambda mode: setattr(self.state, "mode", mode),
            git_commit_func=self._git_add_commit,
            git_undo_func=self._git_undo,
            app_name=config.APP_NAME,
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

    def _init_code_applier(self) -> None:
        """Initializes the CodeApplier, which depends on the app instance."""
        self.code_applier = CodeApplier(
            file_manager=self.file_manager,
            git_manager=self.git_manager,
            input_func=self._prompt_for_confirmation,
            style=self.style,
        )
        self.logger.debug("CodeApplier initialized.")

    def _handle_docker_automation(self, modified_files_rel: List[str], non_interactive: bool = False):
        """
        After edits are applied, checks for Docker context and automates actions.
        - Restarts services that don't have live-reload.
        - Prompts to build if dependency files change.
        """
        if not self.docker_manager or not self.docker_manager.is_available or not self.docker_manager.services:
            self.logger.debug("Docker automation skipped: manager not available or no services found.")
            return

        modified_files_abs = [self.file_manager.get_abs_path(f) for f in modified_files_rel if self.file_manager.get_abs_path(f)]
        if not modified_files_abs:
            return # No valid files to check

        # find_affected_services now returns Dict[str, Set[str]]
        affected_services_map = self.docker_manager.find_affected_services(modified_files_abs)
        if not affected_services_map:
            self.logger.debug("No Docker services affected by file changes.")
            return

        dependency_files = ["requirements.txt", "pyproject.toml", "package.json", "Pipfile", "Dockerfile"] # Added Dockerfile
        modified_dep_files = any(Path(f).name.lower() in dependency_files for f in modified_files_rel) # .lower() for Dockerfile

        services_to_build_and_restart = set()
        services_to_volume_restart_only = set()

        for service_name, reasons in affected_services_map.items():
            needs_build = False
            # If any global dep file changed for *any* service, all *affected* services are marked for build.
            # Or if Dockerfile specific to a service's build context (or the context itself) changes.
            if modified_dep_files: 
                # Check if this specific service's Dockerfile or build context is among the changed dependency files
                service_build_config = self.docker_manager.services.get(service_name, {}).get('build', {})
                service_build_context_str = None
                if isinstance(service_build_config, str):
                    service_build_context_str = service_build_config
                elif isinstance(service_build_config, dict):
                    service_build_context_str = service_build_config.get('context')
                
                service_dockerfile_str = "Dockerfile" # default
                if isinstance(service_build_config, dict) and isinstance(service_build_config.get('dockerfile'), str):
                     service_dockerfile_str = service_build_config.get('dockerfile')


                if service_build_context_str and self.docker_manager.root_dir:
                    service_build_context_path = (self.docker_manager.root_dir / service_build_context_str).resolve()
                    
                    # Check if any modified dep file is THE Dockerfile for this service, or within its context
                    for mod_file_rel in modified_files_rel:
                        mod_file_abs = self.file_manager.get_abs_path(mod_file_rel)
                        if not mod_file_abs: continue

                        # Is the modified file the Dockerfile for this service?
                        # Resolve path to Dockerfile relative to context
                        dockerfile_abs_path = (service_build_context_path / service_dockerfile_str).resolve()
                        if mod_file_abs == dockerfile_abs_path:
                            needs_build = True
                            self.logger.debug(f"Service '{service_name}' Dockerfile '{service_dockerfile_str}' changed.")
                            break
                        # Is a generic dep file (like requirements.txt) inside this service's build context?
                        if mod_file_abs.name.lower() in dependency_files and mod_file_abs.is_relative_to(service_build_context_path):
                            needs_build = True
                            self.logger.debug(f"Dependency file '{mod_file_abs.name}' changed within build context of '{service_name}'.")
                            break
                    if needs_build:
                         self.logger.debug(f"Service '{service_name}' marked for build due to specific dependency change.")


            if "build_context" in reasons and not needs_build: # if not already caught by dep check
                needs_build = True
                self.logger.debug(f"Service '{service_name}' marked for build due to direct build_context change.")

            if needs_build:
                services_to_build_and_restart.add(service_name)
            elif "volume" in reasons: # Only consider for volume restart if not already needing a build
                if self.docker_manager.is_service_running(service_name):
                    if not self.docker_manager.has_live_reload(service_name):
                        services_to_volume_restart_only.add(service_name)
                    else:
                        self.logger.info(f"Service '{STYLES['BOLD']}{FmtColors['CYAN']}{service_name}{RESET}' affected by volume change and has live-reload, no automatic restart needed.")
                else:
                    self.logger.debug(f"Service '{service_name}' affected by volume change but not running, skipping restart.")
        
        if services_to_build_and_restart:
            sorted_build_services = sorted(list(services_to_build_and_restart))
            colored_services = [f"{STYLES['BOLD']}{FmtColors['YELLOW']}{s}{RESET}" for s in sorted_build_services]
            self.logger.warning(
                f"Services requiring build & restart: {', '.join(colored_services)}"
            )
            if non_interactive:
                self.logger.info("Non-interactive mode: Skipping build & restart prompt. Please manage manually.")
            else:
                prompt = f"{FmtColors['YELLOW']}Rebuild and restart affected services ({', '.join(sorted_build_services)}) now? (y/N): {RESET}"
                confirm = prompt_user_input(prompt).strip().lower()

                if not confirm:  # User cancelled the prompt
                    self.logger.info("\nBuild & restart cancelled by user.")
                elif confirm == 'y':
                    try:
                        for service in sorted_build_services:
                            if self.docker_manager.build_service(service):
                                self.docker_manager.up_service_recreate(service)
                    except KeyboardInterrupt:
                        self.logger.info("\nBuild & restart operation cancelled by user.")

            return # Exit after build consideration, regardless of user choice

        # Handle services that only needed a volume-based restart (and weren't built)
        if services_to_volume_restart_only:
            sorted_volume_services = sorted(list(services_to_volume_restart_only))
            colored_services = [f"{STYLES['BOLD']}{FmtColors['CYAN']}{s}{RESET}" for s in sorted_volume_services]
            self.logger.info(
                f"Services requiring restart due to volume changes (no live-reload): {', '.join(colored_services)}"
            )
            if non_interactive:
                self.logger.info("Non-interactive mode: Skipping volume-based restart. Please manage manually.")
            else:
                try:
                    # Could add a prompt here too if desired, but for now, auto-restarting these.
                    # confirm_restart = input(f"Restart services ({', '.join(sorted_volume_services)}) now? (y/N): ").strip().lower()
                    # if confirm_restart == 'y':
                    for service in sorted_volume_services:
                        self.logger.info(f"Service '{STYLES['BOLD']}{FmtColors['CYAN']}{service}{RESET}' is running without apparent live-reload and affected by volume change.")
                        self.docker_manager.restart_service(service)
                except (EOFError, KeyboardInterrupt):
                    self.logger.info("\nVolume restart cancelled by user.")


    def _add_initial_files(self, files: List[str]) -> None:
        """Adds initial files specified via command line arguments."""
        if files:
            colored_files = [f"{FmtColors['CYAN']}{f}{RESET}" for f in files]
            self.logger.debug(f"Adding initial files to context: {', '.join(colored_files)}")
            added_count = 0
            for fname in files:
                if self.file_manager.add_file(fname):
                    added_count += 1
            self.logger.debug(f"Successfully added {added_count} initial file(s).")
        else:
            self.logger.debug("No initial files specified.")

    async def _prompt_for_confirmation(self, prompt_text: str) -> str:
        """Async user prompt for confirmations within the main app loop."""
        ring_bell()
        # Use prompt_async for async contexts
        response = await self.prompt_session.prompt_async(prompt_text)
        # Strip any escape sequences and control characters
        # This handles cases where Alt+Enter or other key combos add unwanted characters
        import re
        cleaned_response = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', response)
        return cleaned_response.strip()


    def _get_bottom_toolbar_tokens(self) -> FormattedText:
        """
        Generates the formatted text for the bottom toolbar from cached token context.
        This function must be extremely fast as it's called on every redraw.
        """
        breakdown = self.state.cached_token_breakdown
        total = breakdown.get("total", 0)
        
        # Determine color based on total tokens
        total_color_class = 'class:bottom-toolbar.low'
        if total > 25000:
            total_color_class = 'class:bottom-toolbar.high'
        elif total > 15000:
            total_color_class = 'class:bottom-toolbar.medium'
        
        # Full word descriptions, single style for most text
        parts = [
            ('class:bottom-toolbar', '  Context: '),
            (total_color_class, f'{total:,}'),
            ('class:bottom-toolbar', f" (Prompt: {breakdown.get('prompt_rules', 0):,} | "),
            ('class:bottom-toolbar', f"Map: {breakdown.get('repo_map', 0):,} | "),
            ('class:bottom-toolbar', f"Files: {breakdown.get('files', 0):,} | "),
            ('class:bottom-toolbar', f"History: {breakdown.get('history', 0):,})  "),
        ]

        return FormattedText(parts)

    def _update_and_cache_token_breakdown(self) -> None:
        """
        Performs the expensive token calculation and caches the result.
        This should only be called when the context has actually changed.
        """
        self.state.cached_token_breakdown = self._get_current_context_token_breakdown()
        self.logger.debug("Token context breakdown cache updated.")
        
    def _get_current_context_token_breakdown(self) -> Dict[str, int]:
        """Calculates the approximate token count breakdown for the current context."""
        # This is a helper function to estimate tokens from characters.
        def count_tokens(text: str) -> int:
            return int(len(text) / 4)

        # 1. System Prompt (Base + Rules)
        active_rules = self.rule_manager.get_active_rules_content()
        # Build system prompt WITHOUT repo map to isolate its size
        base_system_prompt_content = self.prompt_builder.build_system_prompt(
            self.state.mode,
            active_rules,
            include_map=False # Exclude map for this part of calculation
        )
        system_prompt_tokens = count_tokens(base_system_prompt_content)

        # 2. Repo Map
        repo_map_tokens = 0
        if self.state.include_repo_map:
            # Generate the repo map separately to get its size
            chat_files_rel = self.file_manager.get_files()
            repo_map_str = self.repo_map.generate_map(chat_files_rel)
            repo_map_tokens = count_tokens(repo_map_str)

        # 3. File Context
        file_context_message = self.prompt_builder.get_file_content_message()
        file_context_content = file_context_message['content'] if file_context_message else ""
        file_context_tokens = count_tokens(file_context_content)

        # 4. History
        current_history = self.history_manager.get_history()
        history_content = "\n".join(msg['content'] for msg in current_history)
        history_tokens = count_tokens(history_content)

        total_tokens = system_prompt_tokens + repo_map_tokens + file_context_tokens + history_tokens

        return {
            "total": total_tokens,
            "prompt_rules": system_prompt_tokens,
            "repo_map": repo_map_tokens,
            "files": file_context_tokens,
            "history": history_tokens,
        }

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
            self.state.mode,
            active_rules,
            self.state.include_repo_map      # Pass the toggle state
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

            input_chars = sum(len(msg["content"]) for msg in history_to_send) + len(system_prompt_text)
            input_tokens = round(input_chars / 4)
            self.state.total_input_tokens += input_tokens
            
            self.logger.debug(f"Approx. input tokens to send: {input_tokens}")

            response_content = None
            error_message = None

            # Check for streaming capability
            if hasattr(self.client, 'generate_content_stream'):
                assistant_header = [('class:assistant.header', 'ASSISTANT'), ('', ':\n')]
                print_formatted_text(FormattedText(assistant_header), style=self.style)
                
                full_response_chunks = []
                try:
                    stream = self.client.generate_content_stream(
                        system_prompt=system_prompt_text, history=history_to_send
                    )
                    for chunk in stream:
                        if "STREAMING_ERROR:" in chunk:
                            error_message = chunk.replace("STREAMING_ERROR:", "").strip()
                            break
                        
                        # Use print_formatted_text to be safe with prompt_toolkit rendering
                        print_formatted_text(chunk, end='')
                        sys.stdout.flush() # Ensure chunks are displayed immediately
                        full_response_chunks.append(chunk)
                    
                    print() # Newline after the full response
                    if not error_message:
                        response_content = "".join(full_response_chunks)

                except Exception as e:
                    self.logger.error(f"Error while streaming from LLM: {e}", exc_info=True)
                    error_message = f"An unexpected error occurred during streaming: {e}"
            
            else: # Fallback to original non-streaming behavior, but without spinner
                try:
                    response_content, error_message = self.client.generate_content(
                        system_prompt=system_prompt_text, history=history_to_send
                    )
                except Exception as e:
                    self.logger.error(f"Error calling LLM: {e}", exc_info=True)
                    error_message = f"An unexpected error occurred during LLM API call: {e}"

            # --- Handle response ---
            if error_message:
                self.logger.error(
                    f"Error calling LLM API ({self.client.__class__.__name__}): {error_message}",
                )
                return None
            elif response_content is None:
                self.logger.warning(
                    f"LLM API ({self.client.__class__.__name__}) returned no content.",
                )
                return None
            else:
                # For non-streaming, we need to print the response here.
                # For streaming, it was already printed chunk-by-chunk.
                if not hasattr(self.client, 'generate_content_stream'):
                    assistant_header = [('class:assistant.header', 'ASSISTANT'), ('', ':\n')]
                    print_formatted_text(FormattedText(assistant_header), style=self.style)

                    # Format for display if in ask mode and not an edit block
                    if self.state.mode == "ask" and response_content and not response_content.strip().startswith("<"):
                        display_response_tuples = self._format_markdown_for_terminal(response_content)
                        print_formatted_text(FormattedText(display_response_tuples), style=self.style)
                    else:
                        # Print raw content, but use prompt_toolkit to handle potential long lines
                        print_formatted_text(response_content)
                    
                    print() # Add a final newline for spacing

                output_chars = len(response_content)
                output_tokens = round(output_chars / 4) # Based on raw response
                self.state.total_output_tokens += output_tokens
                self.logger.debug("Approx. response tokens: %d", output_tokens)
            
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
            self.logger.warning("Not in a git repository or Git is unavailable, skipping commit.")
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
                        f"Requested commit path {FmtColors['CYAN']}{fname}{RESET} does not exist on disk, skipping.",
                    )
                # Don't warn if iterating all context files and one is missing (it might have been deleted)

        if not files_to_commit_abs:
            self.logger.info("No existing files found for the commit.")
            return

        # Prepare commit message
        commit_message = (
            f"{config.COMMIT_PREFIX} Changes to {', '.join(sorted(files_to_commit_rel))}"
        )

        # Call GitManager to commit
        commit_hash = self.git_manager.commit_files(
            files_to_commit_abs, files_to_commit_rel, commit_message
        )

        if commit_hash:
            self.state.coder_commits.add(commit_hash)
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

        if last_hash not in self.state.coder_commits:
            self.logger.error(f"Last commit {FmtColors['YELLOW']}{last_hash}{RESET} was not made by {STYLES['BOLD']}{config.APP_NAME}{RESET}.")
            self.logger.info("You can manually undo with 'git reset HEAD~1'")
            return

        # Call GitManager to undo
        success = self.git_manager.undo_last_commit(last_hash)

        if success:
            self.state.coder_commits.discard(last_hash)  # Remove hash if undo succeeded
            # Use history manager to log the undo action to the file only
            self.history_manager.save_message_to_file_only(
                "tool", f"Undid commit {last_hash}"
            )

    async def _handle_llm_file_requests(self, requested_files_from_llm: List[str]) -> bool:
        """
        Handles LLM's request for additional files.
        Checks existence, prompts user, adds files, and sets up reflection.
        Returns True if a reflection message was set (meaning files were added or action taken
        that requires an LLM follow-up), False otherwise.
        """
        if not requested_files_from_llm:
            return False

        self.logger.info(f"{STYLES['BOLD']}{FmtColors['BLUE']}LLM requested additional file context:{RESET}")
        
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
                 self.logger.debug("No new, existing files to add from LLM's request.")
            return False

        self.logger.info(f"{FmtColors['BLUE']}LLM suggests adding these existing files to context:{RESET}")
        for i, fname in enumerate(valid_files_to_potentially_add):
            self.logger.info(f"  {i+1}. {FmtColors['CYAN']}{fname}{RESET}")
        
        confirm_prompt = f"{FmtColors['YELLOW']}Add these files to context? (y/N, or list indices like '1,3'): {RESET}"
        confirm = (await self._prompt_for_confirmation(confirm_prompt)).strip().lower()

        if not confirm: # Handles cancellation from prompt_user_input
            self.logger.info(f"{FmtColors['YELLOW']}\nFile addition (from LLM request) cancelled by user.{RESET}")
            self.state.reflected_message = "User cancelled the addition of requested files. Please advise on how to proceed or if you can continue without them."
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
                colored_successfully_added_fnames = [f"{FmtColors['CYAN']}{f}{RESET}" for f in successfully_added_fnames]
                tool_message = f"Added {added_count} file(s) to context from LLM request: {', '.join(colored_successfully_added_fnames)}"
                self.history_manager.save_message_to_file_only("tool", tool_message)
                reflection_content = (
                    f"The following files have been added to the context as per your request: {', '.join(colored_successfully_added_fnames)}. "
                    "Please proceed with the original task based on the updated context."
                )
                self.state.reflected_message = reflection_content
                return True
            else:
                self.logger.info("No files were ultimately added from LLM's request despite confirmation.")
        else: 
            self.logger.debug("User chose not to add files requested by LLM, or selection was invalid.")
            self.state.reflected_message = "User declined to add the requested files. Please advise on how to proceed or if you can continue without them."
            return True

        return False

    def _display_usage_summary(self):
        """Calculates and displays the token usage and estimated cost for the session."""
        if self.state.total_input_tokens == 0 and self.state.total_output_tokens == 0:
            return  # Don't display anything if no API calls were made

        pricing = get_model_pricing(self.model)
        total_tokens = self.state.total_input_tokens + self.state.total_output_tokens
        
        cost_line = ""
        if pricing:
            input_cost = (self.state.total_input_tokens / 1_000_000) * pricing["input"]
            output_cost = (self.state.total_output_tokens / 1_000_000) * pricing["output"]
            total_cost = input_cost + output_cost
            cost_line = f"Est. Cost:  {STYLES['BOLD']}{FmtColors['YELLOW']}${total_cost:.4f}{RESET}"
        elif self.model:
            cost_line = f"Est. Cost:  {FmtColors['GREY']}(price data unavailable for {self.model}){RESET}"
            
        # Prepare formatted lines
        title_line = f"{STYLES['BOLD']}Session Summary{RESET}"
        model_line = f"Model:      {STYLES['BOLD']}{FmtColors['GREEN']}{self.model}{RESET}"
        tokens_line = (
            f"Tokens:     {STYLES['BOLD']}{FmtColors['CYAN']}{total_tokens:,}{RESET} "
            f"{FmtColors['GREY']}(Input: {self.state.total_input_tokens:,} | Output: {self.state.total_output_tokens:,}){RESET}"
        )

        def get_visual_length(s: str) -> int:
            """Calculates the visible length of a string by removing ANSI escape codes."""
            return len(re.sub(r'\x1b\[[0-9;]*m', '', s))

        # Build the final output string with a box
        border_char = '─'
        width = 60 # Fixed width for simplicity and clean alignment

        def pad_line(line: str) -> str:
            """Pads a line to the fixed width, accounting for ANSI codes."""
            visual_len = get_visual_length(line)
            padding = ' ' * (width - visual_len)
            return f"{line}{padding}"
        
        def center_line(line: str) -> str:
            """Centers a line within the fixed width, accounting for ANSI codes."""
            visual_len = get_visual_length(line)
            padding_total = width - visual_len
            if padding_total < 0: padding_total = 0
            left_pad = ' ' * (padding_total // 2)
            right_pad = ' ' * (padding_total - len(left_pad))
            return f"{left_pad}{line}{right_pad}"

        summary_message = (
            f"\n{FmtColors['GREY']}┌{border_char * (width + 2)}┐{RESET}\n"
            f"{FmtColors['GREY']}│ {center_line(title_line)} {FmtColors['GREY']}│{RESET}\n"
            f"{FmtColors['GREY']}├{border_char * (width + 2)}┤{RESET}\n"
            f"{FmtColors['GREY']}│ {pad_line(model_line)} {FmtColors['GREY']}│{RESET}\n"
            f"{FmtColors['GREY']}│ {pad_line(tokens_line)} {FmtColors['GREY']}│{RESET}\n"
            f"{FmtColors['GREY']}│ {pad_line(cost_line)} {FmtColors['GREY']}│{RESET}\n"
            f"{FmtColors['GREY']}└{border_char * (width + 2)}┘{RESET}"
        )
        # Use print() to ensure the summary is always visible regardless of log level
        print(summary_message)

    async def process_user_input(self, non_interactive: bool = False):
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
                if await self._handle_llm_file_requests(requested_files):
                    # A reflection message is set (e.g., files added, user cancelled).
                    # The run_one loop will pick this up. We are done for this turn.
                    return 
                # If it returns False, it means no new files were added to prompt reflection,
                # so we can potentially proceed to edits if any were also sent.

            # --- Process Edits (only if not already handling a file request reflection and in code mode) ---
            if not self.state.reflected_message and self.state.mode == "code":
                if edits:
                    all_succeeded, failed_indices, modified_files, lint_errors = (
                        await self.code_applier.apply_edits(edits)
                    )
                    self.state.lint_errors_found = lint_errors 

                    if all_succeeded:
                        if modified_files:
                            self.logger.debug("All edits applied successfully.")
                            # Automate Docker actions before committing
                            self._handle_docker_automation(list(modified_files), non_interactive=non_interactive)
                            self._git_add_commit(list(modified_files))
                        else:
                            self.logger.info("Edits processed, but no files were changed.")
                    elif failed_indices:
                        failed_indices_str = ", ".join(map(str, sorted(failed_indices)))
                        colored_indices = f"{STYLES['BOLD']}{FmtColors['RED']}{failed_indices_str}{RESET}"
                        error_message = (
                            f"Some edits failed to apply. No changes have been committed.\n"
                            f"Please review and provide corrected edit blocks for the failed edits.\n\n"
                            f"Failed edit block numbers (1-based): {colored_indices}\n\n"
                            f"Successfully applied edits (if any) have modified the files in memory, "
                            f"but you should provide corrections for the failed ones before proceeding."
                        )
                        self.logger.error(error_message)
                        self.state.reflected_message = error_message 
                    
                else:  # No edits found by parser (and no file requests were actioned to cause reflection)
                    self.logger.debug("No actionable edit blocks found in the response.")

                # --- Check for Lint Errors (related to edits) ---
                # Only trigger lint reflection if no other more critical reflection (like edit failure) is already set.
                if self.state.lint_errors_found and not self.state.reflected_message: 
                    error_messages = ["Found syntax errors after applying edits:"]
                    for fname, error in self.state.lint_errors_found.items():
                        error_messages.append(f"\n--- Errors in {FmtColors['CYAN']}{fname}{RESET} ---\n{error}")
                    combined_errors = "\n".join(error_messages)
                    self.logger.error(combined_errors)

                    fix_lint = await self._prompt_for_confirmation(f"{FmtColors['YELLOW']}Attempt to fix lint errors? (y/N): {RESET}")
                    if fix_lint.lower() == "y":
                        self.state.reflected_message = combined_errors
            
        # Mode reversion (if any) is handled in run_one after this function returns

    def _ask_llm_for_files(self, instruction: str) -> List[str]:
        """Asks the LLM to identify files needed for a given instruction."""
        self.logger.info(f"{FmtColors['BLUE']}Asking LLM to identify relevant files...{RESET}")

        # Use PromptBuilder to build the identify files prompt, passing repo map state
        system_prompt = self.prompt_builder.build_identify_files_prompt(
            include_map=self.state.include_repo_map
        )

        history_for_files = [{"role": "user", "content": instruction}]
        try:
            response_content, error_message = self.client.generate_content(
                system_prompt=system_prompt, history=history_for_files
            )
        except KeyboardInterrupt:
            self.logger.info("\nLLM file suggestion cancelled.")
            return []  # Return empty list on cancellation

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
                    f"Ignoring non-existent file suggested by LLM: {FmtColors['RED']}{fname}{RESET}"
                )
        
        if existing_files:
            colored_existing_files = [f"{FmtColors['CYAN']}{f}{RESET}" for f in existing_files]
            self.logger.info(
                f"LLM suggested files (after filtering): {', '.join(colored_existing_files)}",
            )
        else:
            self.logger.info("LLM suggested no existing files after filtering.")
            
        return existing_files

    def init_before_message(self):
        """Resets state before processing a new user message."""
        self.state.lint_errors_found = {}
        self.state.reflected_message = None

    def _format_markdown_for_terminal(self, markdown_text: str) -> List[Tuple[str, str]]:
        """Converts markdown text to a list of (style_class, text) tuples for prompt_toolkit."""
        formatted_text = []
        in_code_block = False

        for line in markdown_text.splitlines():
            stripped_line = line.lstrip()

            if stripped_line.startswith("```"):
                in_code_block = not in_code_block
                formatted_text.append(('class:markdown.code-block', line + '\n'))
                continue

            if in_code_block:
                formatted_text.append(('class:markdown.code-block', line + '\n'))
                continue

            if stripped_line.startswith("#"):
                level = len(stripped_line) - len(stripped_line.lstrip('#'))
                if stripped_line[level:].startswith(' '):
                    style_class = f'class:markdown.h{min(level, 3)}'
                    formatted_text.append((style_class, line + '\n'))
                    continue
            
            # This part is a simplification. A real markdown parser would be needed for complex cases.
            # For now, we just append the line. Further regex for bold/italic could be added here.
            formatted_text.append(('', line + '\n'))

        return formatted_text


    async def _handle_command(self, user_message: str) -> bool:
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
            if not await self.run_one(prompt_arg, preproc=False):
                return False  # Exit signal from processing the prompt

        return True  # Continue processing

    async def run_one(self, user_message, preproc, non_interactive=False):
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
                if not await self._handle_command(user_message):
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
        if self.state.mode == "code" and not self.file_manager.get_files():
            self.logger.info(f"No files in context for {STYLES['BOLD']}{FmtColors['GREEN']}CODE{RESET} mode.")
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
        await self.process_user_input(non_interactive=non_interactive)  # This now handles LLM call, edits, linting

        # Check if reflection is needed *and* allowed (interactive mode)
        while not non_interactive and self.state.reflected_message:
            if num_reflections >= max_reflections:
                self.logger.warning(
                    f"Reached max reflection limit ({max_reflections}). Stopping reflection.",
                )
                self.state.reflected_message = None  # Prevent further loops
                break  # Exit reflection loop

            num_reflections += 1
            self.logger.info(
                f"Reflection {num_reflections}/{max_reflections}: Sending feedback to LLM..."
            )
            message = (
                self.state.reflected_message
            )  # Use the reflected message as the next input
            self.state.reflected_message = (
                None  # Clear before potentially being set again by process_user_input
            )

            # Add the reflected message to history *before* processing
            self.history_manager.add_message("user", message)
            await self.process_user_input(non_interactive=non_interactive)  # Process the reflected input

        return True  # Indicate normal processing occurred (or finished reflection loop)

    async def run(self):
        """Main loop for the chat application using prompt_toolkit."""
        # Initial token calculation before the first prompt
        self._update_and_cache_token_breakdown()

        # Use logger for startup info, which has its own color formatting.
        self.logger.info(f"  Model: {FmtColors['GREEN']}{STYLES['BOLD']}{self.model}{RESET}")
        self.logger.info("  Type /help for commands, or !<cmd> to run shell commands.\n")

        while True:
            try:
                # 1. Build the prompt message
                mode_str = self.state.mode.upper() # Use uppercase for consistency
                prompt_message = FormattedText([
                    ('class:prompt.mode', f'{mode_str}'),
                    ('class:prompt.separator', ' > '),
                ])

                # 2. Build the bottom toolbar with token info
                bottom_toolbar = self._get_bottom_toolbar_tokens

                # 3. Get input from the user
                ring_bell()
                inp = await self.prompt_session.prompt_async(
                    prompt_message,
                    bottom_toolbar=bottom_toolbar,
                    style=self.style
                )

                # 4. Process the input
                processed_inp = inp.strip()
                if not processed_inp:
                    continue

                status = await self.run_one(processed_inp, preproc=True)
                if not status:
                    break # Exit signal from run_one (e.g., /exit command)

                # 5. Update the token cache for the *next* prompt render.
                self._update_and_cache_token_breakdown()

            except KeyboardInterrupt:
                # User pressed Ctrl+C at the prompt.
                # This will cancel the current input and prompt again.
                continue
            except EOFError:
                # User pressed Ctrl+D.
                print("\nExiting (EOF).", file=sys.stderr)
                break

        self._display_usage_summary()
        self.logger.info("Goodbye! 👋")
