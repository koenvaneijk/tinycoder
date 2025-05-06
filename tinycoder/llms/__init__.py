import os # Needed for Ollama error message

from .base import LLMClient
from .gemini import GeminiClient, DEFAULT_GEMINI_MODEL
from .deepseek import DeepSeekClient
from .ollama import OllamaClient, DEFAULT_OLLAMA_MODEL, DEFAULT_OLLAMA_HOST # Import OllamaClient and its defaults
from .anthropic import AnthropicClient # Import AnthropicClient
from .together_ai import TogetherAIClient, DEFAULT_TOGETHER_MODEL # Import TogetherAIClient

from typing import Optional

import logging

__all__ = [
    "LLMClient",
    "GeminiClient",
    "DeepSeekClient",
    "OllamaClient", # Add OllamaClient to __all__
    "AnthropicClient", # Add AnthropicClient to __all__
    "TogetherAIClient", # Add TogetherAIClient to __all__
]

logger = logging.getLogger(__name__)

def create_llm_client(model: Optional[str]) -> LLMClient:
    """
    Selects and instantiates the appropriate LLMClient based on the model name.

    Args:
        model: The requested model name string (e.g., "gemini-...", "deepseek-...").
               If None, uses the default Gemini model.

    Returns:
        An instance of a class derived from LLMClient.

    Raises:
        ValueError: If client initialization fails for the specified or assumed model.
    """
    client: LLMClient
    resolved_model_name: Optional[str] = model # Keep track of the name used

    if model and model.startswith("deepseek-"):
        logger.debug(f"Attempting to initialize DeepSeek client with model: {model}")
        try:
            client = DeepSeekClient(model=model)
            resolved_model_name = client.model # Get potentially updated model name
        except Exception as e:
            raise ValueError(f"Error initializing DeepSeek client for model '{model}': {e}") from e
    elif model and model.startswith("gemini-"):
        logger.debug(f"Attempting to initialize Gemini client with model: {model}")
        try:
            client = GeminiClient(model=model)
            resolved_model_name = client.model
        except Exception as e:
            raise ValueError(f"Error initializing Gemini client for model '{model}': {e}") from e
    elif not model:
        resolved_model_name = DEFAULT_GEMINI_MODEL
        logger.debug(f"No model specified, defaulting to Gemini ({resolved_model_name}).")
        try:
            client = GeminiClient(model=resolved_model_name)
            # Model name is already resolved
        except Exception as e:
            # Error initializing even the default model is critical
             raise ValueError(f"Error initializing default Gemini client ({resolved_model_name}): {e}") from e
    elif model and model.startswith("claude-"):
        logger.debug(f"Attempting to initialize Anthropic client with model: {model}")
        try:
            client = AnthropicClient(model=model)
            resolved_model_name = client.model
        except Exception as e:
            raise ValueError(f"Error initializing Anthropic client for model '{model}': {e}") from e
    elif model and model.startswith("together-"):
        logger.debug(f"Attempting to initialize Together.ai client with model: {model}")
        try:
            # Strip the "together-" prefix for the actual model name
            actual_model = model[len("together-"):]
            client = TogetherAIClient(model=actual_model)
            resolved_model_name = client.model
        except Exception as e:
            raise ValueError(f"Error initializing Together.ai client for model '{model}': {e}") from e
    else:
        # Assume Ollama for unknown/missing prefixes if not recognized
        logger.info(f"Unknown or missing prefix for model '{model}'. Assuming local Ollama model.")
        resolved_model_name = model # Use the provided name for Ollama, or None if None was passed
        try:
            # Pass the provided model name (which might be None, causing OllamaClient to use its default)
            client = OllamaClient(model=resolved_model_name)
            resolved_model_name = client.model # Get actual model name used by OllamaClient
        except Exception as e:
            # Include OLLAMA_HOST in error message if connection failed
            ollama_host_info = f" (checked OLLAMA_HOST: {os.environ.get('OLLAMA_HOST', DEFAULT_OLLAMA_HOST)})"
            raise ValueError(f"Error initializing Ollama client for model '{model}'{ollama_host_info}: {e}") from e

    return client