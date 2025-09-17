from tinycoder.app_builder import AppBuilder
import os
import argparse
import asyncio
import importlib.metadata

from tinycoder.preferences import save_user_preference, load_user_preference_model, load_user_preferences
from tinycoder.ui.log_formatter import COLORS, RESET

from typing import Optional

APP_NAME = "tinycoder"
try:
    __version__ = importlib.metadata.version(APP_NAME)
except importlib.metadata.PackageNotFoundError:
    __version__ = "dev"

def main():
    # Get default provider and model from environment variables
    default_provider = os.environ.get("TINYCODER_PROVIDER", None)
    default_model = os.environ.get("TINYCODER_MODEL", None)
    
    parser = argparse.ArgumentParser(
        description=f"{APP_NAME} - A simplified AI coding assistant."
    )
    parser.add_argument(
        "files",
        metavar="FILE",
        nargs="*",
        help="Files to add to the chat context on startup.",
    )
    
    # New provider selection argument
    parser.add_argument(
        "--provider",
        choices=["anthropic", "gemini", "ollama", "together", "deepseek", "groq", "openai", "xai"],
        default=default_provider,
        help="The LLM provider to use (default: auto-detected or from TINYCODER_PROVIDER env var)",
    )
    
    parser.add_argument(
        "--model",
        metavar="MODEL_NAME",
        default=default_model,
        help=(
            "Specific model name within the selected provider. "
            "Provider-specific model without needing prefixes. "
            "Default is provider-specific or from TINYCODER_MODEL env var."
        ),
    )
    
    parser.add_argument(
        "--code",
        metavar="INSTRUCTION",
        default=None,
        help="Execute a code command directly without interactive mode. Applies edits and commits changes.",
    )
    
    parser.add_argument(
        "--continue-chat",
        action="store_true",
        help="Continue from previous chat history instead of starting fresh.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose output (DEBUG level logging).",
    )
    
    args = parser.parse_args()

    # Resolve model string based on provider/model inputs and preferences
    model_str = None
    
    if args.provider:
        # Convert provider + model to the prefix format the backend expects
        if args.provider == "anthropic":
            model_name = args.model or "claude-3-7-sonnet-20250219"
            model_str = model_name if model_name.startswith("claude-") else f"claude-{model_name}"
        elif args.provider == "gemini":
            model_name = args.model or "gemini-2.5-pro"
            model_str = model_name if model_name.startswith("gemini-") else f"gemini-{model_name}"
        elif args.provider == "deepseek":
            model_name = args.model or "deepseek-reasoner"
            model_str = model_name if model_name.startswith("deepseek-") else f"deepseek-{model_name}"
        elif args.provider == "together":
            model_name = args.model or "Qwen/Qwen3-235B-A22B-fp8-tput"
            model_str = f"together-{model_name}"
        elif args.provider == "groq":
            model_name = args.model or "moonshotai/kimi-k2-instruct-0905"
            model_str = f"groq-{model_name}"
        elif args.provider == "xai":
            model_name = args.model or "grok-code-fast-1"
            model_str = model_name if (model_name.startswith("grok-") or model_name.startswith("xai-")) else f"xai-{model_name}"
        elif args.provider == "ollama":
            model_str = args.model or "qwen3:14b"
        elif args.provider == "openai":
            model_name = args.model or "gpt-5"
            model_str = model_name
    elif args.model:
        # If no provider specified but model is, assume Ollama
        model_str = args.model
    
    if model_str is None:
        model_str = load_user_preference_model()

    # Infer provider for display
    def _infer_provider_from_model(m: Optional[str]) -> Optional[str]:
        if not m:
            return None
        ml = m.lower()
        if ml.startswith("claude-"):
            return "anthropic"
        for p in ("groq", "together", "gemini", "deepseek", "xai"):
            if ml.startswith(p + "-"):
                return p
        if ml.startswith("grok-"):
            return "xai"
        if ":" in m and "/" not in m and " " not in m:
            return "ollama"
        return None

    provider_display = None
    if args.provider:
        provider_display = args.provider
    elif default_provider:
        provider_display = default_provider
    else:
        # Try preferences
        try:
            prefs = load_user_preferences()
            mi = prefs.get("model")
            if isinstance(mi, dict):
                provider_display = mi.get("provider")
            elif isinstance(mi, str):
                provider_display = _infer_provider_from_model(mi)
        except Exception:
            provider_display = None

    if not provider_display and model_str:
        provider_display = _infer_provider_from_model(model_str)
    if not provider_display and args.model and not args.provider:
        provider_display = "ollama"
    provider_display = provider_display or "auto"

    # Render Tinycoder ASCII, version and provider
    ascii_art_lines = [
        r"  _   _                     _         ",
        r" | |_(_)_ _ _  _ __ ___  __| |___ _ _ ",
        r" |  _| | ' \ || / _/ _ \/ _` / -_) '_|",
        r"  \__|_|_||_\_, \__\___/\__,_\___|_|  ",
        r"            |__/                      "
    ]

    gradient_colors = [
        COLORS.get("BRIGHT_CYAN", ""),
        COLORS.get("CYAN", ""),
        COLORS.get("BLUE", ""),
        COLORS.get("MAGENTA", ""),
        COLORS.get("BRIGHT_MAGENTA", "") 
    ]

    for i, line in enumerate(ascii_art_lines):
        color = gradient_colors[i % len(gradient_colors)]  # Cycle through colors
        print(f"{color}{line}{RESET}")

    art_width = max(len(line) for line in ascii_art_lines)
    version_color = COLORS.get("YELLOW", "")
    version_str = f"v{__version__}"
    print(f"{version_color}{version_str: >{art_width}}{RESET}")

    print()  # Extra newline for spacing after the art

    # Initialize the app
    builder = AppBuilder(model=model_str, provider=args.provider, files=args.files, continue_chat=args.continue_chat, verbose=args.verbose)
    coder = builder.build()

    # Save the model preference for next time
    # save_user_preference(coder.client.__class__.__name__, coder.model)

    if args.code:
        coder.mode = "code"
        asyncio.run(coder.run_one(args.code, preproc=False, non_interactive=True))
    else:
        asyncio.run(coder.run())

if __name__ == "__main__":
    main()
