import os
from typing import Dict, Iterable, List, Optional, Tuple

from .base import LLMClient


class ZenLLMClient(LLMClient):
    """
    TinyCoder LLMClient adapter backed by zenllm.
    - Uses zenllm.chat for both non-streaming and streaming modes.
    - Yields only text chunks for streaming (TinyCoder UI is text-only).
    - Exposes last usage via get_last_usage() if available from zenllm.
    """

    def __init__(
        self,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
        provider: Optional[str] = None,
        base_url: Optional[str] = None,
    ):
        super().__init__(model=model, api_key=api_key)
        # Lazy import so zenllm is an optional dependency until this client is used
        try:
            import zenllm as llm  # type: ignore
        except Exception as e:
            raise ImportError(
                "zenllm is not installed. Please install it with: pip install zenllm"
            ) from e
        self._llm = llm

        # If no model provided, prefer environment default used by zenllm
        if self._model is None:
            env_default = os.getenv("ZENLLM_DEFAULT_MODEL")
            if env_default:
                self._model = env_default

        self._provider = provider  # e.g. "openai-compatible", "gemini", "claude", etc.
        self._base_url = base_url  # for OpenAI-compatible/local endpoints
        self._last_usage = None  # type: Optional[Dict]

    def _to_zen_messages(self, history: List[Dict[str, str]]) -> List[Tuple[str, str]]:
        """
        Convert TinyCoder's [{"role": "...", "content": "..."}] into
        zenllm chat shorthands: [("user", text), ("assistant", text), ...]
        """
        msgs: List[Tuple[str, str]] = []
        for msg in history:
            role = msg.get("role")
            text = msg.get("content", "") or ""
            if role in ("user", "assistant"):
                msgs.append((role, text))
            # Ignore other roles for now (e.g., system/tool), system is passed separately.
        return msgs

    def generate_content(
        self, system_prompt: str, history: List[Dict[str, str]]
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Non-streaming generation using zenllm.chat
        Returns (content, error_message)
        """
        try:
            msgs = self._to_zen_messages(history)
            resp = self._llm.chat(
                msgs,
                model=self._model,
                system=system_prompt or None,
                provider=self._provider,
                base_url=self._base_url,
                api_key=self._api_key,
            )
            # Save usage for token accounting if provided by zenllm
            self._last_usage = getattr(resp, "usage", None)

            # If zenllm knows the resolved model, prefer that
            try:
                raw = getattr(resp, "raw", None)
                if isinstance(raw, dict):
                    resolved_model = raw.get("model")
                    if resolved_model and isinstance(resolved_model, str):
                        self._model = resolved_model
            except Exception:
                pass

            return (resp.text or ""), None
        except Exception as e:
            return None, str(e)

    def generate_content_stream(
        self, system_prompt: str, history: List[Dict[str, str]]
    ) -> Iterable[str]:
        """
        Streaming generation using zenllm.chat(stream=True).
        Yields only text events. At the end, finalize to capture usage.
        """
        msgs = self._to_zen_messages(history)
        stream = self._llm.chat(
            msgs,
            model=self._model,
            system=system_prompt or None,
            provider=self._provider,
            base_url=self._base_url,
            api_key=self._api_key,
            stream=True,
        )
        try:
            for ev in stream:
                # zenllm streams typed events; we only surface text
                if getattr(ev, "type", None) == "text":
                    text = getattr(ev, "text", "")
                    if text:
                        yield text
            final = stream.finalize()
            # Save usage from the finalized response
            self._last_usage = getattr(final, "usage", None)

            # Update resolved model if available
            try:
                raw = getattr(final, "raw", None)
                if isinstance(raw, dict):
                    resolved_model = raw.get("model")
                    if resolved_model and isinstance(resolved_model, str):
                        self._model = resolved_model
            except Exception:
                pass
        except Exception:
            # Let the caller handle/log the streaming error
            raise

    def get_last_usage(self) -> Optional[Dict]:
        """
        Returns last usage payload if available, e.g.:
        {"input_tokens": int, "output_tokens": int}
        Fallback field names like {"prompt_tokens", "completion_tokens"} may occur.
        """
        return self._last_usage