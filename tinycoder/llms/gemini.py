import os
import tinycoder.requests as requests
import json
import sys
from typing import List, Dict, Optional, Tuple, Iterator
from tinycoder.llms.base import LLMClient
 
DEFAULT_GEMINI_MODEL = "gemini-2.5-pro"
API_ENDPOINT = "generateContent"

class GeminiClient(LLMClient):
    """
    Client for interacting with the Google Gemini API.
    This version corrects the authentication method by using headers.
    """

    def __init__(self, model: Optional[str] = None, api_key: Optional[str] = None):
        resolved_api_key = api_key or os.environ.get("GEMINI_API_KEY")
        if not resolved_api_key:
            print("Error: GEMINI_API_KEY environment variable not set.", file=sys.stderr)
            sys.exit(1)

        resolved_model = model or DEFAULT_GEMINI_MODEL
        super().__init__(model=resolved_model, api_key=resolved_api_key)

        self.api_url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:{API_ENDPOINT}"

    def _format_history(self, history: List[Dict[str, str]]) -> List[Dict[str, any]]:
        """Formats chat history for the Gemini API's 'contents' field."""
        gemini_history = []
        for message in history:
            role = message.get("role")
            content = message.get("content", "")
            # Map standard roles to Gemini's expected roles
            if role == "user":
                gemini_role = "user"
            elif role == "assistant":
                gemini_role = "model"
            else:
                # Skip system messages (handled separately) or other roles
                continue
            gemini_history.append({"role": gemini_role, "parts": [{"text": content}]})
        return gemini_history

    def generate_content(
        self, system_prompt: str, history: List[Dict[str, str]]
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Sends the prompt and history to the Gemini API (non-streaming).

        Args:
            system_prompt: The system instruction text.
            history: The chat history list (excluding the system prompt).

        Returns:
            A tuple containing (response_text, error_message).
        """
        formatted_history = self._format_history(history)

        payload = {
            "contents": formatted_history,
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "generationConfig": {
                "responseMimeType": "text/plain",
                "temperature": 0.7,
            },
        }

        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": self._api_key
        }

        try:
            response = requests.post(
                self.api_url, headers=headers, json=payload, timeout=120
            )
            response.raise_for_status()  # Raise HTTPError for bad responses (4xx or 5xx)

            response_data = response.json()

            # --- Your robust parsing logic can now work correctly ---
            if "candidates" in response_data and response_data["candidates"]:
                candidate = response_data["candidates"][0]
                if (
                    "content" in candidate
                    and "parts" in candidate["content"]
                    and candidate["content"]["parts"]
                ):
                    full_text = "".join(
                        part.get("text", "") for part in candidate["content"]["parts"]
                    )
                    finish_reason = candidate.get("finishReason")
                    if finish_reason and finish_reason not in ["STOP", "MAX_TOKENS"]:
                        safety_ratings = candidate.get("safetyRatings", [])
                        error_detail = f"Gemini response finished unexpectedly: {finish_reason}. Safety: {safety_ratings}"
                        print(f"WARNING: {error_detail}", file=sys.stderr)
                    return full_text, None
                else:
                    error_detail = f"Unexpected candidate structure: {candidate}"
                    print(response_data)
                    return None, f"Gemini API Error: Could not extract text. {error_detail}"
            elif "error" in response_data:
                error_detail = response_data["error"].get("message", "Unknown error structure")
                return None, f"Gemini API Error: {error_detail}"
            else:
                return None, f"Gemini API Error: Unexpected response structure: {response_data}"

        except requests.RequestException as e:
            error_msg = f"Gemini API Request Error: {e}"
            if e.response is not None:
                try:
                    error_details = e.response.json()
                    error_msg += f"\nDetails: {json.dumps(error_details)}"
                except json.JSONDecodeError:
                    error_msg += f"\nResponse Body (non-JSON): {e.response.text}"
            return None, error_msg
        except Exception as e:
            return None, f"An unexpected error occurred during Gemini API call: {e}"

    def generate_content_stream(
        self, system_prompt: str, history: List[Dict[str, str]]
    ) -> Iterator[str]:
        """
        Generates content from the Gemini API using a streaming connection.
        This method is a generator, yielding text chunks as they are received.
        """
        # Use the streaming endpoint with Server-Sent Events (SSE) for easier parsing
        stream_api_url = self.api_url.replace(f":{API_ENDPOINT}", ":streamGenerateContent") + "?alt=sse"
        
        formatted_history = self._format_history(history)

        payload = {
            "contents": formatted_history,
            "systemInstruction": {"parts": [{"text": system_prompt}]},
            "generationConfig": {
                "responseMimeType": "text/plain",
                "temperature": 0.7,
            },
        }

        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": self._api_key
        }

        response = None
        try:
            response = requests.post(stream_api_url, headers=headers, json=payload, stream=True, timeout=180)
            response.raise_for_status()
            for line in response.iter_lines():
                if line:
                    decoded_line = line.decode('utf-8')
                    if decoded_line.startswith('data: '):
                        json_str = decoded_line[6:]
                        try:
                            data = json.loads(json_str)
                            if "candidates" in data and data["candidates"]:
                                candidate = data["candidates"][0]
                                if "content" in candidate and "parts" in candidate["content"]:
                                    for part in candidate["content"]["parts"]:
                                        if "text" in part:
                                            yield part["text"]
                        except json.JSONDecodeError:
                            # In SSE, there can be other message types or partial data.
                            # For this implementation, we silently ignore parsing errors.
                            continue
        except requests.RequestException as e:
            error_msg = f"Gemini API Request Error: {e}"
            if e.response is not None:
                try:
                    error_details = e.response.json()
                    error_msg += f"\nDetails: {json.dumps(error_details)}"
                except json.JSONDecodeError:
                    error_msg += f"\nResponse Body (non-JSON): {e.response.text}"
            yield f"STREAMING_ERROR: {error_msg}"
        except Exception as e:
            yield f"STREAMING_ERROR: An unexpected error occurred during Gemini API stream: {e}"
        finally:
            if response:
                response.close()
