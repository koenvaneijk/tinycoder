from tinycoder.utils import print_color

import subprocess

from typing import List, Dict, Optional, Tuple

# --- Git Interaction Class ---
class GitManager:
    """Handles all interactions with the git repository."""
    def __init__(self, io_print_error):
        self.io_print_error = io_print_error
        # Initialize git_root to None first
        self.git_root: Optional[str] = None
        # Now find the root, which might call _run_git_command
        self.git_root = self._find_git_root()

    def _run_git_command(self, args: List[str], cwd: Optional[str] = None) -> Tuple[int, str, str]:
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
                check=False, # Don't raise exception on non-zero exit
                encoding='utf-8',
                errors='replace'
            )
            return process.returncode, process.stdout, process.stderr
        except FileNotFoundError:
            self.io_print_error("Error: 'git' command not found. Is Git installed and in your PATH?")
            return -1, "", "Git command not found"
        except Exception as e:
            self.io_print_error(f"Error running git command {' '.join(args)}: {e}")
            return -1, "", str(e)

    def _find_git_root(self) -> Optional[str]:
        """Find the root directory of the git repository."""
        # Run without cwd initially to find the root
        exit_code, stdout, stderr = self._run_git_command(["rev-parse", "--show-toplevel"], cwd=None)
        if exit_code == 0:
            return stdout.strip()
        return None

    def is_repo(self) -> bool:
        """Check if the current directory is inside a git repository."""
        return self.git_root is not None

    def get_root(self) -> Optional[str]:
        """Return the cached git root directory."""
        return self.git_root

    def get_last_commit_hash(self) -> Optional[str]:
        """Get the short hash of the last commit."""
        if not self.is_repo(): return None
        ret, stdout, stderr = self._run_git_command(["rev-parse", "--short", "HEAD"])
        if ret == 0:
            return stdout.strip()
        else:
            self.io_print_error(f"Failed to get last commit hash: {stderr}")
            return None

    def get_files_changed_in_commit(self, commit_hash: str) -> List[str]:
        """Gets relative paths of files changed in a specific commit."""
        if not self.is_repo(): return []
        ret, stdout, stderr = self._run_git_command(["show", "--pretty=", "--name-only", commit_hash])
        if ret == 0:
            # Ensure paths are relative to the git root
            return [f.strip() for f in stdout.splitlines() if f.strip()]
        else:
            self.io_print_error(f"Failed to get files for commit {commit_hash}: {stderr}")
            return []

    def commit_files(self, files_abs: List[str], files_rel: List[str], message: str) -> Optional[str]:
        """Stages and commits specified files. Returns commit hash on success."""
        if not self.is_repo():
            self.io_print_error("Not in a git repository, cannot commit.")
            return None
        if not files_abs:
            self.io_print_error("No files provided to commit.")
            return None

        # Check status of the specific files we might commit
        ret, stdout, stderr = self._run_git_command(["status", "--porcelain", "--"] + files_abs)
        if ret != 0:
            self.io_print_error(f"Git status check failed for files: {stderr}")
            return None
        if not stdout.strip():
             print_color("No changes detected in files to commit.", "info") # Use print_color directly here
             return None

        # Stage the files
        ret, _, stderr = self._run_git_command(["add", "--"] + files_abs)
        if ret != 0:
            self.io_print_error(f"Failed to git add files: {stderr}")
            return None
        print_color(f"Staged changes for: {', '.join(sorted(files_rel))}", "info")

        # Commit
        ret, stdout_commit, stderr_commit = self._run_git_command(["commit", "-m", message])
        if ret != 0:
            if "nothing to commit" in stderr_commit or "no changes added to commit" in stdout_commit:
                print_color("No changes staged to commit.", "info")
                return None
            else:
                self.io_print_error(f"Git commit failed:\nstdout: {stdout_commit}\nstderr: {stderr_commit}")
                return None

        # Get the commit hash
        commit_hash = self.get_last_commit_hash()
        if commit_hash:
            print_color(f"Committed changes as {commit_hash}", "info")
            return commit_hash
        else:
             # Error getting hash already printed by get_last_commit_hash
             return None

    def undo_last_commit(self, expected_hash: str) -> bool:
        """Undo the last commit if it matches the expected hash."""
        if not self.is_repo():
            self.io_print_error("Not in a git repository.")
            return False

        last_hash = self.get_last_commit_hash()
        if not last_hash:
            # Error already printed by get_last_commit_hash
            return False

        if last_hash != expected_hash:
            self.io_print_error(f"Last commit hash {last_hash} does not match expected {expected_hash}.")
            # Consider adding info about manual reset here if desired
            return False

        # Get relative paths of files changed in the commit
        relative_files_to_revert = self.get_files_changed_in_commit(last_hash)
        if not relative_files_to_revert:
             print_color(f"Could not determine files changed in commit {last_hash}. Attempting reset without checkout.", "warning")
             # Proceed with soft reset only

        # Soft reset first - moves HEAD back but keeps changes staged
        ret, _, stderr = self._run_git_command(["reset", "--soft", "HEAD~1"])
        if ret != 0:
            self.io_print_error(f"Git soft reset failed: {stderr}")
            return False

        # If we know which files were changed, check them out from the previous state
        if relative_files_to_revert:
            # Use relative paths for checkout command within the repo root
            ret, _, stderr = self._run_git_command(["checkout", "HEAD~1", "--"] + relative_files_to_revert)
            if ret != 0:
                 self.io_print_error(f"Git checkout failed for reverting files: {stderr}")
                 print_color("Undo failed after soft reset. Repository state might be inconsistent. Files remain staged.", "warning")
                 return False # Indicate failure even though soft reset worked
            else:
                 new_hash = self.get_last_commit_hash()
                 print_color(f"Successfully undid commit {last_hash}. Content reverted. Current HEAD is now {new_hash}.", "info")
                 return True # Success
        else:
             # Files to revert unknown, soft reset done, inform user
             new_hash = self.get_last_commit_hash()
             print_color(f"Successfully reset HEAD past commit {last_hash}. Files remain staged. Current HEAD is now {new_hash}.", "info")
             return True # Indicate success (soft reset worked)

