"""Unit tests for the PromptBuilder class in tinycoder/prompt_builder.py."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from tinycoder.prompt_builder import PromptBuilder
from tinycoder.file_manager import FileManager
from tinycoder.repo_map import RepoMap


class TestPromptBuilder(unittest.TestCase):
    """Test cases for PromptBuilder functionality."""

    def setUp(self):
        """Set up a temporary directory and mock dependencies for each test."""
        self.temp_dir = tempfile.mkdtemp()
        self.addCleanup(lambda: self._cleanup_temp_dir())
        self.file_manager = FileManager(root=self.temp_dir, io_input=lambda prompt: "")
        self.repo_map = RepoMap(root=self.temp_dir)
        self.builder = PromptBuilder(file_manager=self.file_manager, repo_map=self.repo_map)

    def _cleanup_temp_dir(self):
        """Clean up the temporary directory."""
        for root, dirs, files in os.walk(self.temp_dir, topdown=False):
            for name in files:
                os.remove(os.path.join(root, name))
            for name in dirs:
                os.rmdir(os.path.join(root, name))
        os.rmdir(self.temp_dir)

    def test_build_system_prompt_no_files_no_map(self):
        """Test system prompt with no files and no repo map."""
        prompt = self.builder.build_system_prompt(mode="code", custom_rules_content="", include_map=False)
        self.assertIn("(No files added to chat yet)", prompt)
        self.assertIn("(Repository map generation is disabled by user)", prompt)
        self.assertIn("Act as an expert software developer", prompt)

    def test_build_system_prompt_with_files_no_map(self):
        """Test system prompt with files but no repo map."""
        # Create a dummy file
        dummy_path = Path(self.temp_dir) / "dummy.py"
        dummy_path.write_text("# dummy file")
        self.file_manager.add_file(str(dummy_path))

        prompt = self.builder.build_system_prompt(mode="code", custom_rules_content="", include_map=False)
        self.assertIn("- `dummy.py`", prompt)
        self.assertIn("(Repository map generation is disabled by user)", prompt)

    def test_build_system_prompt_ask_mode(self):
        """Test system prompt in ask mode."""
        prompt = self.builder.build_system_prompt(mode="ask", custom_rules_content="", include_map=False)
        self.assertIn("(No files added to chat yet)", prompt)
        # Ask mode should not include DIFF_PROMPT
        self.assertNotIn("When modifying code, always use the diff format", prompt)

    def test_build_system_prompt_with_custom_rules(self):
        """Test system prompt with custom rules in code mode."""
        rules = "Always use snake_case for functions."
        prompt = self.builder.build_system_prompt(mode="code", custom_rules_content=rules, include_map=False)
        self.assertIn("## Custom Rules", prompt)
        self.assertIn(rules, prompt)

    def test_build_system_prompt_with_map_enabled(self):
        """Test system prompt with repo map enabled."""
        # Create a Python file to trigger map generation
        py_file = Path(self.temp_dir) / "module.py"
        py_file.write_text("def foo():\n    pass\n")
        prompt = self.builder.build_system_prompt(mode="code", custom_rules_content="", include_map=True)
        # Map should be generated (non-empty or placeholder)
        self.assertNotIn("(Repository map generation is disabled by user)", prompt)

    def test_build_identify_files_prompt_no_map(self):
        """Test identify files prompt with map disabled."""
        prompt = self.builder.build_identify_files_prompt(include_map=False)
        self.assertIn("(Repository map generation is disabled by user)", prompt)

    def test_build_identify_files_prompt_with_map(self):
        """Test identify files prompt with map enabled."""
        # Create a Python file to trigger map generation
        py_file = Path(self.temp_dir) / "module.py"
        py_file.write_text("def foo():\n    pass\n")
        prompt = self.builder.build_identify_files_prompt(include_map=True)
        self.assertNotIn("(Repository map generation is disabled by user)", prompt)

    def test_get_file_content_message_no_files(self):
        """Test file content message when no files are present."""
        msg = self.builder.get_file_content_message()
        self.assertIsNone(msg)

    def test_get_file_content_message_with_files(self):
        """Test file content message when files are present."""
        # Create and add a file
        test_file = Path(self.temp_dir) / "test.txt"
        test_file.write_text("Hello, world!")
        self.file_manager.add_file(str(test_file))

        msg = self.builder.get_file_content_message()
        self.assertIsNotNone(msg)
        self.assertEqual(msg["role"], "user")
        self.assertIn("Hello, world!", msg["content"])

    def test_repo_map_root_fallback(self):
        """Test that repo map root is set correctly when file manager has no root."""
        fm = FileManager(root=None, io_input=lambda prompt: "")
        builder = PromptBuilder(file_manager=fm, repo_map=self.repo_map)
        # Trigger a method that sets repo map root
        builder.build_system_prompt(mode="code", custom_rules_content="", include_map=False)
        self.assertEqual(self.repo_map.root, Path.cwd())


if __name__ == "__main__":
    unittest.main()