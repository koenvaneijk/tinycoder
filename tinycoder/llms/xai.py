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

    def _default_headers(self, stream: bool = False) -> Dict[str, str]:
        """
        Headers that avoid Cloudflare/WAF issues and compression the shim can't handle.
        """
        accept = "text/event-stream" if stream else "application/json"
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "Accept": accept,
            "Accept-Encoding": "identity",
            "User-Agent": "curl/8.5.0",
        }

    def generate_content(self, system_prompt: str, history: List[Dict[str, str]]):
        """
        Non-streaming generation. Returns (content, error_message).
        """
        url = f"{self._base_url}/chat/completions"
        headers = self._default_headers(stream=False)
        payload = {
            "model": self._model,
            "messages": self._format_history(system_prompt, history),
            "stream": False,
        }
        try:
            resp = self._session.post(url, json=payload, headers=headers, timeout=60)
            status = getattr(resp, "status_code", 0)
            ctype = (resp.headers.get("Content-Type") or "").lower()
            # If status is not OK or content is not JSON, surface a helpful error
            if status >= 400 or "application/json" not in ctype:
                # Try to extract message from JSON if possible
                message = None
                try:
                    data_err = resp.json()
                    if isinstance(data_err, dict):
                        message = (data_err.get("error") or {}).get("message") or data_err.get("message")
                except Exception:
                    message = None
                if not message:
                    body_head = ((resp.text or "")[:200]).replace("\n", "\\n")
                    message = f"HTTP {status or 'error'}; Content-Type: {ctype or 'unknown'}; body head: {body_head}"
                return None, message

            # Parse JSON safely
            try:
                data = resp.json()
            except Exception as e:
                body_head = ((resp.text or "")[:200]).replace("\n", "\\n")
                return None, f"Failed to parse JSON (HTTP {status}): {e}; body head: {body_head}"

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
        headers = self._default_headers(stream=True)
        payload = {
            "model": self._model,
            "messages": self._format_history(system_prompt, history),
            "stream": True,
        }
        try:
            resp = self._session.post(url, json=payload, headers=headers, timeout=300, stream=True)
            status = getattr(resp, "status_code", 0)
            ctype = (resp.headers.get("Content-Type") or "").lower()
            if status >= 400 or "text/event-stream" not in ctype:
                # Consume body to produce a helpful message
                body_head = ((resp.text or "")[:200]).replace("\n", "\\n")
                yield f"STREAMING_ERROR: HTTP {status or 'error'}; Content-Type: {ctype or 'unknown'}; body head: {body_head}"
                return

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