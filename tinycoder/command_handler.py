import re
import logging
from pathlib import Path # Added for globbing
from typing import TYPE_CHECKING, Callable, Optional, Tuple

from tinycoder.unittest_runner import run_tests
from tinycoder.coverage_tool import run_coverage_summary

if TYPE_CHECKING:
    from tinycoder.file_manager import FileManager
    from tinycoder.git_manager import GitManager
    from tinycoder.docker_manager import DockerManager

# Define CommandHandlerReturn tuple for clarity
CommandHandlerReturn = Tuple[bool, Optional[str]] # bool: continue_processing, Optional[str]: immediate_prompt_arg


class CommandHandler:
    """Handles parsing and execution of slash commands."""

    def __init__(
        self,
        file_manager: "FileManager",
        git_manager: "GitManager",
        docker_manager: Optional["DockerManager"],
        logger: logging.Logger,
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
        add_repomap_exclusion_func: Callable[[str], bool],
        remove_repomap_exclusion_func: Callable[[str], bool],
        get_repomap_exclusions_func: Callable[[], list[str]],
    ):
        """
        Initializes the CommandHandler.

        Args:
            file_manager: An instance of FileManager.
            git_manager: An instance of GitManager.
            docker_manager: An instance of DockerManager, or None.
            logger: The application's configured logger instance.
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
            add_repomap_exclusion_func: Function to add a path/pattern to repomap exclusions.
            remove_repomap_exclusion_func: Function to remove a path/pattern from repomap exclusions.
            get_repomap_exclusions_func: Function to get the list of current repomap exclusions.
        """
        self.file_manager = file_manager
        self.git_manager = git_manager
        self.docker_manager = docker_manager
        self.logger = logger
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
        self.add_repomap_exclusion = add_repomap_exclusion_func
        self.remove_repomap_exclusion = remove_repomap_exclusion_func
        self.get_repomap_exclusions = get_repomap_exclusions_func

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
            patterns_or_literals_raw = re.findall(r"\"(.+?)\"|(\S+)", args_str)
            patterns_or_literals = [name for sublist in patterns_or_literals_raw for name in sublist if name]
            if not patterns_or_literals:
                self.logger.error('Usage: /add <file_or_pattern1> ["file_or_pattern 2"] ...')
                return True, None

            base_path = self.file_manager.root if self.file_manager.root else Path.cwd()

            for p_or_l_arg in patterns_or_literals:
                # Determine if the argument is a pattern or an explicit file path
                is_pattern = any(c in p_or_l_arg for c in ['*', '?', '[', ']'])

                if not is_pattern:
                    # This is an explicit file path, bypass exclusions by using force=True
                    self.logger.debug(f"Treating '{p_or_l_arg}' as an explicit path, bypassing exclusions.")
                    if self.file_manager.add_file(p_or_l_arg, force=True):
                        abs_path_literal = self.file_manager.get_abs_path(p_or_l_arg)
                        if abs_path_literal:
                            rel_path = self.file_manager._get_rel_path(abs_path_literal)
                            self.write_history_func("tool", f"Added {rel_path} to the chat.")
                else:
                    # This is a pattern, apply exclusions by using force=False (the default)
                    self.logger.debug(f"Treating '{p_or_l_arg}' as a pattern, applying exclusions.")
                    matched_paths = list(base_path.glob(p_or_l_arg))

                    if not matched_paths:
                        self.logger.warning(f"Pattern '{p_or_l_arg}' did not match any files or directories.")
                        continue

                    files_added_from_pattern = 0
                    for path in matched_paths:
                        if path.is_file():
                            if self.file_manager.add_file(str(path)):
                                files_added_from_pattern += 1
                                rel_path = self.file_manager._get_rel_path(path)
                                self.write_history_func("tool", f"Added {rel_path} (matched by '{p_or_l_arg}').")
                        elif path.is_dir():
                            rel_path_dir = self.file_manager._get_rel_path(path)
                            self.logger.info(f"Recursively adding from directory '{rel_path_dir}' matched by pattern.")
                            for sub_file in path.rglob('*'):
                                if sub_file.is_file():
                                    if self.file_manager.add_file(str(sub_file)):
                                        files_added_from_pattern += 1
                                        rel_sub_path = self.file_manager._get_rel_path(sub_file)
                                        self.write_history_func("tool", f"Added {rel_sub_path} (from dir '{rel_path_dir}' matched by '{p_or_l_arg}').")
                    
                    if files_added_from_pattern > 0:
                         self.logger.info(f"Added {files_added_from_pattern} file(s) from pattern '{p_or_l_arg}'.")
                    else:
                        self.logger.info(f"Pattern '{p_or_l_arg}' matched items, but no new files were added (they may be excluded or already in context).")

            return True, None

        elif command == "/drop":
            patterns_or_literals_raw = re.findall(r"\"(.+?)\"|(\S+)", args_str)
            patterns_or_literals = [name for sublist in patterns_or_literals_raw for name in sublist if name]
            if not patterns_or_literals:
                self.logger.error('Usage: /drop <file_or_pattern1> ["file_or_pattern 2"] ...')
                return True, None

            base_path = self.file_manager.root if self.file_manager.root else Path.cwd()
            initial_fnames_in_context = set(self.file_manager.get_files())
            
            # Keep track of files already dropped by a glob in this command to avoid reprocessing literals
            files_dropped_by_glob_in_this_command_call = set() # Stores relative paths

            for p_or_l_arg in patterns_or_literals:
                matched_abs_paths = list(base_path.glob(p_or_l_arg))
                
                processed_by_glob_this_arg = False
                if matched_abs_paths:
                    self.logger.info(f"Pattern '{p_or_l_arg}' matched {len(matched_abs_paths)} item(s) for potential dropping.")
                    for abs_path_match in matched_abs_paths:
                        if abs_path_match.is_file():
                            rel_path_match = self.file_manager._get_rel_path(abs_path_match)
                            # Only attempt to drop if it was in context initially
                            if rel_path_match in initial_fnames_in_context:
                                # drop_file takes str path, handles logging and actual removal from fnames
                                if self.file_manager.drop_file(str(abs_path_match)):
                                    files_dropped_by_glob_in_this_command_call.add(rel_path_match)
                                    processed_by_glob_this_arg = True
                        elif abs_path_match.is_dir():
                            rel_path_dir = self.file_manager._get_rel_path(abs_path_match)
                            self.logger.info(f"Pattern '{p_or_l_arg}' matched directory '{rel_path_dir}'. Recursively dropping files from it if in context.")
                            for sub_file_path in abs_path_match.rglob('*'):
                                if sub_file_path.is_file():
                                    rel_sub_file_path = self.file_manager._get_rel_path(sub_file_path)
                                    if rel_sub_file_path in initial_fnames_in_context:
                                        if self.file_manager.drop_file(str(sub_file_path)):
                                           files_dropped_by_glob_in_this_command_call.add(rel_sub_file_path)
                                           processed_by_glob_this_arg = True
                
                if not matched_abs_paths or not processed_by_glob_this_arg:
                    if not matched_abs_paths:
                        self.logger.debug(f"Pattern '{p_or_l_arg}' matched no items for dropping. Treating as a literal file name.")
                    # else: # Glob matched, but no files in context were actioned by it. Try as literal.
                    #    self.logger.debug(f"Glob pattern '{p_or_l_arg}' matched items, but no relevant files were dropped. Trying as literal.")

                    # Before trying as literal, ensure it wasn't already dropped by a previous glob in *this* command call
                    potential_literal_abs_path = self.file_manager.get_abs_path(p_or_l_arg)
                    should_process_literal = True
                    if potential_literal_abs_path:
                        potential_literal_rel_path = self.file_manager._get_rel_path(potential_literal_abs_path)
                        if potential_literal_rel_path in files_dropped_by_glob_in_this_command_call:
                            should_process_literal = False
                    
                    if should_process_literal:
                        self.file_manager.drop_file(p_or_l_arg) # drop_file handles logging

            # History for /drop is based on overall set difference
            dropped_fnames_overall = initial_fnames_in_context - self.file_manager.get_files()
            if dropped_fnames_overall:
                 self.write_history_func("tool", f"Removed {len(dropped_fnames_overall)} file(s) from the chat: {', '.join(sorted(list(dropped_fnames_overall)))}")
            elif patterns_or_literals: # Arguments were given, but nothing was actually removed
                self.logger.info("No files matching the arguments were found in the current chat context to drop.")
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
            self.set_mode("ask")
            if args_str:
                # Log a truncated version of the prompt if it's long
                prompt_preview = args_str[:50] + ('...' if len(args_str) > 50 else '')
                return True, args_str  # Pass args_str as immediate_prompt_arg
            else:
                return True, None

        elif command == "/code":
            self.set_mode("code")
            if args_str:
                # Log a truncated version of the prompt if it's long
                prompt_preview = args_str[:50] + ('...' if len(args_str) > 50 else '')
                return True, args_str  # Pass args_str as immediate_prompt_arg
            else:
                return True, None
        
        elif command == "/suggest_files":
            # args_str contains the optional instruction from the user
            # The _ask_llm_for_files_based_on_context method handles if args_str is empty
            self.suggest_files_func(args_str if args_str else None)
            return True, None

        elif command == "/tests":
            if args_str:
                self.logger.warning("/tests command does not accept arguments.")

            # Make the /tests command Docker-aware
            if self.docker_manager and self.docker_manager.services:
                # Simple heuristic: run tests in the first service available, or look for a 'test' service
                service_to_test = None
                if 'test' in self.docker_manager.services:
                    service_to_test = 'test'
                elif self.docker_manager.services:
                    # Fallback to the first service defined in the compose file
                    service_to_test = next(iter(self.docker_manager.services))
                
                if service_to_test:
                    self.logger.info(f"Docker detected. Running tests in '{service_to_test}' service...")
                    # Prefer concise pytest output in containers: quiet, show only failures/errors, force color
                    test_command_to_run = "pytest -q -r fE --color=yes"
                    self.docker_manager.run_command_in_service(service_to_test, test_command_to_run)
                else:
                    self.logger.warning("Docker detected, but could not determine a service to run tests in. Running locally.")
                    run_tests(self.write_history_func, self.git_manager)
            else:
                run_tests(self.write_history_func, self.git_manager)
            return True, None

        elif command == "/coverage":
            if args_str:
                self.logger.warning("/coverage command does not accept arguments.")
            run_coverage_summary(self.write_history_func, self.git_manager, self.logger)
            return True, None

        elif command == "/docker":
            if not self.docker_manager or not self.docker_manager.is_available:
                self.logger.error("Docker integration is not available or enabled.")
                return True, None

            docker_parts = args_str.split(maxsplit=1)
            sub_command = docker_parts[0] if docker_parts else "ps" # Default to ps
            sub_args = docker_parts[1].strip() if len(docker_parts) > 1 else None

            if sub_command == "ps":
                output = self.docker_manager.get_ps()
                if output:
                    self.logger.info("---\n" + output)
            elif sub_command == "logs":
                if not sub_args:
                    self.logger.error("Usage: /docker logs <service_name>")
                else:
                    self.docker_manager.stream_logs(sub_args)
            elif sub_command == "restart":
                if not sub_args:
                    self.logger.error("Usage: /docker restart <service_name>")
                else:
                    self.docker_manager.restart_service(sub_args)
            elif sub_command == "build":
                if not sub_args:
                    self.logger.error("Usage: /docker build <service_name>")
                else:
                    self.docker_manager.build_service(sub_args)
            else:
                self.logger.error(f"Unknown /docker command '{sub_command}'. Use ps, logs, restart, build.")
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

        elif command == "/showdb":
            if not args_str:
                self.logger.error("Usage: /showdb <database_file_path>")
                return True, None
            
            summary = self.file_manager.get_db_summary(args_str)
            if summary:
                self.logger.info(f"\n--- SQLite DB Summary for {args_str} ---\n{summary}\n----------------------------------")
            # If summary is None, get_db_summary already logged the specific error.
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
            repomap_parts = args_str.split(maxsplit=1)
            sub_command = repomap_parts[0] if repomap_parts else None
            pattern_arg = repomap_parts[1].strip() if len(repomap_parts) > 1 else None

            if sub_command == "on":
                self.toggle_repo_map(True)
            elif sub_command == "off":
                self.toggle_repo_map(False)
            elif sub_command == "show":
                repo_map_content = self.get_repo_map_str_func()
                if repo_map_content and repo_map_content != "Repository map is not available at this moment." and repo_map_content.strip() != "Repository Map (other files):":
                    self.logger.info("--- Current Repository Map ---\n" + repo_map_content)
                else:
                    self.logger.info("Repository map is currently empty, contains no unignored files (excluding those already in chat), or all mappable items are excluded.")
            elif sub_command == "exclude":
                if not pattern_arg:
                    self.logger.error("Usage: /repomap exclude <path_or_pattern>")
                    self.logger.info("  Example: /repomap exclude tests/data/  (to exclude a directory)")
                    self.logger.info("  Example: /repomap exclude src/temp_script.py (to exclude a file)")
                else:
                    if self.add_repomap_exclusion(pattern_arg):
                        self.logger.info(f"Added '{pattern_arg}' to repomap exclusions. It will be ignored when generating the map.")
                        self.logger.info("Note: Use a trailing '/' for directories (e.g., 'docs/').")
                    else:
                        self.logger.info(f"'{pattern_arg}' is already in repomap exclusions or is an empty pattern.")
            elif sub_command == "include": # "include" means remove from exclusions
                if not pattern_arg:
                    self.logger.error("Usage: /repomap include <path_or_pattern_to_remove_from_exclusions>")
                else:
                    if self.remove_repomap_exclusion(pattern_arg):
                        self.logger.info(f"Removed '{pattern_arg}' from repomap exclusions. It will now be considered for the map if it exists.")
                    else:
                        self.logger.info(f"'{pattern_arg}' was not found in repomap exclusions or is an empty pattern.")
            elif sub_command == "list_exclusions":
                exclusions = self.get_repomap_exclusions()
                if exclusions:
                    self.logger.info("Current repomap exclusion patterns (relative to project root):")
                    for pattern in exclusions:
                        self.logger.info(f"  - {pattern}")
                else:
                    self.logger.info("No repomap exclusion patterns are currently set.")
            elif sub_command is None and not pattern_arg : # Just /repomap
                 self.logger.error("Usage: /repomap <on|off|show|exclude|include|list_exclusions> [pattern]")
            else:
                self.logger.error(f"Invalid argument or sub-command for /repomap: '{args_str}'.")
                self.logger.info("  Use: on, off, show, exclude <pattern>, include <pattern>, list_exclusions")
            return True, None

            return True, None

        elif command == "/help":
            help_text = f"""Available commands:
  /add <file1> ["file 2"]...  Add file(s) to the chat context.
  /drop <file1> ["file 2"]... Remove file(s) from the chat context.
  /files                      List files currently in the chat.
  /showdb <db_file>           Show the schema and sample data for a SQLite DB file.
  /suggest_files [instruction] Ask the LLM to suggest relevant files. Uses last user message if no instruction.
  /clear                      Clear the chat history.
  /reset                      Clear chat history and drop all files.
  /commit                     Commit the current changes made by {self.app_name}.
  /undo                       Undo the last commit made by {self.app_name}.
  /ask                        Switch to ASK mode (answer questions, no edits).
  /code                       Switch to CODE mode (make edits).
  /tests                      Run unit tests (runs in container if docker-compose.yml is present).
  /coverage                   Run coverage summary (unittest discovery; summary per file and total).
  /docker ps                  Show status of Docker containers.
  /docker logs <service>      Stream logs from a Docker container.
  /docker restart <service>   Restart a Docker container.
  /docker build <service>     Build a Docker container.
  /rules list                 List available built-in and custom rules and their status for this project.
  /rules enable <rule_name>   Enable a rule for this project.
  /rules disable <rule_name>  Disable a rule for this project.
  /repomap on|off|show        Enable, disable, or show the repository map in prompts.
  /repomap exclude <pattern>  Exclude a file or directory (e.g., 'docs/', 'src/config.py') from the repo map.
  /repomap include <pattern>  Remove a pattern from the exclusion list.
  /repomap list_exclusions    List current repo map exclusion patterns.
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
