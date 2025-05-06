import os
import sys
import json
from typing import List, Dict, Optional, Tuple, Any

import tinycoder.requests as requests
from tinycoder.llms.base import LLMClient

# Default model
DEFAULT_TOGETHER_MODEL = "meta-llama/Meta-Llama-3.1-8B-Instruct-Turbo"
TOGETHER_API_ENDPOINT = "https://api.together.xyz/v1/chat/completions"
TOGETHER_API_KEY_ENV_VAR = "TOGETHER_API_KEY"

# Conservative default max tokens limit
DEFAULT_MAX_TOKENS = 4096


class TogetherAIClient(LLMClient):
    """
    Client for interacting with the Together.ai API.
    """

    def __init__(self, model: Optional[str] = None, api_key: Optional[str] = None):
        """
        Initializes the Together.ai client.

        Args:
            model: The specific Together.ai model to use.
                   Defaults to DEFAULT_TOGETHER_MODEL if not provided.
            api_key: The Together.ai API key. If not provided, attempts to read from
                     the TOGETHER_API_KEY environment variable.
        """
        resolved_api_key = api_key or os.environ.get(TOGETHER_API_KEY_ENV_VAR)
        if not resolved_api_key:
            print(
                f"Error: {TOGETHER_API_KEY_ENV_VAR} environment variable not set.",
                file=sys.stderr,
            )
            sys.exit(1)

        resolved_model = model or DEFAULT_TOGETHER_MODEL
        # Remove 'together-' prefix if present
        if resolved_model and resolved_model.startswith("together-"):
            resolved_model = resolved_model[9:]  # Remove 'together-' prefix
            
        super().__init__(model=resolved_model, api_key=resolved_api_key)

        self.api_url = TOGETHER_API_ENDPOINT
        self.headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    def _format_history(self, system_prompt: str, history: List[Dict[str, str]]) -> List[Dict[str, Any]]:
        """
        Formats chat history for the Together.ai API's 'messages' field.
        Places system prompt at the beginning if provided.
        """
        together_messages = []
        
        # Add system prompt at the beginning if it exists
        if system_prompt:
            together_messages.append({"role": "system", "content": system_prompt})
            
        # Add the rest of the history
        for message in history:
            role = message.get("role")
            content = message.get("content", "")
            
            # Together.ai uses standard OpenAI-compatible roles: 'system', 'user', 'assistant'
            if role in ["system", "user", "assistant"]:
                together_messages.append({"role": role, "content": content})
            else:
                # Skip other non-standard roles like 'tool' for now
                print(f"Warning: Skipping message with unhandled role '{role}' for Together.ai.", file=sys.stderr)
                
        return together_messages

    def generate_content(
        self, system_prompt: str, history: List[Dict[str, str]]
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Sends the prompt and history to the Together.ai API.

        Args:
            system_prompt: The system instruction text.
            history: The chat history list (excluding system prompt).

        Returns:
            A tuple containing (response_text, error_message).
            response_text is None if an error occurs.
            error_message is None if the request is successful.
        """
        formatted_messages = self._format_history(system_prompt, history)

        # Basic validation: Ensure we don't send empty messages
        if not formatted_messages:
            return None, "Cannot send request to Together.ai with empty messages."
        
        # Together.ai requires at least one user message
        if not any(msg['role'] == 'user' for msg in formatted_messages):
            return None, "Together.ai API requires at least one user message."

        payload = {
            "model": self.model,
            "messages": formatted_messages,
            "max_tokens": DEFAULT_MAX_TOKENS,
            # "temperature": 0.7,  # Optional parameters
            # "top_p": 0.9,
        }

        try:
            print(f"Debug - Using model: {self.model}")
            print(f"Debug - Sending payload: {json.dumps(payload)}...")
            
            response = requests.post(
                self.api_url, headers=self.headers, json=payload, timeout=180
            )
            
            print(f"Debug - Response status: {response.status_code}")
            print(f"Debug - Response text: {response.text}...")
            
            response.raise_for_status()  # Check for HTTP errors

            response_data = response.json()

            # Parse the successful response - Together.ai follows OpenAI format
            # Expected structure: response_data['choices'][0]['message']['content']
            if "choices" in response_data and response_data["choices"] and "message" in response_data["choices"][0]:
                first_choice = response_data["choices"][0]
                message = first_choice.get("message", {})
                
                if "content" in message:
                    response_text = message["content"]
                    # Check if the response was truncated
                    finish_reason = first_choice.get("finish_reason")
                    if finish_reason == "length":
                        print("Warning: Together.ai response truncated due to max_tokens limit.", file=sys.stderr)
                    
                    return response_text, None  # Success
                else:
                    return None, f"Together.ai API Error: Response message missing 'content': {message}"
            else:
                # Handle unexpected response structure
                return None, f"Together.ai API Error: Unexpected response structure: {response_data}"

        except requests.Timeout:
            return None, f"Together.ai API request timed out after 180 seconds."
        except requests.HTTPError as e:
            error_msg = f"Together.ai API HTTP Error: {e.response.status_code} {e.response.reason} for URL {self.api_url}"
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
            # Catch other requests-related errors (connection, etc.)
            return None, f"Together.ai API Request Error: {e}"
        except json.JSONDecodeError as e:
            return None, f"Failed to decode JSON response from Together.ai: {e}\nResponse text: {response.text}"
        except Exception as e:
            # Catch any other unexpected errors during the process
            return None, f"An unexpected error occurred during Together.ai API call: {type(e).__name__} - {e}"