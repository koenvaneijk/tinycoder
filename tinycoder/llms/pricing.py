from typing import Dict, Optional, List, Any

PRICING_DATA: Dict[str, List[Dict[str, Any]]] = {
  "providers": [
    {
      "provider_name": "Google Gemini",
      "models": [
        {
          "model_id": "gemini-2.5-pro",
          "input_price_per_million_tokens": 1.25,
          "output_price_per_million_tokens": 10.00
        },
        {
          "model_id": "gemini-2.5-flash",
          "input_price_per_million_tokens": 0.30,
          "output_price_per_million_tokens": 2.50
        },
        {
          "model_id": "gemini-2.5-flash-lite",
          "input_price_per_million_tokens": 0.10,
          "output_price_per_million_tokens": 0.40
        }
      ]
    },
    {
      "provider_name": "Anthropic",
      "models": [
        {
          "model_id": "claude-opus-4.1",
          "input_price_per_million_tokens": 15.00,
          "output_price_per_million_tokens": 75.00
        },
        {
          "model_id": "claude-sonnet-4",
          "input_price_per_million_tokens": 3.00,
          "output_price_per_million_tokens": 15.00
        },
        {
          "model_id": "claude-haiku-3.5",
          "input_price_per_million_tokens": 0.80,
          "output_price_per_million_tokens": 4.00
        }
      ]
    },
    {
      "provider_name": "Together.ai",
      "models": [
        {
          "model_id": "llama-3.1-405b-instruct-turbo",
          "input_price_per_million_tokens": 3.50,
          "output_price_per_million_tokens": 3.50
        },
        {
          "model_id": "deepseek-r1",
          "input_price_per_million_tokens": 3.00,
          "output_price_per_million_tokens": 7.00
        },
        {
          "model_id": "qwen3-coder-480b-a35b-instruct",
          "input_price_per_million_tokens": 2.00,
          "output_price_per_million_tokens": 2.00
        }
      ]
    },
    {
      "provider_name": "Groq",
      "models": [
        {
          "model_id": "llama-4-maverick",
          "input_price_per_million_tokens": 0.20,
          "output_price_per_million_tokens": 0.60
        },
        {
          "model_id": "moonshotai/kimi-k2-instruct-0905",
          "input_price_per_million_tokens": 1.00,
          "output_price_per_million_tokens": 3.00
        },
        {
          "model_id": "llama-3-8b-8k",
          "input_price_per_million_tokens": 0.05,
          "output_price_per_million_tokens": 0.08
        }
      ]
    },
    {
      "provider_name": "OpenAI",
      "models": [
        {
          "model_id": "gpt-5",
          "input_price_per_million_tokens": 1.25,
          "output_price_per_million_tokens": 10.00
        },
        {
          "model_id": "gpt-5-mini",
          "input_price_per_million_tokens": 0.25,
          "output_price_per_million_tokens": 2.00
        },
        {
          "model_id": "gpt-5-nano",
          "input_price_per_million_tokens": 0.05,
          "output_price_per_million_tokens": 0.40
        }
      ]
    },
    {
      "provider_name": "DeepSeek",
      "models": [
        {
          "model_id": "deepseek-chat",
          "input_price_per_million_tokens": 0.56,
          "output_price_per_million_tokens": 1.68
        },
        {
          "model_id": "deepseek-reasoner",
          "input_price_per_million_tokens": 3.00,
          "output_price_per_million_tokens": 7.00
        }
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