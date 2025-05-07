import logging
import shlex
import subprocess
from pathlib import Path
from typing import Optional

from tinycoder.chat_history import ChatHistoryManager


class ShellExecutor:
    """Handles the execution of shell commands prefixed with '!'."""

    def __init__(self, logger: logging.Logger, history_manager: ChatHistoryManager, git_root: Optional[str]):
        """
        Initializes the ShellExecutor.

        Args:
            logger: The logger instance for outputting messages.
            history_manager: The chat history manager to record command output if requested.
            git_root: The root directory of the git repository, if available.
                      Used as the current working directory for commands.
        """
        self.logger = logger
        self.history_manager = history_manager
        self.git_root = git_root

    def execute(self, command_with_prefix: str, non_interactive: bool) -> bool:
        """
        Executes a shell command.

        Args:
            command_with_prefix: The full command string, including the '!' prefix (e.g., "!ls -la").
            non_interactive: If True, suppresses prompts (e.g., for adding output to context).

        Returns:
            True if the command was recognized and an attempt was made to execute it (or an error reported).
            This indicates that the input has been "handled" for the main app loop.
        """
        cmd_str = command_with_prefix[1:].strip()
        if not cmd_str:
            self.logger.error("Usage: !<shell_command>")
            return True  # Handled by showing error, continue main loop

        self.logger.info(f"Executing shell command: {cmd_str}")
        cmd_args: list[str] = [] # Ensure cmd_args is defined for FileNotFoundError block
        try:
            cmd_args = shlex.split(cmd_str)
            cwd = Path(self.git_root) if self.git_root else Path.cwd()
            
            result = subprocess.run(
                cmd_args,
                capture_output=True,
                text=True,
                check=False,  # Don't raise exception on non-zero exit code
                cwd=cwd,
            )

            command_output_parts = []
            stdout_content = result.stdout.strip() if result.stdout else ""
            stderr_content = result.stderr.strip() if result.stderr else ""

            if stdout_content:
                command_output_parts.append(f"--- stdout ---\n{stdout_content}")
            if stderr_content:
                command_output_parts.append(f"--- stderr ---\n{stderr_content}")

            combined_output = "\n".join(command_output_parts)
            full_output_for_history = (
                f"Output of shell command: `{cmd_str}`\n{combined_output}"
            )

            # Print output/error to console
            print("--- Shell Command Output ---")
            if stdout_content:
                print(stdout_content)  # Use plain print for console
            if stderr_content:
                # Using logger.error for stderr to get consistent formatting/coloring
                self.logger.error(f"Shell command stderr:\n{stderr_content}")
            if result.returncode != 0:
                self.logger.warning(
                    f"Shell command '{cmd_str}' exited with code {result.returncode}"
                )
            print("--- End Shell Command Output ---")

            if combined_output and not non_interactive:
                try:
                    # Use built-in input for this prompt
                    add_to_context_input = input(
                        "Add shell command output to chat context? (y/N): "
                    )
                except EOFError: # Handle non-interactive scenarios where input might fail
                    add_to_context_input = "n"
                    print() # Newline after simulated EOF
                except KeyboardInterrupt:
                    self.logger.info("\nShell output addition to context cancelled.")
                    add_to_context_input = "n"
                
                if add_to_context_input.lower() == "y":
                    self.history_manager.add_message(
                        "tool", full_output_for_history
                    )
                    self.logger.info("Shell command output added to chat context.")
            
            return True  # Command was handled

        except FileNotFoundError:
            # cmd_args might not be populated if shlex.split failed, but cmd_args[0] relies on it.
            # Use cmd_str for a more robust error message if cmd_args is empty.
            command_name = cmd_args[0] if cmd_args else cmd_str.split()[0] if cmd_str else "Unknown"
            self.logger.error(f"Shell command not found: {command_name}")
            return True  # Command was "handled" by reporting an error
        except Exception as e:
            self.logger.error(f"Error executing shell command '{cmd_str}': {e}", exc_info=self.logger.isEnabledFor(logging.DEBUG))
            return True  # Command was "handled" by reporting an error