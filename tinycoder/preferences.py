import json
import logging
import os
import platform
from pathlib import Path
from typing import Dict, Any, Optional

# APP_NAME is defined here for self-containment of preference logic.
# It should match the APP_NAME in tinycoder/__init__.py.
APP_NAME = "tinycoder"
USER_PREFS_FILE = "user_preferences.json"


def get_user_prefs_path() -> Path:
    """Returns the path to the user preferences file."""
    if platform.system() == "Windows":
        config_dir = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / APP_NAME
    elif platform.system() == "Darwin":  # macOS
        config_dir = Path.home() / "Library" / "Application Support" / APP_NAME
    else:  # Linux and other Unix-like systems
        config_dir = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / APP_NAME
    
    # Ensure directory exists
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir / USER_PREFS_FILE

def load_user_preferences() -> Dict[str, Any]:
    """Loads user preferences from the JSON file."""
    prefs_path = get_user_prefs_path()
    if not prefs_path.exists():
        return {}
    
    try:
        with open(prefs_path, "r", encoding="utf-8") as f:
            prefs = json.load(f)
            if not isinstance(prefs, dict):
                logging.warning(f"Invalid format in {prefs_path}. Expected a JSON object. Ignoring preferences.")
                return {}
            return prefs
    except json.JSONDecodeError:
        logging.warning(f"Error decoding JSON from {prefs_path}. Ignoring preferences.")
        return {}
    except Exception as e:
        logging.warning(f"Failed to read preferences from {prefs_path}: {e}")
        return {}

def save_user_preferences(prefs: Dict[str, Any]) -> bool:
    """Saves user preferences to the JSON file."""
    prefs_path = get_user_prefs_path()
    try:
        with open(prefs_path, "w", encoding="utf-8") as f:
            json.dump(prefs, f, indent=2)
        return True
    except Exception as e:
        logging.warning(f"Failed to save preferences to {prefs_path}: {e}")
        return False

def load_user_preference_model() -> Optional[str]:
    """Loads the last used model preference."""
    prefs = load_user_preferences()
    model_info = prefs.get("model")
    
    if not model_info:
        return None
        
    # If it's just a string, return it directly
    if isinstance(model_info, str):
        return model_info
        
    # If it's a dict with provider-specific format
    if isinstance(model_info, dict):
        provider = model_info.get("provider")
        name = model_info.get("name")
        
        if not provider or not name:
            return None
            
        # Format based on provider
        if provider == "anthropic" and not name.startswith("claude-"):
            return f"claude-{name}"
        elif provider == "gemini" and not name.startswith("gemini-"):
            return f"gemini-{name}"
        elif provider == "deepseek" and not name.startswith("deepseek-"):
            return f"deepseek-{name}" 
        elif provider == "together":
            return f"together-{name}"
        else:
            return name  # For ollama or other formats
            
    return None

def save_user_preference(provider_class: str, model_name: str) -> None:
    """Saves the current model preference for future use."""
    if not model_name:
        return
        
    prefs = load_user_preferences()
    
    # Store in normalized format to help with future flexibility
    provider_mapping = {
        "AnthropicClient": "anthropic",
        "GeminiClient": "gemini", 
        "TogetherAIClient": "together",
        "DeepSeekClient": "deepseek",
        "OllamaClient": "ollama"
    }
    
    provider = provider_mapping.get(provider_class)
    
    if provider:
        # Strip provider prefix if present
        name = model_name
        if provider == "anthropic" and name.startswith("claude-"):
            name = name[7:]  # Remove "claude-" prefix
        elif provider == "gemini" and name.startswith("gemini-"):
            name = name[7:]  # Remove "gemini-" prefix
        elif provider == "deepseek" and name.startswith("deepseek-"):
            name = name[9:]  # Remove "deepseek-" prefix
        elif provider == "together" and name.startswith("together-"):
            name = name[9:]  # Remove "together-" prefix
            
        # Store in structured format for flexibility
        prefs["model"] = {
            "provider": provider,
            "name": name,
            "full_name": model_name  # Keep original for reference
        }
    else:
        # If provider not recognized, just store the raw model string
        prefs["model"] = model_name
        
    save_user_preferences(prefs)