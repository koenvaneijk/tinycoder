from typing import Dict, Optional, List, Any

PRICING_DATA: Dict[str, List[Dict[str, Any]]] = {
  "providers": [
    {
      "provider_name": "OpenAI",
      "models": [
        { "model_id": "gpt-4o", "input_price_per_million_tokens": 5.00, "output_price_per_million_tokens": 15.00 },
        { "model_id": "gpt-4-turbo", "input_price_per_million_tokens": 10.00, "output_price_per_million_tokens": 30.00 },
        { "model_id": "gpt-4", "input_price_per_million_tokens": 30.00, "output_price_per_million_tokens": 60.00 },
        { "model_id": "gpt-3.5-turbo-0125", "input_price_per_million_tokens": 0.50, "output_price_per_million_tokens": 1.50 },
        { "model_id": "gpt-4o-mini", "input_price_per_million_tokens": 0.15, "output_price_per_million_tokens": 0.60 }
      ]
    },
    {
      "provider_name": "Anthropic",
      "models": [
        { "model_id": "claude-3-opus-20240229", "input_price_per_million_tokens": 15.00, "output_price_per_million_tokens": 75.00 },
        { "model_id": "claude-3.5-sonnet-20240620", "input_price_per_million_tokens": 3.00, "output_price_per_million_tokens": 15.00 },
        { "model_id": "claude-3-sonnet-20240229", "input_price_per_million_tokens": 3.00, "output_price_per_million_tokens": 15.00 },
        { "model_id": "claude-3-haiku-20240307", "input_price_per_million_tokens": 0.25, "output_price_per_million_tokens": 1.25 }
      ]
    },
    {
      "provider_name": "Google",
      "models": [
        { "model_id": "gemini-2.5-pro", "input_price_per_million_tokens": 1.25, "output_price_per_million_tokens": 10.00 },
        { "model_id": "gemini-1.5-pro-latest", "input_price_per_million_tokens": 3.50, "output_price_per_million_tokens": 10.50 },
        { "model_id": "gemini-1.5-flash-latest", "input_price_per_million_tokens": 0.35, "output_price_per_million_tokens": 1.05 }
      ]
    },
    {
      "provider_name": "Groq",
      "models": [
          { "model_id": "llama3-8b-8192", "input_price_per_million_tokens": 0.05, "output_price_per_million_tokens": 0.10 },
          { "model_id": "llama3-70b-8192", "input_price_per_million_tokens": 0.59, "output_price_per_million_tokens": 0.79 },
          { "model_id": "mixtral-8x7b-32768", "input_price_per_million_tokens": 0.24, "output_price_per_million_tokens": 0.24 },
          { "model_id": "moonshotai/kimi-k2-instruct", "input_price_per_million_tokens": 1.00, "output_price_per_million_tokens": 3.00 }
      ]
    },
    {
        "provider_name": "Together",
        "models": [
            { "model_id": "Qwen/Qwen3-Coder-480B-A35B-Instruct-FP8", "input_price_per_million_tokens": 2.00, "output_price_per_million_tokens": 2.00 },
            { "model_id": "meta-llama/Llama-3-8B-chat-hf", "input_price_per_million_tokens": 0.10, "output_price_per_million_tokens": 0.10 },
            { "model_id": "meta-llama/Llama-3-70B-chat-hf", "input_price_per_million_tokens": 0.90, "output_price_per_million_tokens": 0.90 },
            { "model_id": "mistralai/Mixtral-8x7B-Instruct-v0.1", "input_price_per_million_tokens": 0.60, "output_price_per_million_tokens": 0.60 }
        ]
    }
  ]
}


def get_model_pricing(model_id: Optional[str]) -> Optional[Dict[str, float]]:
    """
    Finds the pricing information for a given model ID.

    Args:
        model_id: The identifier of the model (e.g., "gpt-4o").

    Returns:
        A dictionary with "input" and "output" prices per million tokens, or None if not found.
    """
    if not model_id:
        return None

    # Some client-side model names might have prefixes (e.g., 'openai/gpt-4o' or 'together/meta-llama/Llama-3-8B-chat-hf').
    # We check for a direct match first, then try matching the part after the last '/'.
    
    all_models = [
        model_info
        for provider in PRICING_DATA.get("providers", [])
        for model_info in provider.get("models", [])
    ]

    # First, try a direct match
    for model_info in all_models:
        if model_info.get("model_id") == model_id:
            return {
                "input": model_info["input_price_per_million_tokens"],
                "output": model_info["output_price_per_million_tokens"],
            }
            
    # If no direct match, try matching the last part of the ID
    simple_model_id = model_id.split('/')[-1]
    for model_info in all_models:
        if model_info.get("model_id") == simple_model_id:
            return {
                "input": model_info["input_price_per_million_tokens"],
                "output": model_info["output_price_per_million_tokens"],
            }
            
    return None