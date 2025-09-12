import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from tinycoder.git_manager import GitManager


class TestGitManagerRootDetection(unittest.TestCase):
    def setUp(self):
        self._orig_cwd = os.getcwd()
        self._tmp = TemporaryDirectory()

    def tearDown(self):
        try:
            os.chdir(self._orig_cwd)
        finally:
            self._tmp.cleanup()

    def test_find_git_root_in_parent_directory(self):
        base = Path(self._tmp.name)
        repo = base / "repo"
        nested = repo / "sub" / "dir"

        # Create a fake git repo structure
        (repo / ".git").mkdir(parents=True)
        nested.mkdir(parents=True)

        os.chdir(nested)

        with patch.object(GitManager, "_check_git_availability", return_value=True), \
             patch.object(GitManager, "_check_and_configure_git_user", return_value=None):
            gm = GitManager()
            self.assertEqual(gm.git_root, str(repo))
            self.assertTrue(gm.is_repo())

    def test_find_git_root_returns_none_when_absent(self):
        base = Path(self._tmp.name)
        nested = base / "proj" / "a" / "b"
        nested.mkdir(parents=True)
        os.chdir(nested)

        with patch.object(GitManager, "_check_git_availability", return_value=True), \
             patch.object(GitManager, "_check_and_configure_git_user", return_value=None):
            gm = GitManager()
            self.assertIsNone(gm.git_root)
            self.assertFalse(gm.is_repo())


if __name__ == "__main__":
    unittest.main()