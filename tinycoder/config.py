import os
import platform
from pathlib import Path

APP_NAME = "tinycoder"
COMMIT_PREFIX = "🤖 tinycoder: "
HISTORY_FILE_NAME = ".tinycoder_history"

def get_config_dir() -> Path:
    """Gets the application's configuration directory based on OS."""
    if platform.system() == "Windows":
        return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / APP_NAME
    elif platform.system() == "Darwin":  # macOS
        return Path.home() / "Library" / "Application Support" / APP_NAME
    else:  # Linux and other Unix-like systems
        return Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / APP_NAME

def get_history_file_path() -> Path:
    """Gets the path to the prompt history file."""
    # Using a platform-agnostic data directory location
    hist_dir = Path.home() / ".local" / "share" / APP_NAME
    hist_dir.mkdir(parents=True, exist_ok=True)
    return hist_dir / HISTORY_FILE_NAME