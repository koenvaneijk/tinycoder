"""Context management for the TinyCoder application."""

import logging
from pathlib import Path
from typing import Dict, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from tinycoder.file_manager import FileManager
    from tinycoder.prompt_builder import PromptBuilder
    from tinycoder.repo_map import RepoMap
    from tinycoder.rule_manager import RuleManager
    from tinycoder.chat_history import ChatHistoryManager


class ContextManager:
    """Manages the application context including token calculations and caching."""
    
    def __init__(
        self,
        file_manager: 'FileManager',
        prompt_builder: 'PromptBuilder',
        repo_map: 'RepoMap',
        rule_manager: 'RuleManager',
        history_manager: 'ChatHistoryManager',
        logger: logging.Logger
    ):
        """Initialize the context manager with required dependencies."""
        self.file_manager = file_manager
        self.prompt_builder = prompt_builder
        self.repo_map = repo_map
        self.rule_manager = rule_manager
        self.history_manager = history_manager
        self.logger = logger
        
        # Token caching system
        self._cached_token_breakdown: Dict[str, int] = {}
        self._include_repo_map = True
    
    @property
    def include_repo_map(self) -> bool:
        """Get the current repository map inclusion state."""
        return self._include_repo_map
    
    def set_repo_map_state(self, state: bool) -> None:
        """Set the repository map inclusion state."""
        self._include_repo_map = state
    
    def update_token_cache(self) -> None:
        """Update the cached token breakdown by recalculating current context."""
        self._cached_token_breakdown = self._calculate_token_breakdown()
        self.logger.debug("Token context breakdown cache updated.")
    
    def get_cached_token_breakdown(self) -> Dict[str, int]:
        """Get the cached token breakdown."""
        return self._cached_token_breakdown.copy()
    
    def _calculate_token_breakdown(self) -> Dict[str, int]:
        """Calculate the approximate token count breakdown for the current context."""
        # Helper function to estimate tokens from characters
        def count_tokens(text: str) -> int:
            return int(len(text) / 4)

        # 1. System Prompt (Base + Rules)
        active_rules = self.rule_manager.get_active_rules_content()
        base_system_prompt_content = self.prompt_builder.build_system_prompt(
            "code",  # Default mode, can be parameterized if needed
            active_rules,
            include_map=False  # Exclude map for this part of calculation
        )
        system_prompt_tokens = count_tokens(base_system_prompt_content)

        # 2. Repository Map
        repo_map_tokens = 0
        if self._include_repo_map:
            chat_files_rel = self.file_manager.get_files()
            repo_map_str = self.repo_map.generate_map(chat_files_rel)
            repo_map_tokens = count_tokens(repo_map_str)

        # 3. File Context
        file_context_message = self.prompt_builder.get_file_content_message()
        file_context_content = file_context_message['content'] if file_context_message else ""
        file_context_tokens = count_tokens(file_context_content)

        # 4. History
        current_history = self.history_manager.get_history()
        history_content = "\n".join(msg['content'] for msg in current_history)
        history_tokens = count_tokens(history_content)

        total_tokens = system_prompt_tokens + repo_map_tokens + file_context_tokens + history_tokens

        return {
            "total": total_tokens,
            "prompt_rules": system_prompt_tokens,
            "repo_map": repo_map_tokens,
            "files": file_context_tokens,
            "history": history_tokens,
        }
    
    def get_current_repo_map_string(self) -> str:
        """Generate and return the current repository map string."""
        chat_files_rel = self.file_manager.get_files()  # Set[str] of relative paths
        
        # Ensure repo_map is initialized and has a root before generating
        if self.repo_map and self.repo_map.root:
            return self.repo_map.generate_map(chat_files_rel)
        else:
            self.logger.warning("RepoMap not fully initialized, cannot generate map string.")
            return "Repository map is not available at this moment."