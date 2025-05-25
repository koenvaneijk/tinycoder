import os
import json
import logging
from typing import Generator, List, Dict, Optional, Any, Union, Tuple
import sys

import tinycoder.requests as requests
from tinycoder.llms.base import LLMClient  # Import the base class

# --- Constants and Setup ---
API_URL = "https://api.deepseek.com/chat/completions"
DEFAULT_DEEPSEEK_MODEL = "deepseek-reasoner"  # Default model for DeepSeek

logger = logging.getLogger(__name__)

# --- Type Definitions ---

MessagesType = List[Dict[str, Any]]
ToolType = List[Dict[str, Any]]
# Type for streaming yields
YieldType = Dict[
    str, Union[Optional[str], Optional[List[Dict[str, Any]]], Optional[str]]
]  # {"type": "content/tool_call/error/finish", "data": ...}
# Type for the non-streaming return value (content string)
NonStreamReturnType = str
# Type for the non-streaming return value including tool calls (if needed later)
# NonStreamReturnTypeComplex = Dict[str, Union[Optional[str], Optional[List[Dict[str, Any]]], Optional[str]]] # {"content": ..., "tool_calls": ..., "finish_reason": ...}


# --- Low-level API Call Function ---
# Keep the existing answer function for direct API interaction if needed,
# but the client class will be the primary interface for tinycoder.
def answer(
    messages: MessagesType,
    model: str,  # Add model parameter
    api_key: str,  # Add api_key parameter
    tools: Optional[ToolType] = None,
    tool_choice: Optional[
        Union[str, Dict]
    ] = "auto",  # Default to auto if tools are provided, API defaults to none otherwise
    stream: bool = False,  # Default to non-streaming for client usage
) -> Union[Generator[YieldType, None, None], NonStreamReturnType]:
    """
    Gets a response from the DeepSeek API, supporting both streaming and non-streaming modes.

    Args:
        messages: A list of message dictionaries (history).
        model: The specific DeepSeek model to use (e.g., "deepseek-chat").
        api_key: The DeepSeek API key.
        tools: An optional list of tool schemas the model can use.
        tool_choice: Optional control for tool usage ('none', 'auto', 'required', or specific tool).
        stream: If True, returns a generator yielding response chunks.
                If False, returns the complete response content as a string.

    Returns:
        If stream is True: A generator yielding dictionaries indicating the type of data:
            - {"type": "content", "data": str}: A chunk of text content.
            - {"type": "tool_calls", "data": List[Dict]}: A list of tool calls detected in a chunk.
              Note: Tool call arguments might be streamed incrementally. The consumer needs to accumulate.
            - {"type": "error", "data": str}: An error message.
            - {"type": "finish", "data": str}: The finish reason (e.g., "stop", "tool_calls").
        If stream is False: The complete message content as a string.
            Note: Tool calls are currently ignored in the non-streaming return value.
    """
    if not api_key:
        # Handle missing API key within the function call
        logger.error("DeepSeek API key was not provided to the answer function.")
        # Return an error indicator compatible with the return type
        return (
            "[ERROR: API Key Missing]"
            if not stream
            else iter([{"type": "error", "data": "API Key Missing"}])
        )

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}",  # Use passed api_key
    }

    payload: Dict[str, Any] = {
        "model": model,  # Use passed model
        "messages": messages,
        "stream": stream,  # Use the stream parameter
    }

    # Add tools and tool_choice to payload if tools are provided
    if tools:
        payload["tools"] = tools
        payload["tool_choice"] = tool_choice

    if stream:
        # Wrap the streaming logic in a separate generator function
        # to handle the Union return type correctly.
        def _stream_generator():
            try:
                # Use the 'json' parameter to pass the payload directly
                response = requests.post(
                    API_URL, headers=headers, json=payload, stream=True
                )
                response.raise_for_status()  # Check for initial HTTP errors (like 4xx, 5xx)

                # Process the stream
                for line in response.iter_lines():
                    if line:
                        decoded_line = line.decode("utf-8")
                        # Skip empty or whitespace-only lines often present between SSE messages
                        if not decoded_line.strip():
                            continue
                        if decoded_line.startswith("data: "):
                            data_str = decoded_line[len("data: ") :]
                            # Handle the [DONE] marker which might have surrounding whitespace
                            if data_str.strip() == "[DONE]":
                                break  # Signal end of stream
                            try:
                                chunk = json.loads(data_str)
                                choices = chunk.get("choices")
                                if choices and len(choices) > 0:
                                    choice = choices[0]
                                    delta = choice.get("delta", {})
                                    content_delta = delta.get("content")
                                    tool_calls_delta = delta.get("tool_calls")
                                    finish_reason = choice.get("finish_reason")

                                    if content_delta:
                                        yield {"type": "content", "data": content_delta}

                                    if tool_calls_delta:
                                        # Yield tool calls as they arrive.
                                        # The consumer (assistant.py) will need to accumulate these.
                                        yield {
                                            "type": "tool_calls",
                                            "data": tool_calls_delta,
                                        }

                                    # Check for finish reason to yield final status and stop iteration
                                    if finish_reason:
                                        logger.info(
                                            f"Stream finished with reason: {finish_reason}"
                                        )
                                        yield {"type": "finish", "data": finish_reason}
                                        break  # Stop processing lines after finish
                            except json.JSONDecodeError:
                                logger.error(
                                    f"Error decoding JSON from stream: {data_str}"
                                )
                                yield {
                                    "type": "error",
                                    "data": f"JSON decode error: {data_str}",
                                }
                            except Exception as e:
                                logger.error(
                                    f"Error processing stream chunk: {e} - Chunk: {data_str}"
                                )
                                yield {
                                    "type": "error",
                                    "data": f"Chunk processing error: {e}",
                                }

                        elif decoded_line.startswith(":"):
                            # Ignore SSE comments
                            pass
                        else:
                            logger.warning(
                                f"Received unexpected line in stream: {decoded_line}"
                            )

            except requests.RequestException as e:
                error_message = f"Error calling DeepSeek streaming API: {e}"
                if e.response is not None:
                    try:
                        error_details = e.response.text
                        error_message += f"\nResponse status: {e.response.status_code}"
                        error_message += f"\nResponse body: {error_details}"
                    except Exception as read_err:
                        error_message += (
                            f"\nCould not read error response body: {read_err}"
                        )
                logger.error(error_message)
                yield {"type": "error", "data": error_message}  # Signal error

            except Exception as e:
                import traceback

                error_message = f"An unexpected error occurred during DeepSeek API stream setup or call: {e}\n{traceback.format_exc()}"
                logger.error(error_message)
                yield {"type": "error", "data": error_message}  # Signal error

        return _stream_generator()  # Return the generator if stream=True

    else:  # Handle non-streaming case
        try:
            response = requests.post(
                API_URL,
                headers=headers,
                json=payload,
                stream=False,  # stream=False here
            )
            response.raise_for_status()
            response_json = response.json()

            choices = response_json.get("choices")
            if choices and len(choices) > 0:
                message = choices[0].get("message", {})
                content = message.get("content")
                # tool_calls = message.get("tool_calls") # Available if needed later
                # finish_reason = choices[0].get("finish_reason") # Available if needed later

                if content:
                    logger.info(
                        f"Non-streaming call successful. Finish reason: {choices[0].get('finish_reason')}"
                    )
                    return content  # Return the full content string
                else:
                    # Handle cases where content might be missing (e.g., only tool calls)
                    logger.warning(
                        "Non-streaming response received, but content was empty."
                    )
                    # Decide what to return here. Empty string? Raise error?
                    # For now, return empty string as the request was for "string response".
                    return ""
            else:
                logger.error(
                    f"Non-streaming API call failed: No choices found in response. Response: {response_json}"
                )
                # Consider raising an exception or returning a specific error indicator
                return "[ERROR: No choices found in API response]"

        except requests.RequestException as e:
            error_message = f"Error calling DeepSeek non-streaming API: {e}"
            if e.response is not None:
                try:
                    error_details = e.response.text
                    error_message += f"\nResponse status: {e.response.status_code}"
                    error_message += f"\nResponse body: {error_details}"
                except Exception as read_err:
                    error_message += f"\nCould not read error response body: {read_err}"
            logger.error(error_message)
            # Decide how to signal error in non-streaming mode. Raise exception? Return error string?
            # Returning an error string for now.
            return f"[ERROR: API Request Failed - {e}]"
        except json.JSONDecodeError as e:
            error_message = f"Error decoding JSON response from non-streaming API: {e}\nResponse text: {response.text}"
            logger.error(error_message)
            return f"[ERROR: JSON Decode Failed]"
        except Exception as e:
            import traceback

            error_message = f"An unexpected error occurred during DeepSeek non-streaming API call: {e}\n{traceback.format_exc()}"
            logger.error(error_message)
            return f"[ERROR: Unexpected error - {e}]"


# --- DeepSeek Client Class ---


class DeepSeekClient(LLMClient):
    """
    Client for interacting with the DeepSeek API using the answer function.
    """

    def __init__(self, model: Optional[str] = None, api_key: Optional[str] = None):
        # Use provided API key or get from environment
        resolved_api_key = api_key or os.getenv("DEEPSEEK_API_KEY")
        if not resolved_api_key:
            # Handle error more gracefully within tinycoder's context if possible
            # For now, print error and exit like GeminiClient
            print(
                "Error: DEEPSEEK_API_KEY environment variable not set.", file=sys.stderr
            )
            sys.exit(1)

        # Use provided model or default, then call super().__init__
        resolved_model = model or DEFAULT_DEEPSEEK_MODEL
        super().__init__(
            model=resolved_model, api_key=resolved_api_key
        )  # Pass resolved values to base
        print(
            f"INFO: Using DeepSeek model: {self.model}", file=sys.stderr
        )  # Info message

    def _format_history(
        self, system_prompt: str, history: List[Dict[str, str]]
    ) -> List[Dict[str, any]]:
        """Formats system prompt and history for the DeepSeek API."""
        # DeepSeek expects system prompt as the first message
        formatted_messages = [{"role": "system", "content": system_prompt}]
        # Append the rest of the history, mapping roles if necessary (DeepSeek uses 'user', 'assistant')
        for message in history:
            role = message.get("role")
            content = message.get("content", "")
            # Ensure roles are 'user' or 'assistant'
            if role == "user":
                formatted_messages.append({"role": "user", "content": content})
            elif role == "assistant":
                # DeepSeek uses 'assistant' role for model responses
                formatted_messages.append({"role": "assistant", "content": content})
            # Skip other roles (like 'system' if it appears again, or 'tool')
            # Tool handling would require more logic here if needed later.

        return formatted_messages

    def generate_content(
        self, system_prompt: str, history: List[Dict[str, str]]
    ) -> Tuple[Optional[str], Optional[str]]:
        """
        Sends the prompt and history to the DeepSeek API (non-streaming).

        Args:
            system_prompt: The system instruction text.
            history: The chat history list (excluding system prompt).

        Returns:
            A tuple containing (response_text, error_message).
        """
        formatted_messages = self._format_history(system_prompt, history)

        # Call the non-streaming answer function
        response_content = answer(
            messages=formatted_messages,
            model=self.model,  # Pass model from client instance
            api_key=self._api_key,  # Pass API key from client instance
            stream=False,
        )

        # Check the response string for our error indicators
        if isinstance(response_content, str) and response_content.startswith("[ERROR:"):
            error_message = f"DeepSeek API Error: {response_content}"
            logger.error(error_message)
            return None, error_message
        elif isinstance(response_content, str):
            # Success
            return response_content, None
        else:
            # Should not happen with stream=False, but handle defensively
            error_message = f"DeepSeek API Error: Unexpected response type ({type(response_content)}) for non-streaming call."
            logger.error(error_message)
            return None, error_message
