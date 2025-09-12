import logging
import os
from typing import Optional

from .base import LLMClient

logger = logging.getLogger(__name__)

__all__ = [
    "LLMClient",
    "create_llm_client",
]


def create_llm_client(model: Optional[str]) -> LLMClient:
    """
    Instantiate a zenllm-backed client for all providers.
    - Provider is auto-detected by model prefix or can be overridden via env.
    - For OpenAI-compatible/local endpoints, set TINYCODER_LLM_BASE_URL.
    - Optionally set TINYCODER_LLM_PROVIDER to force a specific provider.
    """
    provider = os.getenv("TINYCODER_LLM_PROVIDER")  # e.g., "openai-compatible", "gemini", "claude", "deepseek", "together"
    base_url = os.getenv("TINYCODER_LLM_BASE_URL")  # e.g., "http://localhost:11434/v1" for OpenAI-compatible
    api_key = os.getenv("ZENLLM_API_KEY")  # Optional; zenllm also reads provider-specific env vars

    try:
        # Lazy import adapter to keep zenllm dependency optional until used
        from .zen_client import ZenLLMClient
        client: LLMClient = ZenLLMClient(model=model, api_key=api_key, provider=provider, base_url=base_url)
        logger.debug(f"Initialized ZenLLMClient (provider={provider or 'auto'}, base_url={base_url or 'default'})")
        return client
    except ImportError as e:
        raise ValueError(
            f"ZenLLM is required to use TinyCoder now. Please install it:\n"
            f"  pip install zenllm==0.2.1\n"
            f"Original error: {e}"
        ) from e
    except Exception as e:
        raise ValueError(f"Failed to initialize ZenLLM client: {e}") from e