import os
import sys
import json
from typing import List, Dict, Optional, Tuple, Any, Generator

import tinycoder.requests as requests
from tinycoder.llms.base import LLMClient

# Default model on Groq
DEFAULT_GROQ_MODEL = "moonshotai/kimi-k2-instruct-0905"
GROQ_API_ENDPOINT = "https://api.groq.com/openai/v1/chat/completions"
GROQ_API_KEY_ENV_VAR = "GROQ_API_KEY"


class GroqClient(LLMClient):
    """
    Client for interacting with the Groq Cloud API.
    """

    def __init__(self, model: Optional[str] = None, api_key: Optional[str] = None):
        """
        Initializes the Groq client.

        Args:
            model: The specific Groq model to use.
                   Defaults to DEFAULT_GROQ_MODEL if not provided.
            api_key: The Groq API key. If not provided, attempts to read from
                     the GROQ_API_KEY environment variable.
        """
        resolved_api_key = api_key or os.environ.get(GROQ_API_KEY_ENV_VAR)
        if not resolved_api_key:
            print(
                f"Error: {GROQ_API_KEY_ENV_VAR} environment variable not set.",
                file=sys.stderr,
            )
            sys.exit(1)

        resolved_model = model or DEFAULT_GROQ_MODEL
        # Remove 'groq-' prefix if present from model factory
        if resolved_model and resolved_model.startswith("groq-"):
            resolved_model = resolved_model[5:]  # Remove 'groq-' prefix
            
        super().__init__(model=resolved_model, api_key=resolved_api_key)

        self.api_url = GROQ_API_ENDPOINT
        self.headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            "User-Agent": "tinycoder/1.0",
        }

    def _format_history(self, system_prompt: str, history: List[Dict[str, str]]) -> List[Dict[str, Any]]:
        """
        Formats chat history for the Groq API's 'messages' field.
        Places system prompt at the beginning if provided.
        """
        groq_messages = []
        
        # Add system prompt at the beginning if it exists
        if system_prompt:
            groq_messages.append({"role": "system", "content": system_prompt})
            
        # Add the rest of the history
        for message in history:
            role = message.get("role")
            content = message.get("content", "")
            
            # Groq uses standard OpenAI-compatible roles: 'system', 'user', 'assistant'
            if role in ["system", "user", "assistant"]:
                groq_messages.append({"role": role, "content": content})
            else:
                # Skip other non-standard roles
                print(f"Warning: Skipping message with unhandled role '{role}' for Groq.", file=sys.stderr)
                
        return groq_messages

    def generate_content(
        self, system_prompt: str, history: List[Dict[str, str]]
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Sends the prompt and history to the Groq API.

        Args:
            system_prompt: The system instruction text.
            history: The chat history list (excluding system prompt).

        Returns:
            A tuple containing (response_text, error_message).
            response_text is None if an error occurs.
            error_message is None if the request is successful.
        """
        formatted_messages = self._format_history(system_prompt, history)

        if not formatted_messages:
            return None, "Cannot send request to Groq with empty messages."
        
        if not any(msg['role'] == 'user' for msg in formatted_messages):
            return None, "Groq API requires at least one user message."

        payload = {
            "model": self.model,
            "messages": formatted_messages,
        }

        try:
            response = requests.post(
                self.api_url, headers=self.headers, json=payload, timeout=180
            )
            response.raise_for_status()

            response_data = response.json()

            if "choices" in response_data and response_data["choices"] and "message" in response_data["choices"][0]:
                first_choice = response_data["choices"][0]
                message = first_choice.get("message", {})
                
                if "content" in message:
                    response_text = message["content"]
                    finish_reason = first_choice.get("finish_reason")
                    if finish_reason == "length":
                        print("Warning: Groq response truncated due to max_tokens limit.", file=sys.stderr)
                    
                    return response_text, None
                else:
                    return None, f"Groq API Error: Response message missing 'content': {message}"
            else:
                return None, f"Groq API Error: Unexpected response structure: {response_data}"

        except requests.Timeout:
            return None, f"Groq API request timed out after 180 seconds."
        except requests.HTTPError as e:
            error_msg = f"Groq API HTTP Error: {e.response.status_code} {e.response.reason} for URL {self.api_url}"
            try:
                error_details = e.response.json()
                if "error" in error_details:
                    error_info = error_details["error"]
                    if isinstance(error_info, dict):
                        error_msg += f"\nDetails: {error_info.get('message', str(error_info))}"
                    else:
                        error_msg += f"\nDetails: {error_info}"
                else:
                    error_msg += f"\nResponse Body: {json.dumps(error_details)}"
            except json.JSONDecodeError:
                error_msg += f"\nResponse Body (non-JSON): {e.response.text}"
            except Exception:
                error_msg += "\n(Could not parse error details from response body)"
            return None, error_msg
        except requests.RequestException as e:
            return None, f"Groq API Request Error: {e}"
        except json.JSONDecodeError as e:
            return None, f"Failed to decode JSON response from Groq: {e}\nResponse text: {response.text}"
        except Exception as e:
            return None, f"An unexpected error occurred during Groq API call: {type(e).__name__} - {e}"

    def generate_content_stream(self, system_prompt: str, history: List[Dict[str, str]]) -> Generator[str, None, None]:
        """
        Streams content from the Groq API (OpenAI-compatible), yielding chunks as they arrive.
        On error, yields a single 'STREAMING_ERROR: ...' message.
        """
        formatted_messages = self._format_history(system_prompt, history)

        if not formatted_messages:
            yield "STREAMING_ERROR: Cannot send request to Groq with empty messages."
            return
        
        if not any(msg['role'] == 'user' for msg in formatted_messages):
            yield "STREAMING_ERROR: Groq API requires at least one user message."
            return

        payload = {
            "model": self.model,
            "messages": formatted_messages,
            "stream": True,
        }

        try:
            response = requests.post(
                self.api_url, headers=self.headers, json=payload, stream=True, timeout=180
            )
            response.raise_for_status()

            for raw_line in response.iter_lines():
                if not raw_line:
                    continue
                try:
                    line = raw_line.decode("utf-8")
                except Exception:
                    continue

                if not line.strip():
                    continue

                data_str = line[6:] if line.startswith("data: ") else line
                if data_str.strip() == "[DONE]":
                    break

                try:
                    data = json.loads(data_str)
                except json.JSONDecodeError:
                    continue

                choices = data.get("choices")
                if choices and len(choices) > 0:
                    delta = choices[0].get("delta", {})
                    content = delta.get("content")
                    if content:
                        yield content

            try:
                response.close()
            except Exception:
                pass

        except requests.RequestException as e:
            yield f"STREAMING_ERROR: Groq streaming request failed: {e}"
        except Exception as e:
            yield f"STREAMING_ERROR: Unexpected error during Groq streaming: {e}"