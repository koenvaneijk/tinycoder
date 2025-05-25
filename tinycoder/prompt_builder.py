from pathlib import Path
from typing import Optional, Dict

from tinycoder.file_manager import FileManager
from tinycoder.repo_map import RepoMap
from tinycoder.prompts import (
    ASK_PROMPT,
    BASE_PROMPT,
    DIFF_PROMPT,
    IDENTIFY_FILES_PROMPT,
)


class PromptBuilder:
    """Handles the construction of prompts for the LLM."""

    def __init__(self, file_manager: FileManager, repo_map: RepoMap):
        """
        Initializes the PromptBuilder.

        Args:
            file_manager: The file manager instance to get file lists and content.
            repo_map: The repo map instance to generate repository structures.
        """
        self.file_manager = file_manager
        self.repo_map = repo_map

    def build_system_prompt(self, mode: str, custom_rules_content: str, include_map: bool) -> str:
        """
        Builds the main system prompt including file list, repo map, and custom rules.

        Args:
            mode: The current application mode ("code" or "ask").
            custom_rules_content: The content of loaded custom rules.
            include_map: Whether to include the repository map.

        Returns:
            The constructed system prompt string.
        """
        current_fnames = sorted(list(self.file_manager.get_files()))
        fnames_block = "\n".join(f"- `{fname}`" for fname in current_fnames)
        if not fnames_block:
            fnames_block = "(No files added to chat yet)"

        # Generate repo map for files *not* in chat
        # Ensure RepoMap uses the correct root from FileManager's perspective
        if self.file_manager.root:
            self.repo_map.root = Path(self.file_manager.root)
        else:
            # Fallback if FileManager has no root (e.g., not in git repo)
            self.repo_map.root = Path.cwd()

        # Conditionally generate repo map
        if include_map:
            repomap_block = self.repo_map.generate_map(self.file_manager.get_files())
        else:
            repomap_block = "(Repository map generation is disabled by user)"

        prompt_template = ASK_PROMPT if mode == "ask" else BASE_PROMPT
        base = prompt_template.format(
            fnames_block=fnames_block, repomap_block=repomap_block
        )

        if mode == "code":
            # Always use the standard diff prompt for code mode
            combined_prompt = base + DIFF_PROMPT
            if custom_rules_content:
                combined_prompt += "\n\n## Custom Rules\n\n" + custom_rules_content
            return combined_prompt
        else:  # ask mode
            # Ask mode does not use DIFF_PROMPT or custom rules directly in base.
            # If custom rules are needed for Ask, they should be part of ASK_PROMPT template.
            # If ASK_PROMPT (as modified by the user) now contains instructions for <request_files>,
            # this function correctly returns that as the system prompt for "ask" mode.
            return base

    def build_identify_files_prompt(self, include_map: bool) -> str:
        """
        Builds the prompt used to ask the LLM to identify relevant files.

        Args:
            include_map: Whether to include the repository map.

        Returns:
            The constructed prompt string.
        """
        # Ensure RepoMap uses the correct root
        if self.file_manager.root:
            self.repo_map.root = Path(self.file_manager.root)
        else:
            self.repo_map.root = Path.cwd()

        # Conditionally generate repo map
        if include_map:
            # Generate repo map of all files to help LLM identify existing files
            repomap_block = self.repo_map.generate_map(set()) # Pass empty set for full map
            map_section = "\n\nCurrent repository structure:\n" + repomap_block
        else:
            map_section = "\n\n(Repository map generation is disabled by user)"

        return IDENTIFY_FILES_PROMPT + map_section

    def get_file_content_message(self) -> Optional[Dict[str, str]]:
        """
        Creates the message dictionary containing the content of files in the context.

        Returns:
            A dictionary representing the user message with file content,
            or None if no files are in context.
        """
        # Check if there are any files in context using FileManager
        if self.file_manager.get_files():
            file_content_str = self.file_manager.get_content_for_llm()
            # Return the standard message format for the LLM
            return {"role": "user", "content": file_content_str}
        # Return None if no files are currently managed by FileManager
        return None
