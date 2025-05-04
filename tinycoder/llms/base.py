from abc import ABC, abstractmethod
from typing import List, Dict, Optional, Tuple

class LLMClient(ABC):
    """Abstract Base Class for LLM API clients."""

    def __init__(self, model: Optional[str] = None, api_key: Optional[str] = None):
        """
        Initializes the client. Subclasses handle specific API key logic
        and model defaults.
        """
        self._model = model  # Store the requested model name
        self._api_key = api_key  # Store the API key if provided directly

    @property
    def model(self) -> Optional[str]:
        """Returns the specific model name being used by the client."""
        return self._model

    @abstractmethod
    def generate_content(
        self, system_prompt: str, history: List[Dict[str, str]]
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Generates content based on a system prompt and chat history.

        Args:
            system_prompt: The system instruction text.
            history: The chat history list (excluding system prompt).

        Returns:
            A tuple containing (response_text, error_message).
            response_text is None if an error occurs.
            error_message is None if the request is successful.
        """
        pass

