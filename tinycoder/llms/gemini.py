import os
import tinycoder.requests as requests
import json
import sys
from typing import List, Dict, Optional, Tuple

from tinycoder.llms.base import LLMClient  # Import the base class

# Default model - can be overridden by constructor or --model arg
DEFAULT_GEMINI_MODEL = "gemini-2.5-pro-preview-05-06"  # Keep Gemini-specific default
# Using generateContent as streamGenerateContent requires handling streamed responses.
# Sticking to generateContent for now based on simpler non-streaming parsing.
# If streamGenerateContent is strictly needed, response handling must be updated.
API_ENDPOINT = "generateContent"
# API_ENDPOINT = "streamGenerateContent" # Use this if stream handling is implemented


class GeminiClient(LLMClient):  # Inherit from LLMClient
    """
    Client for interacting with the Google Gemini API using a local requests module.
    """

    def __init__(self, model: Optional[str] = None, api_key: Optional[str] = None):
        # Use provided API key or get from environment
        resolved_api_key = api_key or os.environ.get("GEMINI_API_KEY")
        if not resolved_api_key:
            print(
                "Error: GEMINI_API_KEY environment variable not set.", file=sys.stderr
            )
            sys.exit(1)

        # Use provided model or default, then call super().__init__
        resolved_model = model or DEFAULT_GEMINI_MODEL
        super().__init__(
            model=resolved_model, api_key=resolved_api_key
        )  # Pass resolved values to base

        # Construct API URL using the selected model and endpoint
        # Access model and api_key via properties/attributes set by super()
        self.api_url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:{API_ENDPOINT}?key={self._api_key}"

    def _format_history(self, history: List[Dict[str, str]]) -> List[Dict[str, any]]:
        """Formats chat history for the Gemini API's 'contents' field."""
        # This method remains specific to Gemini
        gemini_history = []
        for message in history:
            role = message.get("role")
            content = message.get("content", "")
            # Map roles: 'user' -> 'user', 'assistant' -> 'model'
            if role == "user":
                gemini_role = "user"
            elif role == "assistant":
                gemini_role = "model"
            else:
                # Skip system messages (handled separately) and other non-standard roles
                continue

            # Append formatted message to the history list
            gemini_history.append({"role": gemini_role, "parts": [{"text": content}]})
        return gemini_history

    def generate_content(
        self, system_prompt: str, history: List[Dict[str, str]]
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Sends the prompt and history to the Gemini API (non-streaming).

        Args:
            system_prompt: The system instruction text.
            history: The chat history list (excluding system prompt).

        Returns:
            A tuple containing (response_text, error_message).
            response_text is None if an error occurs.
            error_message is None if the request is successful.
        """
        formatted_history = self._format_history(history)

        # Construct the payload for the Gemini API request
        payload = {
            "contents": formatted_history,
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "generationConfig": {
                "responseMimeType": "text/plain",
                # Consider adding temperature, topP, maxOutputTokens etc. if needed
                # "temperature": 0.7,
            },
            # Add safety settings if required by the API or use case
            # "safetySettings": [...]
        }

        headers = {"Content-Type": "application/json"}

        try:
            # Make the POST request using the (potentially local) requests module
            response = requests.post(
                self.api_url, headers=headers, json=payload, timeout=600
            )  # Longer timeout
            response.raise_for_status()  # Raise HTTPError for bad responses (4xx or 5xx)

            response_data = response.json()

            # --- Parse the non-streaming response ---
            # Expected structure: response_data['candidates'][0]['content']['parts'][0]['text']
            if "candidates" in response_data and response_data["candidates"]:
                candidate = response_data["candidates"][0]
                if (
                    "content" in candidate
                    and "parts" in candidate["content"]
                    and candidate["content"]["parts"]
                ):
                    # Concatenate text from all parts (usually just one for text/plain)
                    full_text = "".join(
                        part.get("text", "") for part in candidate["content"]["parts"]
                    )
                    # Check for finishReason - might indicate blocked content etc.
                    finish_reason = candidate.get("finishReason")
                    if finish_reason and finish_reason not in ["STOP", "MAX_TOKENS"]:
                        safety_ratings = candidate.get("safetyRatings", [])
                        error_detail = f"Gemini response finished unexpectedly: {finish_reason}. Safety: {safety_ratings}"
                        print(f"WARNING: {error_detail}", file=sys.stderr)
                        # Decide if you want to return partial text or None
                        # return full_text, error_detail # Return partial text with warning
                        # return None, error_detail # Or return None on safety/other issues
                    return full_text, None  # Success
                else:
                    # Handle cases where the expected structure is missing
                    error_detail = f"Unexpected candidate structure: {candidate}"
                    return (
                        None,
                        f"Gemini API Error: Could not extract text. {error_detail}",
                    )
            elif "error" in response_data:
                # Handle explicit errors returned by the API
                error_detail = response_data["error"].get(
                    "message", "Unknown error structure"
                )
                return None, f"Gemini API Error: {error_detail}"
            else:
                # Handle other unexpected response formats
                return (
                    None,
                    f"Gemini API Error: Unexpected response structure: {response_data}",
                )

        except requests.RequestException as e:
            # Handle errors during the HTTP request itself
            error_msg = f"Gemini API Request Error: {e}"
            # Try to include response body if available for more context
            if e.response is not None:
                try:
                    error_details = e.response.json()
                    error_msg += f"\nDetails: {json.dumps(error_details)}"
                except json.JSONDecodeError:
                    error_msg += f"\nResponse Body (non-JSON): {e.response.text}"
            return None, error_msg
        except Exception as e:
            # Catch any other unexpected errors during the process
            return None, f"An unexpected error occurred during Gemini API call: {e}"

    # TODO: Implement stream_generate_content if needed for the 'streamGenerateContent' endpoint
    # def stream_generate_content(self, system_prompt: str, history: List[Dict[str, str]]):
    #     # ... construct payload ...
    #     response = requests.post(self.api_url, headers=headers, json=payload, stream=True)
    #     response.raise_for_status()
    #     full_response_text = ""
    #     for line in response.iter_lines():
    #         if line:
    #             try:
    #                 # Assuming stream sends JSON objects line by line
    #                 chunk = json.loads(line)
    #                 # Extract text from chunk based on streaming format
    #                 # ... parsing logic for streamed chunks ...
    #                 # text_part = chunk['candidates'][0]['content']['parts'][0]['text']
    #                 # full_response_text += text_part
    #                 # yield text_part # Or yield chunks/parts
    #             except json.JSONDecodeError:
    #                 print(f"Warning: Could not decode JSON stream line: {line}", file=sys.stderr)
    #             except Exception as e:
    #                 print(f"Error processing stream chunk: {e}", file=sys.stderr)
    #     # return full_response_text
