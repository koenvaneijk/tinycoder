import os
import sys
import json
from typing import List, Dict, Optional, Tuple, Any

import tinycoder.requests as requests # Use the local requests shim
from tinycoder.llms.base import LLMClient

DEFAULT_ANTHROPIC_MODEL = "claude-opus-4-20250514"
ANTHROPIC_API_ENDPOINT = "https://api.anthropic.com/v1/messages"
ANTHROPIC_API_VERSION = "2023-06-01"
ANTHROPIC_API_KEY_ENV_VAR = "ANTHROPIC_API_KEY"

# Anthropic requires max_tokens. 4096 is a reasonable default upper limit.
DEFAULT_MAX_TOKENS = 20000


class AnthropicClient(LLMClient):
    """
    Client for interacting with the Anthropic Claude API.
    """

    def __init__(self, model: Optional[str] = None, api_key: Optional[str] = None):
        """
        Initializes the Anthropic client.

        Args:
            model: The specific Anthropic model to use (e.g., "claude-3-7-sonnet-20250219").
                   Defaults to DEFAULT_ANTHROPIC_MODEL if not provided.
            api_key: The Anthropic API key. If not provided, attempts to read from
                     the ANTHROPIC_API_KEY environment variable.
        """
        resolved_api_key = api_key or os.environ.get(ANTHROPIC_API_KEY_ENV_VAR)
        if not resolved_api_key:
            print(
                f"Error: {ANTHROPIC_API_KEY_ENV_VAR} environment variable not set.",
                file=sys.stderr,
            )
            sys.exit(1)

        resolved_model = model or DEFAULT_ANTHROPIC_MODEL
        super().__init__(model=resolved_model, api_key=resolved_api_key)

        self.api_url = ANTHROPIC_API_ENDPOINT
        self.headers = {
            "x-api-key": self._api_key, # Access api_key stored by base class
            "anthropic-version": ANTHROPIC_API_VERSION,
            "content-type": "application/json",
        }

    def _format_history(self, history: List[Dict[str, str]]) -> List[Dict[str, Any]]:
        """Formats chat history for the Anthropic API's 'messages' field."""
        anthropic_messages: List[Dict[str, Any]] = []
        for message in history:
            role = message.get("role")
            content = message.get("content", "")
            # Anthropic uses 'user' and 'assistant' roles directly
            if role in ["user", "assistant"]:
                anthropic_messages.append({"role": role, "content": content})
            else:
                # Skip system (handled separately) and other non-standard roles like 'tool' for now
                # We might need to handle 'tool' responses later if using tools.
                print(f"Warning: Skipping message with unhandled role '{role}' for Anthropic.", file=sys.stderr)
        return anthropic_messages

    def generate_content(
        self, system_prompt: str, history: List[Dict[str, str]]
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Sends the prompt and history to the Anthropic API.

        Args:
            system_prompt: The system instruction text.
            history: The chat history list (excluding system prompt).

        Returns:
            A tuple containing (response_text, error_message).
            response_text is None if an error occurs.
            error_message is None if the request is successful.
        """
        formatted_messages = self._format_history(history)

        # Basic validation: Ensure we don't send empty messages
        if not formatted_messages and not system_prompt:
             return None, "Cannot send request to Anthropic with empty system prompt and messages."
        # Anthropic allows sending just a system prompt and user message,
        # but requires at least one user message if messages are present.
        if not any(msg['role'] == 'user' for msg in formatted_messages):
             if system_prompt and not formatted_messages:
                 # This case is unlikely with current logic, but technically possible.
                 # Anthropic API might require a first user message. Let's prevent it.
                 return None, "Cannot send only a system prompt to Anthropic without any user messages."
             elif not system_prompt and not formatted_messages:
                 # Already caught above
                 pass
             elif formatted_messages: # Only assistant messages?
                 return None, "Cannot send request to Anthropic with only assistant messages."


        payload = {
            "model": self.model,
            "messages": formatted_messages,
            "max_tokens": DEFAULT_MAX_TOKENS,
            # Anthropic uses a top-level 'system' parameter
            "system": system_prompt if system_prompt else None,
            # "stream": False, # Default is False for this endpoint
            # Can add temperature, top_p etc. here if needed
            # "temperature": 0.7,
        }
        # Remove system from payload if it's None or empty
        if not payload["system"]:
             del payload["system"]


        try:
            response = requests.post(
                self.api_url, headers=self.headers, json=payload, timeout=600
            )
            response.raise_for_status() # Check for HTTP 4xx/5xx errors

            response_data = response.json()

            # --- Parse the successful response ---
            # Expected structure: response_data['content'][0]['text']
            if "content" in response_data and isinstance(response_data["content"], list) and response_data["content"]:
                # Check if the response type is text
                first_content_block = response_data["content"][0]
                if first_content_block.get("type") == "text":
                    response_text = first_content_block.get("text")
                    if response_text is not None:
                        # Check stop reason (e.g., 'max_tokens', 'stop_sequence')
                        stop_reason = response_data.get("stop_reason")
                        if stop_reason == "max_tokens":
                             print("Warning: Anthropic response truncated due to max_tokens limit.", file=sys.stderr)
                        # Other reasons like 'tool_use' might need specific handling later
                        return response_text, None # Success
                    else:
                        return None, f"Anthropic API Error: Response content block missing 'text': {first_content_block}"
                else:
                     # Handle unexpected content block types (e.g., 'tool_use' if not handled)
                     return None, f"Anthropic API Error: Unexpected content block type '{first_content_block.get('type')}': {first_content_block}"

            # --- Handle API errors reported in the JSON body ---
            # Anthropic error structure: response_data['type'] == 'error', response_data['error'] contains details
            elif response_data.get("type") == "error" and "error" in response_data:
                error_details = response_data["error"]
                error_type = error_details.get("type", "unknown_error")
                error_message = error_details.get("message", "No error message provided.")
                return None, f"Anthropic API Error ({error_type}): {error_message}"
            else:
                # Handle other unexpected valid JSON response structures
                 return None, f"Anthropic API Error: Unexpected response structure: {response_data}"

        # --- Handle Request/HTTP Errors ---
        except requests.Timeout:
             return None, f"Anthropic API request timed out after 180 seconds."
        except requests.HTTPError as e:
            error_msg = f"Anthropic API HTTP Error: {e.response.status_code} {e.response.reason} for URL {self.api_url}"
            # Try to get more specific error info from response body (which is likely JSON for Anthropic)
            try:
                 error_details = e.response.json()
                 if error_details.get("type") == "error" and "error" in error_details:
                     # Extract Anthropic-specific error details if available
                     err_data = error_details["error"]
                     error_type = err_data.get("type", "unknown_http_error")
                     error_message = err_data.get("message", "No message in error details.")
                     error_msg += f"\nDetails ({error_type}): {error_message}"
                 else:
                      error_msg += f"\nResponse Body: {json.dumps(error_details)}"
            except json.JSONDecodeError:
                 error_msg += f"\nResponse Body (non-JSON): {e.response.text}"
            except Exception: # Catch errors during error detail parsing
                 error_msg += "\n(Could not parse error details from response body)"
            return None, error_msg
        except requests.RequestException as e:
            # Catch other requests-related errors (connection, etc.)
            return None, f"Anthropic API Request Error: {e}"
        except json.JSONDecodeError as e:
             # Should be caught by HTTPError parsing ideally, but as fallback
             return None, f"Failed to decode JSON response from Anthropic: {e}\nResponse text: {response.text}"
        except Exception as e:
            # Catch any other unexpected errors during the process
            return None, f"An unexpected error occurred during Anthropic API call: {type(e).__name__} - {e}"