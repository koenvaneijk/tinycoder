import os
import tinycoder.requests as requests
import json
import sys
from typing import List, Dict, Optional, Tuple, Any

from tinycoder.llms.base import LLMClient

# Default model - can be overridden by constructor or --model arg
DEFAULT_OLLAMA_MODEL = "qwen3:30b"
# Default host - can be overridden by OLLAMA_HOST env var
DEFAULT_OLLAMA_HOST = "http://localhost:11434"

class OllamaClient(LLMClient):
    """
    Client for interacting with a local Ollama API server.
    """

    def __init__(self, model: Optional[str] = None, api_key: Optional[str] = None):
        """
        Initializes the Ollama client.

        Args:
            model: The specific Ollama model to use (e.g., "llama3", "mistral").
                   Defaults to DEFAULT_OLLAMA_MODEL if not provided.
            api_key: Not used by Ollama, included for interface compatibility.
        """
        resolved_model = model or DEFAULT_OLLAMA_MODEL
        # Ollama doesn't use API keys for auth in the standard setup
        super().__init__(model=resolved_model, api_key=None)

        self.ollama_host = os.environ.get("OLLAMA_HOST", DEFAULT_OLLAMA_HOST).rstrip('/')
        self.api_url = f"{self.ollama_host}/api/chat"
        self._check_connection()

    def _check_connection(self) -> None:
        """Verify connection to the Ollama server."""
        try:
            # Simple check to see if the base URL is reachable
            response = requests.get(self.ollama_host, timeout=5)
            response.raise_for_status()
            # Optionally, check for specific Ollama response or endpoint like /api/tags
            # tags_response = requests.get(f"{self.ollama_host}/api/tags", timeout=5)
            # tags_response.raise_for_status()
            # print(f"Successfully connected to Ollama at {self.ollama_host}", file=sys.stderr)
        except requests.RequestException as e:
            print(
                f"Error: Could not connect to Ollama server at {self.ollama_host}.",
                file=sys.stderr,
            )
            print(f"Details: {e}", file=sys.stderr)
            print("Ensure Ollama is running and OLLAMA_HOST is set correctly if not using default.", file=sys.stderr)
            sys.exit(1)
        except Exception as e:
            print(f"An unexpected error occurred during Ollama connection check: {e}", file=sys.stderr)
            sys.exit(1)


    def _format_history(
        self, system_prompt: str, history: List[Dict[str, str]]
    ) -> List[Dict[str, Any]]:
        """Formats system prompt and chat history for the Ollama API."""
        ollama_messages: List[Dict[str, Any]] = []

        # Add the system prompt first if it exists
        if system_prompt:
            ollama_messages.append({"role": "system", "content": system_prompt})

        # Add the rest of the history
        for message in history:
            role = message.get("role")
            content = message.get("content", "")
            # Ollama uses 'user' and 'assistant' roles directly
            if role in ["user", "assistant"]:
                ollama_messages.append({"role": role, "content": content})
            # We could potentially handle 'tool' roles here if needed later
            else:
                 print(f"Warning: Skipping message with unhandled role '{role}' for Ollama.", file=sys.stderr)


        return ollama_messages

    def generate_content(
        self, system_prompt: str, history: List[Dict[str, str]]
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Sends the prompt and history to the Ollama API (non-streaming).

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
             return None, "Cannot send request to Ollama with empty messages."

        # Ensure there's at least one non-system message if a system prompt exists
        if system_prompt and len(formatted_messages) == 1:
             return None, "Cannot send request to Ollama with only a system message."


        payload = {
            "model": self.model,
            "messages": formatted_messages,
            "stream": False, # Request a single response object
            # Add options if needed, e.g., "options": {"temperature": 0.7}
        }

        headers = {"Content-Type": "application/json"}

        try:
            response = requests.post(
                self.api_url, headers=headers, json=payload, timeout=180 # Adjust timeout as needed
            )
            response.raise_for_status() # Check for HTTP errors

            response_data = response.json()

            # --- Parse the non-streaming response ---
            # Expected structure: response_data['message']['content']
            if response_data.get("done") is True and "message" in response_data:
                message_content = response_data["message"].get("content")
                if message_content is not None:
                     # Check for specific error messages if Ollama puts them in content
                     if "error" in message_content.lower() and len(message_content) < 100: # Basic check
                           if f"model '{self.model}' not found" in message_content:
                                return None, f"Ollama Error: Model '{self.model}' not found locally. Pull it with `ollama pull {self.model}`."
                           return None, f"Ollama API reported an error: {message_content}"
                     return message_content, None # Success
                else:
                    # Handle case where 'content' key is missing in the message
                    return None, f"Ollama API Error: Response missing 'content' in message: {response_data}"
            elif "error" in response_data:
                 # Handle explicit top-level errors
                 error_detail = response_data["error"]
                 if f"model '{self.model}' not found" in error_detail:
                     return None, f"Ollama Error: Model '{self.model}' not found locally. Pull it with `ollama pull {self.model}`."
                 return None, f"Ollama API Error: {error_detail}"
            else:
                # Handle other unexpected structures or if 'done' is not true
                 done_status = response_data.get('done', 'Not specified')
                 return None, f"Ollama API Error: Unexpected response structure or incomplete response (done={done_status}). Data: {response_data}"


        except requests.Timeout:
             return None, f"Ollama API request timed out after 180 seconds."
        except requests.ConnectionError as e:
            return None, f"Ollama API Connection Error: Could not connect to {self.api_url}. Is Ollama running? Details: {e}"
        except requests.HTTPError as e:
             # Try to get more specific error info from response body
            error_msg = f"Ollama API HTTP Error: {e.response.status_code} {e.response.reason} for URL {self.api_url}"
            try:
                 error_details = e.response.json()
                 error_msg += f"\nDetails: {json.dumps(error_details)}"
            except json.JSONDecodeError:
                 error_msg += f"\nResponse Body (non-JSON): {e.response.text}"
            return None, error_msg
        except requests.RequestException as e:
            # Catch other requests-related errors
            return None, f"Ollama API Request Error: {e}"
        except json.JSONDecodeError as e:
             return None, f"Failed to decode JSON response from Ollama: {e}\nResponse text: {response.text}"
        except Exception as e:
            # Catch any other unexpected errors
            return None, f"An unexpected error occurred during Ollama API call: {type(e).__name__} - {e}"