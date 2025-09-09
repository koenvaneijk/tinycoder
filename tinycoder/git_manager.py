import logging
import subprocess
from typing import List, Optional, Tuple
from pathlib import Path # Added Path import
from tinycoder.ui.log_formatter import COLORS, RESET


class GitManager:
    """Handles all interactions with the git repository."""

    def __init__(self):
        self.logger = logging.getLogger(__name__)
        self.git_available: bool = self._check_git_availability()
        self.git_root: Optional[str] = None

        if self.git_available:
            # Only check for root if git command is available
            self.git_root = self._find_git_root()
            if self.git_root:
                # If we found a git root, check user config immediately
                self._check_and_configure_git_user()
            # If git_root is None here, it means git is available but no .git in CWD.
            # The prompting logic will be in App.__init__
            # Config check will happen in initialize_repo if user says yes.
        else:
            # Warning already logged by _check_git_availability
            pass # git_root remains None

    def _check_git_availability(self) -> bool:
        """Checks if the 'git' command is available."""
        try:
            # Use --version as a simple check
            process = subprocess.run(
                ["git", "--version"],
                capture_output=True,
                text=True,
                check=False,
                encoding="utf-8",
                errors="replace",
            )
            if process.returncode == 0:
                self.logger.debug(f"Git found: {COLORS['GREEN']}{process.stdout.strip()}{RESET}")
                return True
            else:
                self.logger.warning(
                    f"Git command check failed (exit code {COLORS['YELLOW']}{process.returncode}{RESET}). Git integration disabled."
                )
                self.logger.debug(f"Git check stderr: {COLORS['YELLOW']}{process.stderr.strip()}{RESET}")
                return False
        except FileNotFoundError:
            self.logger.warning(
                f"{COLORS['RED']}Error: 'git' command not found. Is Git installed and in your PATH? Git integration disabled.{RESET}"
            )
            return False
        except Exception as e:
            self.logger.error(f"Unexpected error checking git availability: {e}")
            return False

    def is_git_available(self) -> bool:
        """Returns whether the git command is available."""
        return self.git_available

    def _run_git_command(
        self, args: List[str], cwd: Optional[str] = None
    ) -> Tuple[int, str, str]:
        """Runs a git command and returns exit code, stdout, stderr."""
        # Prevent running if git is not available
        if not self.git_available:
             self.logger.debug("Git command skipped: Git is not available.")
             return -1, "", "Git command not found or available"

        # Determine effective CWD carefully
        effective_cwd = cwd
        """Runs a git command and returns exit code, stdout, stderr."""
        # Determine effective CWD carefully
        effective_cwd = cwd
        if effective_cwd is None and self.git_root is not None:
            # Only use self.git_root if it exists and cwd wasn't explicitly given
            effective_cwd = self.git_root
        # If cwd is None and self.git_root is None (during init), effective_cwd remains None,
        # which allows the initial 'git rev-parse --show-toplevel' to run from the current dir.
        try:
            process = subprocess.run(
                ["git"] + args,
                capture_output=True,
                text=True,
                cwd=effective_cwd,
                check=False,  # Don't raise exception on non-zero exit
                encoding="utf-8",
                errors="replace",
            )
            return process.returncode, process.stdout, process.stderr
        except FileNotFoundError:
            self.logger.error(
                f"{COLORS['RED']}Error: 'git' command not found. Is Git installed and in your PATH?{RESET}"
            )
            return -1, "", "Git command not found"
        except Exception as e:
            self.logger.error(f"{COLORS['RED']}Error running git command {COLORS['CYAN']}{' '.join(args)}{RESET}: {e}{RESET}")
            return -1, "", str(e)

    def _find_git_root(self) -> Optional[str]:
        """Check *only* the current working directory for a .git folder."""
        cwd = Path.cwd()
        git_dir = cwd / ".git"
        if git_dir.is_dir(): # Check if .git exists and is a directory
            self.logger.debug(f"Found .git directory at: {COLORS['GREEN']}{cwd}{RESET}")
            return str(cwd)
        else:
            self.logger.debug(f"No .git directory found in current directory: {cwd}")
            return None

    def initialize_repo(self) -> bool:
        """Initializes a git repository in the current working directory."""
        # Ensure git is available before attempting init
        if not self.git_available:
            self.logger.error(f"{COLORS['RED']}Cannot initialize repository: Git command is not available.{RESET}")
            return False

        cwd = Path.cwd()
        self.logger.info(f"Attempting to initialize Git repository in {COLORS['CYAN']}{cwd}{RESET}...")
        # Run 'git init' in the current working directory, explicitly set cwd
        exit_code, stdout, stderr = self._run_git_command(["init"], cwd=str(cwd))

        if exit_code == 0:
            self.logger.info(f"Successfully initialized Git repository in {COLORS['GREEN']}{cwd}{RESET}.")
            # Re-check and set the root after successful initialization
            self.git_root = self._find_git_root() # Should now find it
            if not self.git_root: # Defensive check, should not happen if init succeeded
                 self.logger.error(f"{COLORS['RED']}Git init succeeded but failed to confirm .git directory afterwards.{RESET}")
                 return False
            # Check config *after* successful initialization and root confirmation
            self._check_and_configure_git_user()
            return True
        else:
            self.logger.error(f"{COLORS['RED']}Failed to initialize Git repository: {stderr.strip()}{RESET}")
            self.git_root = None # Ensure root is None on failure
            return False

    def is_repo(self) -> bool:
        """Check if Git is available and the current directory is inside a git repository."""
        # A directory can only be a repo if git is available and we found a root
        return self.git_available and self.git_root is not None

    def get_root(self) -> Optional[str]:
        """Return the cached git root directory if Git is available."""
        # Only return a root if git is actually usable
        return self.git_root if self.git_available else None

    def _check_and_configure_git_user(self):
        """Checks for git user.name and user.email and prompts to set if missing."""
        if not self.git_root: # Should not happen if called correctly, but defensive
             self.logger.debug("Skipping git config check: No git root found.")
             return

        configs_to_check = {"user.name": "Your Name", "user.email": "your.email@example.com"}
        configs_to_set = {}

        for config_key, prompt_placeholder in configs_to_check.items():
            ret, stdout, stderr = self._run_git_command(["config", config_key])
            # Check if return code is non-zero (config not found) or if output is empty/whitespace
            if ret != 0 or not stdout.strip():
                self.logger.warning(f"Git configuration '{COLORS['YELLOW']}{config_key}{RESET}' is not set.")
                while True:
                    try:
                        # Prompt user for input using standard input
                        value = input(f"Please enter your git {COLORS['YELLOW']}{config_key}{RESET} (e.g., {prompt_placeholder}): ").strip()
                        if value:
                            configs_to_set[config_key] = value
                            break # Exit inner loop once valid input is received
                        else:
                            print(f"{COLORS['RED']}Input cannot be empty. Please try again.{RESET}")
                    except EOFError:
                         print(f"\n{COLORS['YELLOW']}Input stream closed. Cannot set git configuration.{RESET}")
                         return # Exit config check if input fails
                    except KeyboardInterrupt:
                         print(f"\n{COLORS['YELLOW']}Operation cancelled by user. Git configuration not set.{RESET}")
                         return # Exit config check if user cancels

        # Set the configurations globally if any were collected
        for config_key, value in configs_to_set.items():
            # Use --global to set it for the user across all repos
            ret_set, _, stderr_set = self._run_git_command(["config", "--global", config_key, value])
            if ret_set == 0:
                 self.logger.info(f"Successfully set global git config: {COLORS['GREEN']}{config_key}='{value}'{RESET}")
            else:
                 self.logger.error(f"{COLORS['RED']}Failed to set global git config {config_key}: {stderr_set}{RESET}")
                 # Continue trying to set others if needed, but log the error

    def get_tracked_files_relative(self) -> List[str]:
        """Gets a list of all files currently tracked by git, relative to the repo root."""
        if not self.is_repo():
            self.logger.debug("Cannot get tracked files: Not in a git repository or git unavailable.")
            return []

        # 'git ls-files' lists tracked files relative to the repo root
        ret, stdout, stderr = self._run_git_command(["ls-files"])

        if ret == 0:
            files = [line.strip() for line in stdout.splitlines() if line.strip()]
            self.logger.debug(f"Found {COLORS['GREEN']}{len(files)}{RESET} tracked files via 'git ls-files'.")
            return files
        else:
            self.logger.error(f"{COLORS['RED']}Failed to list tracked files using 'git ls-files': {stderr.strip()}{RESET}")
            return []

    def get_last_commit_hash(self) -> Optional[str]:
        """Get the short hash of the last commit."""
        if not self.is_repo():
            return None
        ret, stdout, stderr = self._run_git_command(["rev-parse", "--short", "HEAD"])
        if ret == 0:
            return stdout.strip()
        else:
            self.logger.error(f"{COLORS['RED']}Failed to get last commit hash: {stderr}{RESET}")
            return None

    def get_files_changed_in_commit(self, commit_hash: str) -> List[str]:
        """Gets relative paths of files changed in a specific commit."""
        if not self.is_repo():
            return []
        ret, stdout, stderr = self._run_git_command(
            ["show", "--pretty=", "--name-only", commit_hash]
        )
        if ret == 0:
            # Ensure paths are relative to the git root
            return [f.strip() for f in stdout.splitlines() if f.strip()]
        else:
            self.logger.error(
                f"{COLORS['RED']}Failed to get files for commit {COLORS['YELLOW']}{commit_hash}{RESET}: {stderr}{RESET}"
            )
            return []

    def commit_files(
        self, files_abs: List[str], files_rel: List[str], message: str
    ) -> Optional[str]:
        """Stages and commits specified files. Returns commit hash on success."""
        if not self.is_repo():
            self.logger.error(f"{COLORS['RED']}Not in a git repository, cannot commit.{RESET}")
            return None
        if not files_abs:
            self.logger.error(f"{COLORS['RED']}No files provided to commit.{RESET}")
            return None

        # Check status of the specific files we might commit
        ret, stdout, stderr = self._run_git_command(
            ["status", "--porcelain", "--"] + files_abs
        )
        if ret != 0:
            self.logger.error(f"{COLORS['RED']}Git status check failed for files: {stderr}{RESET}")
            return None
        if not stdout.strip():
            self.logger.info(
                "No changes detected in files to commit."
            )
            return None

        # Stage the files
        ret, _, stderr = self._run_git_command(["add", "--"] + files_abs)
        if ret != 0:
            self.logger.error(f"{COLORS['RED']}Failed to git add files: {stderr}{RESET}")
            return None
        self.logger.debug(f"GIT: Staged changes for: {COLORS['CYAN']}{', '.join(sorted(files_rel))}{RESET}")

        # Commit
        ret, stdout_commit, stderr_commit = self._run_git_command(
            ["commit", "-m", message]
        )
        if ret != 0:
            if (
                "nothing to commit" in stderr_commit
                or "no changes added to commit" in stdout_commit
            ):
                self.logger.info("No changes staged to commit.")
                return None
            else:
                self.logger.error(
                    f"{COLORS['RED']}Git commit failed:\nstdout: {stdout_commit}\nstderr: {stderr_commit}{RESET}"
                )
                return None

        # Get the commit hash
        commit_hash = self.get_last_commit_hash()
        if commit_hash:
            self.logger.info(f"📑 Commit: {COLORS['GREEN']}{commit_hash}{RESET}")
            return commit_hash
        else:
            # Error getting hash already printed by get_last_commit_hash
            return None

    def undo_last_commit(self, expected_hash: str) -> bool:
        """Undo the last commit if it matches the expected hash."""
        if not self.is_repo():
            self.logger.error(f"{COLORS['RED']}Not in a git repository.{RESET}")
            return False

        last_hash = self.get_last_commit_hash()
        if not last_hash:
            # Error already printed by get_last_commit_hash
            return False

        if last_hash != expected_hash:
            self.logger.error(
                f"{COLORS['RED']}Last commit hash {COLORS['YELLOW']}{last_hash}{RESET} does not match expected {COLORS['YELLOW']}{expected_hash}{RESET}.{RESET}"
            )
            # Consider adding info about manual reset here if desired
            return False

        # Get relative paths of files changed in the commit
        relative_files_to_revert = self.get_files_changed_in_commit(last_hash)
        if not relative_files_to_revert:
            self.logger.warning(
                f"{COLORS['YELLOW']}Could not determine files changed in commit {COLORS['YELLOW']}{last_hash}{RESET}. Attempting reset without checkout.{RESET}",
            )
            # Proceed with soft reset only

        # Soft reset first - moves HEAD back but keeps changes staged
        ret, _, stderr = self._run_git_command(["reset", "--soft", "HEAD~1"])
        if ret != 0:
            self.logger.error(f"{COLORS['RED']}Git soft reset failed: {stderr}{RESET}")
            return False

        # If we know which files were changed, check them out from the previous state
        if relative_files_to_revert:
            # Use relative paths for checkout command within the repo root
            ret, _, stderr = self._run_git_command(
                ["checkout", "HEAD~1", "--"] + relative_files_to_revert
            )
            if ret != 0:
                self.logger.error(
                    f"{COLORS['RED']}Git checkout failed for reverting files: {stderr}{RESET}"
                )
                self.logger.warning(
                    f"{COLORS['YELLOW']}Undo failed after soft reset. Repository state might be inconsistent. Files remain staged.{RESET}",
                )
                return False  # Indicate failure even though soft reset worked
            else:
                new_hash = self.get_last_commit_hash()
                self.logger.info(
                    f"Successfully undid commit {COLORS['YELLOW']}{last_hash}{RESET}. Content reverted. Current HEAD is now {COLORS['GREEN']}{new_hash}{RESET}.",
                )
                return True  # Success
        else:
            # Files to revert unknown, soft reset done, inform user
            new_hash = self.get_last_commit_hash()
            self.logger.info(
                f"Successfully reset HEAD past commit {COLORS['YELLOW']}{last_hash}{RESET}. Files remain staged. Current HEAD is now {COLORS['GREEN']}{new_hash}{RESET}.",
            )
            return True  # Indicate success (soft reset worked)
