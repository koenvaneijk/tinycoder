import argparse
import os
import re
import sys
import traceback
from pathlib import Path
from typing import List, Set, Dict, Tuple, Optional
import importlib.resources

from tinycoder.llms.base import LLMClient
from tinycoder.llms.gemini import GeminiClient, DEFAULT_GEMINI_MODEL
from tinycoder.llms.deepseek import DeepSeekClient, DEFAULT_DEEPSEEK_MODEL
from tinycoder.utils import print_color
from tinycoder.git import GitManager
from tinycoder.repomap import RepoMap
from tinycoder.files import FileManager
from tinycoder.commands import CommandHandler
from tinycoder.edit_parser import EditParser # Import new class
from tinycoder.code_applier import CodeApplier # Import new class

# --- Configuration ---
APP_NAME = "tinycoder"
HISTORY_FILE = ".tinycoder.chat.history.md"
COMMIT_PREFIX = "tinycoder: "

# --- Prompts ---s
# Load prompts using importlib.resources to work when installed as a package
try:
    with importlib.resources.files(__package__).joinpath('prompts/system_prompt_base.md').open('r', encoding='utf-8') as f:
        SYSTEM_PROMPT_BASE = f.read()
    with importlib.resources.files(__package__).joinpath('prompts/system_prompt_ask.md').open('r', encoding='utf-8') as f:
        SYSTEM_PROMPT_ASK = f.read()
    with importlib.resources.files(__package__).joinpath('prompts/system_prompt_diff.md').open('r', encoding='utf-8') as f:
        SYSTEM_PROMPT_DIFF = f.read()
except FileNotFoundError:
    print("Error: Could not find prompt files. Ensure they are included in the package.", file=sys.stderr)
    sys.exit(1)
except Exception as e:
    print(f"Error loading prompt files: {e}", file=sys.stderr)
    sys.exit(1)

# --- Core Application Class ---
class App:
    def __init__(self, model: Optional[str], files: List[str]): # model can be None
        # Determine LLM provider and instantiate the correct client
        self.client: LLMClient # Type hint for the client attribute
        self.model: Optional[str] # Store the actual model name

        # Logic to select client based on model name prefix
        # If no model is specified, default to Gemini for now
        if model and model.startswith("deepseek-"):
            self.client = DeepSeekClient(model=model)
        elif model and model.startswith("gemini-"):
             self.client = GeminiClient(model=model)
        elif not model: # No model specified, use default (Gemini for now)
             print(f"INFO: No model specified, defaulting to Gemini ({DEFAULT_GEMINI_MODEL}).", file=sys.stderr)
             self.client = GeminiClient(model=DEFAULT_GEMINI_MODEL)
        else:
             # Assume Gemini if prefix doesn't match known providers
             # Or potentially raise an error for unknown model types
             print(f"WARNING: Unknown model prefix for '{model}'. Assuming Gemini compatibility.", file=sys.stderr)
             # Attempt to use Gemini client, which might fail if the model name is invalid for Gemini
             try:
                 self.client = GeminiClient(model=model)
             except Exception as e:
                 print(f"Error: Failed to initialize Gemini client for model '{model}'. Please check model name or specify a known provider (e.g., 'gemini-...' or 'deepseek-...'). Error: {e}", file=sys.stderr)
                 sys.exit(1)

        # Store the actual model name being used (resolved by the client)
        self.model = self.client.model

        # self.fnames: Set[str] = set() # Moved to FileManager
        self.chat_history: List[Dict[str, str]] = []
        self.git_manager = GitManager(self._print_error_internal) # Instantiate GitManager
        self.git_root: Optional[str] = self.git_manager.get_root() # Get root from GitManager
        self.file_manager = FileManager(self.git_root, self._print_error_internal, self._print_info_internal, input) # Instantiate FileManager
        self.coder_commits: Set[str] = set() # tinycoder still tracks its own commits
        self.mode = "code"
        self.repo_map = RepoMap(self.git_root, self._print_error_internal) # Pass internal error printer

        # Instantiate CommandHandler
        self.command_handler = CommandHandler(
            file_manager=self.file_manager,
            git_manager=self.git_manager,
            # Pass functions/lambdas for dependencies
            clear_history_func=lambda: self.chat_history.clear(), # Simple clear for now
            write_history_func=self._write_chat_history,
            print_info=self._print_info_internal,
            print_error=self._print_error_internal,
            get_mode=lambda: self.mode,
            set_mode=lambda mode: setattr(self, 'mode', mode),
            git_commit_func=self._git_add_commit,
            git_undo_func=self._git_undo,
            app_name=APP_NAME,
        )

        # Instantiate EditParser and CodeApplier
        self.edit_parser = EditParser(
            print_warning=self._print_warning_internal,
            fnames_provider=self.file_manager.get_files # Pass method reference
        )
        self.code_applier = CodeApplier(
            file_manager=self.file_manager,
            git_manager=self.git_manager,
            input_func=input, # Use built-in input
            print_info=self._print_info_internal,
            print_error=self._print_error_internal,
        )

        self.lint_errors_found: Dict[str, str] = {} # Still managed by App for reflection loop
        self.reflected_message: Optional[str] = None # To store messages for reflection (like lint errors)

        # ANSI color map
        self.colors = {
            "user": "green",
            "assistant": "blue",
            "tool": "yellow",
            "error": "red",
            "info": "cyan",
            "warning": "yellow", # Add warning color
        }

        if not self.git_root:
            print_color("Warning: Not inside a git repository. Git integration (commit/undo) will be disabled.", "yellow")
        # else: # Optional: Confirm git root found
        #    self._print("info", f"Git repository root found at: {self.git_root}")

        # Add initial files using FileManager
        for fname in files:
            self.file_manager.add_file(fname) # Use FileManager

        # Simplified history loading - might need improvement for robustness
        self.load_chat_history()

    def _print(self, role: str, text: str):
        """Helper to print colored output."""
        color = self.colors.get(role, "reset")
        print_color(f"{role.upper()}: {text}", color)

    def _print_error_internal(self, text: str):
        """Internal helper for RepoMap to print errors."""
        self._print("error", text)

    def _print_info_internal(self, text: str):
        """Internal helper for FileManager/CodeApplier to print info."""
        self._print("info", text)

    def _print_warning_internal(self, text: str):
        """Internal helper for EditParser to print warnings."""
        self._print("warning", text) # Assuming 'warning' color exists or defaults

    def _add_to_history(self, role: str, content: str):
        """Adds a message to the chat history."""
        self.chat_history.append({"role": role, "content": content})
        self._write_chat_history(role, content)

    def _write_chat_history(self, role: str, content: str):
        """Appends a message to the history markdown file."""
        try:
            with open(HISTORY_FILE, "a", encoding="utf-8") as f:
                prefix = "> " if role == "tool" else "#### " if role == "user" else ""
                # Basic escaping of ``` for markdown history
                content_md = content.replace("```", "\\```")
                f.write(f"{prefix}{content_md.strip()}\n\n")
        except Exception as e:
            self._print("error", f"Could not write to history file {HISTORY_FILE}: {e}")

    def load_chat_history(self):
        """Loads chat history from the markdown file (Simplified)."""
        if not os.path.exists(HISTORY_FILE):
            return

        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                content = f.read()
            # Super simple parsing: Assume blocks separated by #### or > are messages
            # This won't perfectly reconstruct Coder's complex history but gives a basic load
            potential_messages = re.split(r'\n\n(?:#### |> )', content)
            current_role = "assistant" # Assume first non-meta block is assistant
            for block in potential_messages:
                block = block.strip()
                if not block or block.startswith("# coder chat started at"):
                    continue
                # Basic check if it looks like user input (starts without special prefix)
                # This is fragile.
                is_user = not block.startswith(("Assistant:", "Tool:", "Error:", "Info:", "Warning:", "> ", "#### "))
                role = "user" if is_user else "assistant"

                # Crude role alternation if the simple check fails
                if role == current_role :
                    role = "user" if current_role == "assistant" else "assistant"

                # Unescape markdown code fences
                block_content = block.replace("\\```", "```")
                self.chat_history.append({"role": role, "content": block_content})
                current_role = "user" if role == "assistant" else "assistant"

            self._print("info", f"Loaded ~{len(self.chat_history)} messages from {HISTORY_FILE} (basic parsing)")
        except Exception as e:
            self._print("error", f"Could not load/parse history file {HISTORY_FILE}: {e}")

    def _build_system_prompt(self) -> str:
        """Builds the system prompt including file list and repo map."""
        current_fnames = sorted(list(self.file_manager.get_files()))
        fnames_block = "\n".join(f"- `{fname}`" for fname in current_fnames)
        if not fnames_block:
            fnames_block = "(No files added to chat yet)"

        # Generate repo map for files *not* in chat
        # Ensure RepoMap uses the correct root from GitManager if available
        self.repo_map.root = Path(self.git_manager.get_root()) if self.git_manager.is_repo() else Path.cwd()
        repomap_block = self.repo_map.generate_map(self.file_manager.get_files()) # Use FileManager

        prompt_template = SYSTEM_PROMPT_ASK if self.mode == "ask" else SYSTEM_PROMPT_BASE
        base = prompt_template.format(fnames_block=fnames_block, repomap_block=repomap_block)

        if self.mode == "code":
            # Always use the standard diff prompt
            return base + SYSTEM_PROMPT_DIFF
        else: # ask mode
            return base

    def _send_to_llm(self) -> Optional[str]:
        """Sends the current chat history and file context to the LLM."""
        if not self.chat_history or self.chat_history[-1]["role"] != "user":
            self._print("error", "Cannot send to LLM without a user message.")
            return None

        system_prompt_msg = {"role": "system", "content": self._build_system_prompt()}

        # Prepare file context message using FileManager
        file_context_message = []
        if self.file_manager.get_files(): # Check using FileManager
            file_content_str = self.file_manager.get_content_for_llm() # Use FileManager
            # Include file content as a user message BEFORE the actual user query
            file_context_message = [{"role": "user", "content": file_content_str}]
            # Optional: Add an assistant "OK" to keep alternation, mimics Coder more closely
            # file_context_message.append({"role": "assistant", "content": "Ok, I have the file content."})


        # Combine messages: System Prompt, File Context, Chat History
        # Place file context right before the last user message for relevance
        messages_to_send = [system_prompt_msg] + self.chat_history[:-1] + file_context_message + [self.chat_history[-1]]

        # Simple alternation check (might need refinement for edge cases)
        final_messages = []
        last_role = "system" # Start assuming system
        for msg in messages_to_send:
            if msg['role'] == 'system': # Allow system messages anywhere
                 final_messages.append(msg)
                 # Don't update last_role for system message
                 continue
            if msg['role'] == last_role:
                 # Insert placeholder if consecutive non-system roles are the same
                 if last_role == 'user':
                      final_messages.append({'role':'assistant', 'content':'(placeholder)'})
                 else:
                      final_messages.append({'role':'user', 'content':'(placeholder)'})
            final_messages.append(msg)
            last_role = msg['role']


        try:
            # print("DEBUG: Sending messages to LLM:") # Keep for debugging
            # for msg in final_messages:
            #    print(f"  Role: {msg['role']}, Content: {msg['content'][:100]}...")
            # print("-" * 20)

            # --- Use the selected LLM client ---
            # The client interface expects system_prompt and history separately.
            system_prompt_text = ""
            history_to_send = []

            # Extract system prompt if present
            if final_messages and final_messages[0]['role'] == 'system':
                system_prompt_text = final_messages[0]['content']
                history_to_send = final_messages[1:] # Exclude system prompt from history
            else:
                 # If no system prompt was built (e.g., empty history?), send history as is
                 history_to_send = final_messages
                 self._print("warning", "System prompt not found at the beginning of messages for LLM.")

            # Call the client's generate_content method (works polymorphically)
            response_content, error_message = self.client.generate_content(
                system_prompt=system_prompt_text,
                history=history_to_send
            )

            # --- Handle response ---
            if error_message:
                self._print("error", f"Error calling LLM API ({self.client.__class__.__name__}): {error_message}")
                return None
            elif response_content is None:
                 # Should be covered by error_message, but handle defensively
                 self._print("error", f"LLM API ({self.client.__class__.__name__}) returned no content and no error message.")
                 return None
            else:
                # print(f"DEBUG: Received response:\n{response_content}") # Keep for debugging
                return response_content

        except Exception as e:
            # Catch any unexpected errors during the process
            self._print("error", f"An unexpected error occurred preparing for or handling LLM API call ({self.client.__class__.__name__}): {e}")
            # Print traceback for debugging unexpected issues
            traceback.print_exc()
    def _git_add_commit(self):
        """Stage changes to added files and commit them using GitManager."""
        if not self.git_manager.is_repo():
            self._print("info", "Not in a git repository, skipping commit.")
            return

        # Resolve relative paths in self.fnames to absolute and relative for GitManager
        files_to_process_abs = []
        files_to_process_rel = []

        # Get files from FileManager
        current_fnames = self.file_manager.get_files()
        if not current_fnames:
            self._print("info", "No files in chat context to commit.")
            return

        for fname in current_fnames: # fname is relative path
            abs_path = self.file_manager.get_abs_path(fname) # Use FileManager
            if abs_path and abs_path.exists():
                 files_to_process_abs.append(str(abs_path))
                 files_to_process_rel.append(fname) # Already have relative path
            # else: # Optional: Warn if file in context doesn't exist?
            #    self._print("warning", f"File {fname} in chat context does not exist on disk, skipping for commit.")

        if not files_to_process_abs:
            self._print("info", "No existing files in chat context to check for changes.")
            return

        # Prepare commit message
        commit_message = f"{COMMIT_PREFIX} Changes to {', '.join(sorted(files_to_process_rel))}"

        # Call GitManager to commit
        commit_hash = self.git_manager.commit_files(files_to_process_abs, files_to_process_rel, commit_message)

        if commit_hash:
            self.coder_commits.add(commit_hash)
            # Success message printed by GitManager
        # else: # Failure messages printed by GitManager

    def _git_undo(self):
        """Undo the last commit made by this tool using GitManager."""
        if not self.git_manager.is_repo():
            self._print("error", "Not in a git repository.")
            return

        last_hash = self.git_manager.get_last_commit_hash()
        if not last_hash:
            # Error already printed by GitManager
            return

        if last_hash not in self.coder_commits:
            self._print("error", f"Last commit {last_hash} was not made by {APP_NAME}.")
            self._print("info", "You can manually undo with 'git reset HEAD~1'")
            return

        # Call GitManager to undo
        success = self.git_manager.undo_last_commit(last_hash)

        if success:
            self.coder_commits.discard(last_hash) # Remove hash if undo succeeded
            self._write_chat_history("tool", f"Undid commit {last_hash}")

    def check_for_file_mentions(self, inp: str):
        """Placeholder: Checks for file mentions in user input."""
        # TODO: Implement logic to find potential file paths in `inp`
        # and maybe suggest adding them using self.add_file() or print a warning.
        pass # Currently does nothing

    def check_for_urls(self, inp: str) -> str:
        """Placeholder: Checks for URLs in user input."""
        # TODO: Implement logic to find URLs. Could potentially fetch content
        # or just return the input string unchanged.
        return inp # Currently returns input unchanged

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
             self._print("assistant", response)
             self._add_to_history("assistant", response)

             # Only try to parse and apply edits if in code mode
             if self.mode == "code":
                 edits = self.edit_parser.parse(response)
                 if edits:
                     applied_any, lint_errors = self.code_applier.apply_edits(edits)
                     self.lint_errors_found = lint_errors # Update App state

                     if applied_any:
                         # Optional: Auto-commit after successful edits
                         # self._git_add_commit()
                         pass # Placeholder for now
                     else:
                         # This case might be covered by CodeApplier's error messages,
                         # but we can add a summary here if needed.
                         # self._print("info", "No edits were successfully applied.")
                         pass

                 else: # No edits found by parser
                     # Check if the LLM just output code without the edit block format
                     # Use the parser's regex for consistency
                     code_block_match = self.edit_parser.code_block_pattern.search(response)
                     # Check if the *whole* response is just a code block (allow it),
                     # but warn if code appears *within* text without the block format.
                     is_just_code = response.strip().startswith("```") and response.strip().endswith("```")
                     if code_block_match and not is_just_code :
                          self._print("warning", "The LLM provided code but didn't use the required edit format. No changes applied.")
                     elif not code_block_match: # No edits and no code blocks found
                          self._print("info", "No edit blocks found in the response.")

                 # --- Check for Lint Errors ---
                 if self.lint_errors_found:
                     error_messages = ["Found syntax errors after applying edits:"]
                     for fname, error in self.lint_errors_found.items():
                         error_messages.append(f"\n--- Errors in {fname} ---\n{error}")
                     combined_errors = "\n".join(error_messages)
                     self._print("error", combined_errors)

                     fix_lint = input("Attempt to fix lint errors? (y/N): ")
                     if fix_lint.lower() == 'y':
                         self.reflected_message = combined_errors # Set message for next LLM call
                         # The loop in run_one will handle sending this reflected message
                     # else: lint errors are ignored for this round

         else:
             # Handle LLM call failure
             self._print("error", "Failed to get response from LLM.")

    def init_before_message(self):
        """Resets state before processing a new user message."""
        self.lint_errors_found = {}
        self.reflected_message = None

    def run_one(self, user_message, preproc):
        """Processes a single user message, including potential reflection loops."""
        self.init_before_message()

        if preproc:
            message = self._handle_command(user_message) if user_message.startswith("/") else self.preproc_user_input(user_message)
            if message is True: # Command handled, no further processing needed for this input
                 return
            elif message is False: # Exit command
                 return False # Signal exit to main loop
        else:
            message = user_message

        # Loop for handling reflections (like fixing lint errors)
        num_reflections = 0
        max_reflections = 3
        while message:
            self._add_to_history("user", message)
            self.process_user_input() # This now handles LLM call, edits, linting

            if not self.reflected_message:
                 break # No reflection needed, exit loop

            if num_reflections >= max_reflections:
                 self._print("warning", f"Reached max reflection limit ({max_reflections}). Stopping.")
                 break

            num_reflections += 1
            self._print("info", f"Reflection {num_reflections}: Sending feedback to LLM...")
            message = self.reflected_message # Use the reflected message as the next input
            # process_user_input clears self.reflected_message, so it won't loop infinitely unless set again

        return True # Indicate normal processing occurred (or finished reflection loop)


    def run(self):
        """Main loop for the chat application."""
        self._print("info", f"Welcome to {APP_NAME}! Model: {self.model}. Type /help for commands.")
        while True:
            try:
                # Construct the prompt string dynamically
                prompt_str = f"({self.mode}) " # Edit format removed from prompt
                prompt_str += ">>> "

                inp = input(prompt_str)
                if not inp.strip():
                    continue

                if inp.startswith("/"):
                    # Use the CommandHandler
                    status, prompt = self.command_handler.handle(inp)

                    if not status:
                        break # Exit command was received

                    if prompt:
                        # Command included a prompt (e.g., /ask "What is...?"), process it directly
                        if not self.run_one(prompt, preproc=False): # Don't preprocess command args
                            break # Exit signal from run_one
                    else:
                        # Command handled, continue to next input prompt
                        continue

                else: # Regular user message (not a command)
                    # Preprocessing (URL/file mentions) happens within run_one if preproc=True
                    if not self.run_one(inp, preproc=True):
                         break # Exit signal from run_one

            except (KeyboardInterrupt, EOFError):
                break # Exit on Ctrl+C or Ctrl+D

        print_color("\nGoodbye!", "info")
        # Consider saving history explicitly here if needed, though it's appended live

# --- Main Execution ---
def main():
    parser = argparse.ArgumentParser(description=f"{APP_NAME} - A simplified AI coding assistant.")
    parser.add_argument(
        "files",
        metavar="FILE",
        nargs="*",
        help="Files to add to the chat context on startup."
    )
    parser.add_argument(
        "--model",
        metavar="MODEL_NAME",
        # Default model selection is now handled in tinycoder.__init__ if None is passed
        default=None,
        help=f"LLM model to use (e.g., 'gemini-2.5-pro-preview-03-25', 'deepseek-chat'). Determines the API provider. Defaults to Gemini if unspecified."
    )
    # Optional: Add a separate --llm-provider argument if needed for more complex scenarios
    # parser.add_argument("--llm-provider", choices=["gemini", "deepseek"], help="Explicitly choose the LLM provider.")

    args = parser.parse_args()

    # Removed validation check related to edit format

    coder = App(model=args.model, files=args.files) # Removed edit_format argument
    coder.run()

if __name__ == "__main__":
    main()
