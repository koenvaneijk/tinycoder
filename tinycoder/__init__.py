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

# --- Configuration ---
APP_NAME = "tinycoder"
HISTORY_FILE = ".tinycoder.chat.history.md"
COMMIT_PREFIX = "tinycoder: "

# --- Prompts ---
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
        self.lint_errors_found: Dict[str, str] = {}
        self.reflected_message: Optional[str] = None # To store messages for reflection (like lint errors)

        # ANSI color map
        self.colors = {
            "user": "green",
            "assistant": "blue",
            "tool": "yellow",
            "error": "red",
            "info": "cyan",
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
        """Internal helper for FileManager to print info."""
        self._print("info", text)

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

    # --- File operations moved to FileManager ---
    # get_abs_path
    # _get_file_content_for_llm
    # add_file
    # drop_file

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
            return None


    def _parse_edits(self, response: str) -> List[Tuple[str, str, str]]:
        """Parses diff/diff-fenced edit blocks from the LLM response."""
        edits = []
        # Regex for the inner SEARCH/REPLACE structure
        edit_block_pattern = re.compile(
            r"<<<<<<< SEARCH\s*\n([\s\S]*?)\n=======\s*\n([\s\S]*?)\n>>>>>>> REPLACE",
            re.DOTALL
        )

        # Regex for code blocks (```lang\n...\n```)
        # Make language optional? No, stick to python/diff for now as per prompt.
        code_block_pattern = re.compile(
            r"```(?:python|diff)\s*\n([\s\S]*?)\n```",
            re.DOTALL
        )

        # Find all potential code blocks first
        potential_code_blocks = code_block_pattern.finditer(response)

        # Keep track of the end position of the last processed match to avoid overlap/double matching filename
        last_pos = 0

        for code_match in potential_code_blocks:
            code_content_full = code_match.group(1) # Content inside ```...```
            code_block_start, code_block_end = code_match.span()

            # Check if this block contains the SEARCH/REPLACE markers
            # Use search instead of finditer if we only expect one edit per block (safer assumption?)
            # No, LLM might provide multiple edits for one file in one block. Stick with finditer.
            inner_matches_found = list(edit_block_pattern.finditer(code_content_full))
            if not inner_matches_found:
                continue # This code block doesn't contain edits, skip

            # --- Determine the filename ---
            fname = None
            code_content_for_edits = code_content_full # Default content for parsing edits

            # Case 1: Filename is the first line *inside* the code block
            lines = code_content_full.split('\n', 1)
            first_line_inside = lines[0].strip()
            # Basic check: does it look like a path? (contains / or \ or ends with common extension)
            # Avoid matching keywords like 'python' or the SEARCH marker itself
            # Also check it's not empty
            if first_line_inside and \
               not first_line_inside.startswith("<<<<<<< SEARCH") and \
               first_line_inside not in {"python", "diff"} and \
               ('/' in first_line_inside or '\\' in first_line_inside or '.' in first_line_inside):
                 # Check if the *rest* of the content contains the edit block start marker
                 # This ensures the first line IS the filename and not part of the search block
                 if len(lines) > 1 and edit_block_pattern.search(lines[1]):
                     fname = first_line_inside
                     # Adjust content to exclude the filename line for inner parsing
                     code_content_for_edits = lines[1]
                     # Re-run inner matches on the adjusted content
                     inner_matches_found = list(edit_block_pattern.finditer(code_content_for_edits))


            # Case 2: Filename is on the line *before* the code block
            if fname is None:
                # Search backwards from the start of the code block in the original response
                # Ensure we don't re-read text processed by previous block matches
                search_start = response.rfind('\n', 0, code_block_start) + 1 # Start of the line before the block
                if search_start < last_pos: # Avoid overlap with previous matches/filenames
                     search_start = last_pos

                preceding_text = response[search_start:code_block_start]
                lines_before = preceding_text.strip().split('\n')
                if lines_before:
                    last_line_before = lines_before[-1].strip()
                    # Basic check: does it look like a path?
                    if last_line_before and \
                       last_line_before not in {"python", "diff"} and \
                       ('/' in last_line_before or '\\' in last_line_before or '.' in last_line_before):
                        fname = last_line_before
                        # Use the original full content for inner parsing
                        code_content_for_edits = code_content_full
                        # Reset inner matches based on full content (already done above)
                        inner_matches_found = list(edit_block_pattern.finditer(code_content_for_edits))


            # --- If filename is still undetermined ---
            if fname is None:
                 # Fallback or Warning
                 self._print("warning", f"Could not determine filename for edit block:\n```\n{code_content_full[:100]}...\n```")
                 # Option: Default to first file in chat?
                 if self.fnames:
                     fname = list(sorted(self.fnames))[0] # Use sorted list for determinism
                     self._print("warning", f"Assuming edit applies to the first file in chat: {fname}")
                     code_content_for_edits = code_content_full # Use original content
                     # Reset inner matches based on full content
                     inner_matches_found = list(edit_block_pattern.finditer(code_content_for_edits))
                 else:
                     self._print("error", "Cannot apply edit block - no filename found and no files in chat.")
                     continue # Skip this block

            # --- Extract edits using the determined content ---
            if fname: # Ensure filename was found or defaulted
                for match in inner_matches_found: # Use the potentially updated inner_matches
                    search_block, replace_block = match.groups()
                    edits.append((fname, search_block, replace_block))

            # Update last position to prevent the next iteration from re-parsing this block's preceding line
            last_pos = code_block_end


        # Post-process all found edits (same as before)
        processed_edits = []
        for fname, search_block, replace_block in edits:
             # Normalize line endings to LF for comparison and application
             search_block = search_block.replace('\r\n', '\n')
             replace_block = replace_block.replace('\r\n', '\n')

             # Handle case where replace_block is meant to be empty (deletion)
             if replace_block.strip() == "":
                  replace_block = "" # Explicitly empty

             processed_edits.append((fname.strip(), search_block, replace_block))

        return processed_edits

    def _lint_python_compile(self, abs_path: Path, content: str) -> Optional[str]:
        """Checks python syntax using compile(). Returns error string or None."""
        try:
            compile(content, str(abs_path), "exec")
            return None
        except (SyntaxError, ValueError) as err: # Catch ValueError for null bytes etc.
            # Format traceback similar to Coder's linter
            tb_lines = traceback.format_exception(type(err), err, err.__traceback__)

            # Find the start of the traceback relevant to the compile error
            traceback_marker = "Traceback (most recent call last):"
            relevant_lines = []
            in_relevant_section = False
            for line in tb_lines:
                if traceback_marker in line:
                    in_relevant_section = True
                if in_relevant_section:
                    # Exclude the frame pointing to our internal compile() call
                    if 'compile(content, str(abs_path), "exec")' not in line:
                         relevant_lines.append(line)

            # If we couldn't filter properly, return the whole traceback
            if not relevant_lines or not any(str(abs_path) in line for line in relevant_lines):
                 formatted_error = "".join(tb_lines)
            else:
                 formatted_error = "".join(relevant_lines)

            return f"Syntax error in {abs_path.name}:\n```\n{formatted_error}\n```"


    def _apply_edits(self, edits: List[Tuple[str, str, str]]) -> bool:
        """Applies the parsed edits to the files."""
        applied_edit_to_at_least_one_file = False
        failed_edits = []
        edited_py_files: Dict[str, str] = {} # Store {fname: new_content} for linting
        applied_files: Set[str] = set() # Track relative paths of files edited

        for i, (fname, search_block, replace_block) in enumerate(edits):
            abs_path = self.file_manager.get_abs_path(fname) # Use FileManager
            if not abs_path:
                 # Error printed by get_abs_path
                 failed_edits.append(i)
                 continue

            # Ensure file is in chat context or get confirmation
            # Determine relative path for checking `self.fnames`
            git_root_path = Path(self.git_manager.get_root()) if self.git_manager.is_repo() else None
            base_path = git_root_path if git_root_path else Path.cwd()
            try:
                 rel_path_check = str(abs_path.relative_to(base_path))
            except ValueError:
                 rel_path_check = str(abs_path) # Use absolute if not relative to base

            # Use FileManager to check if file is in context
            if rel_path_check not in self.file_manager.get_files():
                 confirm = input(f"LLM wants to edit '{rel_path_check}' which is not in the chat. Allow? (y/N): ")
                 if confirm.lower() == 'y':
                     # Use the original fname the user might have typed, or the resolved relative path
                     self.file_manager.add_file(fname) # Use FileManager
                     # Re-check if adding succeeded (it might fail if file doesn't exist and user says no)
                     if rel_path_check not in self.file_manager.get_files():
                           self._print("error", f"Could not add '{fname}' for editing.")
                           failed_edits.append(i)
                           continue
                 else:
                     self._print("info", f"Skipping edit for {fname}.")
                     failed_edits.append(i)
                     continue

            is_new_file = not abs_path.exists() or (search_block == "" and (not abs_path.exists() or abs_path.stat().st_size == 0))

            if is_new_file:
                 if search_block != "":
                      self._print("error", f"Edit for new file {fname} has a non-empty SEARCH block. Skipping.")
                      failed_edits.append(i)
                      continue
                 self._print("info", f"Creating and writing new file {rel_path_check}")
                 # Use FileManager to write the new file
                 if self.file_manager.write_file(abs_path, replace_block):
                     applied_edit_to_at_least_one_file = True
                     applied_files.add(rel_path_check) # Track new file
                     if abs_path.suffix == '.py': # Lint new python files too
                         edited_py_files[rel_path_check] = replace_block
                 else:
                     # Error printed by write_file
                     failed_edits.append(i)
                 continue # Move to next edit

            # --- Existing file logic ---
            try:
                # Use FileManager to read the file
                original_content = self.file_manager.read_file(abs_path)
                if original_content is None:
                    # Error printed by read_file
                    failed_edits.append(i)
                    continue

                original_content_normalized = original_content.replace('\r\n', '\n')

                # The search needs to be exact.
                if search_block not in original_content_normalized:
                    self._print("error", f"SEARCH block not found exactly in {fname}. Edit {i+1} failed.")
                    # Provide context for debugging
                    # print(f"---EXPECTED (SEARCH)---\n{search_block}\n-----------------------")
                    # print(f"---ACTUAL (CONTENT抜粋)---\n{original_content_normalized[max(0, original_content_normalized.find(search_block[:20])-50):original_content_normalized.find(search_block[:20])+len(search_block)+50]}\n-----------------------")
                    failed_edits.append(i)
                    continue

                # Perform the replacement
                new_content_normalized = original_content_normalized.replace(search_block, replace_block, 1)

                # Restore original line endings
                if '\r\n' in original_content:
                    new_content = new_content_normalized.replace('\n', '\r\n')
                else:
                    new_content = new_content_normalized # This line might be redundant now, but keep for context

                # Only write if content actually changed (normalized comparison)
                # Note: write_file handles line ending restoration
                if new_content_normalized != original_content_normalized:
                    # Use FileManager to write the file
                    if self.file_manager.write_file(abs_path, new_content_normalized):
                        self._print("info", f"Applied edit {i+1} to {rel_path_check}")
                        applied_edit_to_at_least_one_file = True
                        applied_files.add(rel_path_check)
                        # Store normalized content for linting if it's a python file
                        if abs_path.suffix == '.py':
                            edited_py_files[rel_path_check] = new_content_normalized
                    else:
                        # Error printed by write_file
                        failed_edits.append(i)
                else:
                     self._print("info", f"Edit {i+1} for {rel_path_check} resulted in no changes. Skipping write.")
                     # Still need to lint even if no changes, in case the edit *fixed* a syntax error
                     if abs_path.suffix == '.py':
                         # Use the normalized content which might be different due to line endings only
                         edited_py_files[rel_path_check] = new_content_normalized


            except FileNotFoundError:
                 self._print("error", f"File {rel_path_check} vanished before edit {i+1} could be applied.")
                 failed_edits.append(i)
            except Exception as e:
                self._print("error", f"Error applying edit {i+1} to {fname}: {e}")
                failed_edits.append(i)

        if failed_edits:
            self._print("error", f"Failed to apply edits: {', '.join(map(lambda x: str(x+1), failed_edits))}")

        # --- Lint Python files after edits ---
        # Lint all python files that were touched or newly created
        for rel_path in applied_files:
            if rel_path.endswith('.py'):
                abs_path = self.file_manager.get_abs_path(rel_path) # Use FileManager
                if abs_path:
                    content_to_lint = edited_py_files.get(rel_path) # Get potentially modified content
                    if content_to_lint is None: # If not in edited_py_files, read from disk
                        content_to_lint = self.file_manager.read_file(abs_path) # Use FileManager

                    if content_to_lint is not None:
                        error_string = self._lint_python_compile(abs_path, content_to_lint)
                        if error_string:
                            self.lint_errors_found[rel_path] = error_string
                    else:
                         self._print("warning", f"Could not read {rel_path} for linting after edit.")


        return applied_edit_to_at_least_one_file


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
        # else: # Failure messages printed by GitManager


    def _handle_command(self, inp: str) -> bool:
        """Handles slash commands, returns True if handled."""
        parts = inp.strip().split(maxsplit=1)
        command = parts[0]
        args = parts[1].strip() if len(parts) > 1 else "" # Strip args here

        if command == "/add":
            filenames = re.findall(r"\"(.+?)\"|(\S+)", args) # Handle quoted filenames
            filenames = [name for sublist in filenames for name in sublist if name]
            if not filenames:
                 self._print("error", "Usage: /add <file1> [\"file 2\"] ...")
            else:
                 for fname in filenames:
                      self.file_manager.add_file(fname) # Use FileManager
                      # Write history entry here, as FileManager doesn't do it
                      # Need to resolve fname to the stored relative path for accurate history
                      abs_path = self.file_manager.get_abs_path(fname)
                      if abs_path:
                          rel_path = self.file_manager._get_rel_path(abs_path)
                          if rel_path in self.file_manager.get_files(): # Check if add succeeded
                               self._write_chat_history("tool", f"Added {rel_path} to the chat.")
        elif command == "/drop":
            filenames = re.findall(r"\"(.+?)\"|(\S+)", args) # Handle quoted filenames
            filenames = [name for sublist in filenames for name in sublist if name] # Flatten list of tuples
            if not filenames:
                 self._print("error", "Usage: /drop <file1> [\"file 2\"] ...")
            else:
                initial_fnames = set(self.file_manager.get_files()) # Copy before dropping
                for fname in filenames:
                      self.file_manager.drop_file(fname) # Use FileManager
                # Write history for files actually dropped
                dropped_fnames = initial_fnames - self.file_manager.get_files()
                for fname in dropped_fnames: # fname here is the relative path
                     self._write_chat_history("tool", f"Removed {fname} from the chat.")
        elif command == "/clear":
            self.chat_history = []
            self._print("info", "Chat history cleared.")
            self._write_chat_history("tool", "Chat history cleared.")
        elif command == "/reset":
            self.file_manager.fnames = set() # Reset FileManager's set
            self.chat_history = []
            self._print("info", "Chat history and file list cleared.")
            self._write_chat_history("tool", "Chat history and file list cleared.")
        elif command == "/commit":
            self._git_add_commit()
        elif command == "/undo":
             self._git_undo()
        elif command == "/ask":
             self.mode = "ask"
             self._print("info", "Switched to ASK mode. I will answer questions but not edit files.")
             if args: # If user provided a prompt with /ask
                 # Let run_one handle adding to history and processing
                 return args # Return the prompt for run_one
        elif command == "/code":
             self.mode = "code"
             self._print("info", "Switched to CODE mode. I will try to edit files.")
             if args: # If user provided a prompt with /code
                 # Let run_one handle adding to history and processing
                 return args # Return the prompt for run_one
        # Removed /format command as only 'diff' is supported now
        elif command == "/files":
            current_fnames = self.file_manager.get_files()
            if not current_fnames:
                 self._print("info", "No files are currently added to the chat.")
            else:
                 self._print("info", "Files in chat:")
                 for fname in sorted(list(current_fnames)):
                      print(f"- {fname}") # Use standard print for clean list
        elif command == "/help":
             self._print("info", """Available commands:
  /add <file1> ["file 2"]...  Add file(s) to the chat context.
  /drop <file1> ["file 2"]... Remove file(s) from the chat context.
  /files                      List files currently in the chat.
  /clear                      Clear the chat history.
  /reset                      Clear chat history and drop all files.
  /commit                     Commit the current changes made by this tool.
  /undo                       Undo the last commit made by this tool.
  /ask [question]             Switch to ASK mode (answer questions, no edits) or ask a question directly.
  /code [instruction]         Switch to CODE mode (make edits) or give an instruction directly.
  # /format command removed
  /help                       Show this help message.
  /exit or /quit              Exit the application.""")
        elif command in ["/exit", "/quit"]:
            return False # Signal to exit main loop
        else:
            self._print("error", f"Unknown command: {command}. Try /help.")

        # Return True to indicate command was handled (or unknown but processed)
        # This prevents the command itself from being treated as user input by run_one
        return True

    # --- Input Preprocessing ---

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

             # Only try to apply edits if in code mode
             if self.mode == "code":
                 edits = self._parse_edits(response)
                 if edits:
                     if self._apply_edits(edits):
                           # Optional: Auto-commit after successful edits
                           # self._git_add_commit()
                           pass
                     else:
                          self._print("info", "Some edits failed to apply.")
                 else:
                     # Check if the LLM just output code without the edit block format
                     code_block_match = re.search(r"```(?:\w*\n)?(.*?)```", response, re.DOTALL)
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
                    # Keep track of mode before command potentially changes it
                    mode_before_cmd = self.mode
                    if not self._handle_command(inp):
                        break # Exit command was received
                    # If the command itself didn't process input (like /add, /drop, /help, /files, /format)
                    # continue to the next loop iteration without sending anything to LLM.
                    # Commands like /ask or /code with arguments will trigger processing via process_user_input(is_command_context=True).
                    # Mode switching commands like bare /ask, /code don't need LLM processing either.
                    # Exit/quit already handled. Commit/undo have their own logic. Reset/clear modify state.
                    command_processed_input = inp.startswith(("/ask ", "/code ")) and len(inp.split()) > 1
                    if not command_processed_input and self.mode == mode_before_cmd: # Check if mode actually changed
                         continue
                    # If a command like /ask or /code *without* args was used, just continue
                    elif not command_processed_input and self.mode != mode_before_cmd:
                         continue

                else: # Regular user message (not a command)
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
