import logging
import sys
from dataclasses import dataclass, field
from typing import List, Set, Dict, Optional

from prompt_toolkit import PromptSession
from prompt_toolkit.styles import Style

from tinycoder.chat_history import ChatHistoryManager
from tinycoder.code_applier import CodeApplier
from tinycoder.command_handler import CommandHandler
from tinycoder.context_manager import ContextManager
from tinycoder.edit_parser import EditParser
from tinycoder.file_manager import FileManager
from tinycoder.git_manager import GitManager
from tinycoder.input_preprocessor import InputPreprocessor
from tinycoder.llms.base import LLMClient
from tinycoder.llm_response_processor import LLMResponseProcessor
from tinycoder.prompt_builder import PromptBuilder
from tinycoder.repo_map import RepoMap
from tinycoder.rule_manager import RuleManager
from tinycoder.shell_executor import ShellExecutor
from tinycoder.ui.console_interface import ring_bell, prompt_user_input
from tinycoder.ui.session_summary import format_session_summary
from tinycoder.ui.app_formatter import AppFormatter
from tinycoder.docker_manager import DockerManager
from tinycoder.docker_automation import DockerAutomation

import tinycoder.config as config


from tinycoder.ui.log_formatter import (
    COLORS as FmtColors,
    RESET,
)

@dataclass
class AppState:
    mode: str = "code"
    coder_commits: Set[str] = field(default_factory=set)
    lint_errors_found: Dict[str, str] = field(default_factory=dict)
    reflected_message: Optional[str] = None
    include_repo_map: bool = True
    use_streaming: bool = False
    total_input_tokens: int = 0
    total_output_tokens: int = 0


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
        self.formatter = AppFormatter()

        # Initialize context manager
        self.context_manager = ContextManager(
            file_manager=self.file_manager,
            prompt_builder=self.prompt_builder,
            repo_map=self.repo_map,
            rule_manager=self.rule_manager,
            history_manager=self.history_manager,
            logger=self.logger
        )

        # Initialize LLM response processor
        self.llm_processor = LLMResponseProcessor(
            client=self.client,
            model=self.model,
            style=self.style,
            logger=self.logger
        )

        # Initialize Docker automation
        self.docker_automation = DockerAutomation(
            docker_manager=self.docker_manager,
            file_manager=self.file_manager,
            logger=self.logger
        )

        # Initialize components that depend on the App instance (`self`)
        self._init_command_handler()
        self._init_code_applier()

        self.logger.debug("App instance fully initialized.")

    def toggle_repo_map(self, state: bool) -> None:
        """Sets the state for including the repo map in prompts."""
        self.context_manager.set_repo_map_state(state)
        status_message = self.formatter.format_status_message(
            state, "Repository map inclusion in prompts"
        )
        self.logger.info(status_message)

    def _get_current_repo_map_string(self) -> str:
        """Generates and returns the current repository map string."""
        return self.context_manager.get_current_repo_map_string()

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
                self.logger.info(self.formatter.format_info("Suggesting files based on the last user message in history."))
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
                self.logger.info(f"  {i+1}. {self.formatter.format_filename(fname)}")

            confirm_prompt = f"{self.formatter.format_warning('Add files to context? (y/N, or list indices like \'1,3\'): ')}"
            confirm = prompt_user_input(confirm_prompt).strip().lower()
            if not confirm: # User cancelled
                self.logger.info(self.formatter.format_warning("\nFile addition cancelled by user."))
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
                    colored_fnames = self.formatter.format_success_files(successfully_added_fnames)
                    self.logger.debug(f"Added {added_count} file(s) to context: {self.formatter.format_success_files(successfully_added_fnames)}")
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
        """Handle Docker automation after file modifications."""
        self.docker_automation.handle_modified_files(modified_files_rel, non_interactive)


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


    def _get_bottom_toolbar_tokens(self):
        """
        Generates the formatted text for the bottom toolbar from cached token context.
        This function must be extremely fast as it's called on every redraw.
        """
        breakdown = self.context_manager.get_cached_token_breakdown()
        
        # Get current files in context
        files = list(self.file_manager.get_files())
        if files:
            files_str = f"  Files ({len(files)}): {', '.join(files[:5])}{'...' if len(files) > 5 else ''}"
        else:
            files_str = "  Files: none"
        
        # Create multi-line toolbar with files on top line and tokens below
        toolbar_text = f"{files_str}\n{self.formatter.format_bottom_toolbar(breakdown)}"
        return toolbar_text

    def _update_and_cache_token_breakdown(self) -> None:
        """
        Performs the expensive token calculation and caches the result.
        This should only be called when the context has actually changed.
        """
        self.context_manager.update_token_cache()

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
            self.context_manager.include_repo_map      # Pass the toggle state
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

        # Use the LLM response processor to handle the actual LLM interaction
        return self.llm_processor.process(final_messages, self.state.mode, self.state.use_streaming)

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
                        f"Requested commit path {self.formatter.format_filename(fname)} does not exist on disk, skipping.",
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
            self.logger.error(f"Last commit {self.formatter.format_warning(last_hash)} was not made by {self.formatter.format_bold(config.APP_NAME)}.")
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

        self.logger.info(f"{self.formatter.format_bold(self.formatter.format_info('LLM requested additional file context:'))}")
        
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
            formatted_non_existent = [self.formatter.format_error(fname) for fname in non_existent_files_requested]
            self.logger.warning(
                f"LLM requested non-existent files: {', '.join(formatted_non_existent)}"
            )
        
        if already_in_context_files:
            formatted_already_in_context = [self.formatter.format_info(fname) for fname in already_in_context_files]
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

        self.logger.info(self.formatter.format_info("LLM suggests adding these existing files to context:"))
        for i, fname in enumerate(valid_files_to_potentially_add):
            self.logger.info(f"  {i+1}. {self.formatter.format_filename(fname)}")
        
        confirm_prompt = f"{self.formatter.format_warning('Add these files to context? (y/N, or list indices like \'1,3\'): ')}"
        confirm = (await self._prompt_for_confirmation(confirm_prompt)).strip().lower()

        if not confirm: # Handles cancellation from prompt_user_input
            self.logger.info(self.formatter.format_warning("\nFile addition (from LLM request) cancelled by user."))
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
                colored_successfully_added_fnames = self.formatter.format_filename_list(successfully_added_fnames)
                tool_message = f"Added {added_count} file(s) to context from LLM request: {colored_successfully_added_fnames}"
                self.history_manager.save_message_to_file_only("tool", tool_message)
                reflection_content = (
                    f"The following files have been added to the context as per your request: {colored_successfully_added_fnames}. "
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

    def _display_usage_summary(self) -> None:
        """Calculates and displays the token usage and estimated cost for the session."""
        input_tokens, output_tokens, _total_tokens = self.llm_processor.get_usage_summary()
        cost_estimate = self.llm_processor.get_cost_estimate()
        summary = format_session_summary(self.model, input_tokens, output_tokens, cost_estimate)
        print(summary)

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
                        colored_indices = self.formatter.format_error_indices(failed_indices)
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
                        formatted_fname = self.formatter.format_success_files([fname])
                        error_messages.append(f"\n--- Errors in {formatted_fname} ---\n{error}")
                    combined_errors = "\n".join(error_messages)
                    self.logger.error(combined_errors)

                    fix_lint = await self._prompt_for_confirmation(f"{self.formatter.format_warning('Attempt to fix lint errors? (y/N): ')}")
                    if fix_lint.lower() == "y":
                        self.state.reflected_message = combined_errors
            
        # Mode reversion (if any) is handled in run_one after this function returns

    def _ask_llm_for_files(self, instruction: str) -> Optional[List[str]]:
        """Asks the LLM to identify files needed for a given instruction."""
        self.logger.info(f"{self.formatter.format_info('Asking LLM to identify relevant files...')}")

        # Use PromptBuilder to build the identify files prompt, passing repo map state
        system_prompt = self.prompt_builder.build_identify_files_prompt(
            include_map=self.context_manager.include_repo_map
        )

        history_for_files = [{"role": "user", "content": instruction}]
        try:
            response_content, error_message = self.client.generate_content(
                system_prompt=system_prompt, history=history_for_files
            )
        except KeyboardInterrupt:
            self.logger.info("\nLLM file suggestion cancelled.")
            return None  # Return None on cancellation to indicate user wants to exit

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
                    f"Ignoring non-existent file suggested by LLM: {self.formatter.format_error(fname)}"
                )
        
        if existing_files:
            colored_existing_files = [f"{self.formatter.format_filename(f)}" for f in existing_files]
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

    async def _maybe_handle_special_input(self, user_message: str) -> bool:
        """
        Handles commands (/...) and shell escapes (!...).
        Returns True if input was consumed, False otherwise.
        """
        if user_message.startswith("/"):
            status = await self._handle_command(user_message)
            return status  # Return the actual status from command handling
        if user_message.startswith("!"):
            self.shell_executor.execute(user_message, False)
            return True
        return False

    async def _ensure_files_for_code_mode(self, user_message: str) -> bool:
        """
        Ensures files are present for code mode by asking the LLM if none exist.
        Returns True if files were added or user cancelled, False if should exit.
        """
        if self.state.mode != "code":
            return True
        if self.file_manager.get_files():
            return True

        self.logger.info(f"No files in context for {self.formatter.format_bold(self.formatter.format_success('CODE'))} mode.")
        suggested_files = self._ask_llm_for_files(user_message)
        
        # If user cancelled the file suggestion (Ctrl+C), treat as exit
        if suggested_files is None:
            return False
            
        added_files_count = 0
        if suggested_files:
            self.logger.info("Attempting to add suggested files to context...")
            for fname in suggested_files:
                if self.file_manager.add_file(fname):
                    added_files_count += 1
            if added_files_count > 0:
                self.logger.info(f"Added {added_files_count} file(s) suggested by LLM.")
            else:
                self.logger.warning("Could not add any of the files suggested by the LLM.")
        else:
            self.logger.warning("LLM did not suggest files, or failed to retrieve suggestions. Proceeding without file context.")
        
        return True

    async def _main_llm_loop(self, non_interactive: bool) -> None:
        """
        Runs the main LLM interaction and optional reflection loops.
        """
        num_reflections = 0
        max_reflections = 3

        # Initial processing
        await self.process_user_input(non_interactive=non_interactive)

        # Reflection loop
        while not non_interactive and self.state.reflected_message:
            if num_reflections >= max_reflections:
                self.logger.warning(f"Reached max reflection limit ({max_reflections}). Stopping reflection.")
                self.state.reflected_message = None
                break
            num_reflections += 1
            self.logger.info(f"Reflection {num_reflections}/{max_reflections}: Sending feedback to LLM...")
            message = self.state.reflected_message
            self.state.reflected_message = None
            self.history_manager.add_message("user", message)
            await self.process_user_input(non_interactive=non_interactive)

    



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
        """
        self.init_before_message()
        if preproc:
            handled = await self._maybe_handle_special_input(user_message)
            if handled:
                return True
            # Check if this was an exit command that returned False
            if user_message.startswith("/"):
                # Command was handled but returned False (exit signal)
                return False

        # Ensure the message is added to history before any LLM processing
        self.history_manager.add_message("user", user_message)

        if not await self._ensure_files_for_code_mode(user_message):
            return False  # User cancelled, should exit
        await self._main_llm_loop(non_interactive)
        return True

    async def run(self):
        """Main loop for the chat application using prompt_toolkit."""
        # Initial token calculation before the first prompt
        self._update_and_cache_token_breakdown()

        # Use logger for startup info, which has its own color formatting.
        self.logger.info(f"  Model: {self.formatter.format_success(self.formatter.format_bold(self.model))}")
        self.logger.info("  Type /help for commands, or !<cmd> to run shell commands.\n")

        while True:
            try:
                # 1. Build the prompt message
                prompt_message = self.formatter.format_mode_prompt(self.state.mode)

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
