import os
import json
from typing import List, Dict, Optional, Generator

from tinycoder.llms.base import LLMClient
from tinycoder.requests import Session, RequestException, HTTPError, Timeout


DEFAULT_XAI_MODEL = "grok-code-fast-1"
DEFAULT_XAI_BASE_URL = "https://api.x.ai/v1"


class XAIClient(LLMClient):
    """
    Client for interacting with the X.ai (Grok) API using an OpenAI-compatible Chat Completions interface.
    """

    def __init__(self, model: Optional[str] = None, api_key: Optional[str] = None):
        self._model = model or DEFAULT_XAI_MODEL
        self._api_key = api_key or os.environ.get("XAI_API_KEY")
        if not self._api_key:
            raise ValueError("XAI_API_KEY environment variable not set.")
        self._base_url = os.environ.get("XAI_BASE_URL", DEFAULT_XAI_BASE_URL).rstrip("/")
        self._session = Session()

    @property
    def model(self) -> str:
        return self._model

    def _format_history(self, system_prompt: str, history: List[Dict[str, str]]) -> List[Dict[str, str]]:
        messages: List[Dict[str, str]] = []
        if system_prompt:
            messages.append({"role": "system", "content": system_prompt})
        for m in history:
            role = m.get("role")
            content = m.get("content", "")
            if not content:
                continue
            if role not in ("user", "assistant", "system"):
                role = "user"
            messages.append({"role": role, "content": content})
        return messages

    def generate_content(self, system_prompt: str, history: List[Dict[str, str]]):
        """
        Non-streaming generation. Returns (content, error_message).
        """
        url = f"{self._base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self._model,
            "messages": self._format_history(system_prompt, history),
            "stream": False,
        }
        try:
            resp = self._session.post(url, json=payload, headers=headers, timeout=60)
            data = resp.json()
            # Surface errors if present
            if getattr(resp, "status_code", 200) >= 400:
                message = None
                if isinstance(data, dict):
                    message = (data.get("error") or {}).get("message") or data.get("message")
                return None, message or f"HTTP {getattr(resp, 'status_code', 'error')}"
            # Extract content in OpenAI-compatible schema
            content = ""
            try:
                content = (data.get("choices") or [{}])[0].get("message", {}).get("content", "")  # type: ignore
            except Exception:
                content = ""
            return content, None
        except (RequestException, HTTPError, Timeout) as e:
            return None, str(e)
        except Exception as e:
            return None, f"Unexpected error: {e}"

    def generate_content_stream(self, system_prompt: str, history: List[Dict[str, str]]):
        """
        Streaming generation. Yields text chunks as they arrive.
        """
        url = f"{self._base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self._model,
            "messages": self._format_history(system_prompt, history),
            "stream": True,
        }
        try:
            resp = self._session.post(url, json=payload, headers=headers, timeout=300, stream=True)
            for line in resp.iter_lines(chunk_size=512, decode_unicode=True):
                if not line:
                    continue
                if isinstance(line, (bytes, bytearray)):
                    try:
                        line = line.decode("utf-8", errors="ignore")
                    except Exception:
                        continue
                line = line.strip()
                if not line:
                    continue
                # Expect lines like: "data: { ... }"
                if line.startswith("data: "):
                    data_str = line[6:].strip()
                    if data_str == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data_str)
                    except Exception:
                        continue
                    choices = chunk.get("choices") or []
                    if not choices:
                        continue
                    delta = (choices[0] or {}).get("delta", {})
                    text = delta.get("content") or ""
                    if text:
                        yield text
        except (RequestException, HTTPError, Timeout):
            return
        except Exception:
            return