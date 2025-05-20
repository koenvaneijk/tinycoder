from tinycoder.app import App
import os
import argparse

from tinycoder.preferences import save_user_preference, load_user_preference_model
from tinycoder.ui.log_formatter import COLORS, RESET

APP_NAME = "tinycoder"

def main():
    ascii_art_lines = [
        r"  _   _                     _         ",
        r" | |_(_)_ _ _  _ __ ___  __| |___ _ _ ",
        r" |  _| | ' \ || / _/ _ \/ _` / -_) '_|",
        r"  \__|_|_||_\_, \__\___/\__,_\___|_|  ",
        r"            |__/                      "
    ]

    # Define a color sequence for the gradient
    gradient_colors = [
        COLORS.get("BRIGHT_CYAN", ""),
        COLORS.get("CYAN", ""),
        COLORS.get("BLUE", ""),
        COLORS.get("MAGENTA", ""),
        COLORS.get("BRIGHT_MAGENTA", "") 
    ]

    for i, line in enumerate(ascii_art_lines):
        color = gradient_colors[i % len(gradient_colors)] # Cycle through colors
        print(f"{color}{line}{RESET}")
    print() # Add an extra newline for spacing after the art

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
        choices=["anthropic", "gemini", "ollama", "together", "deepseek"],
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

    model_str = None
    
    # Otherwise use provider + model combination
    if args.provider:
        # Convert provider + model to the prefix format the backend expects
        if args.provider == "anthropic":
            model_name = args.model or "claude-3-7-sonnet-20250219"
            if not model_name.startswith("claude-"):
                model_str = f"claude-{model_name}"
            else:
                model_str = model_name
        elif args.provider == "gemini":
            model_name = args.model or "gemini-2.5-pro-preview-05-06"
            if not model_name.startswith("gemini-"):
                model_str = f"gemini-{model_name}"
            else:
                model_str = model_name
        elif args.provider == "deepseek":
            model_name = args.model or "deepseek-coder"
            if not model_name.startswith("deepseek-"):
                model_str = f"deepseek-{model_name}"
            else:
                model_str = model_name
        elif args.provider == "together":
            model_name = args.model or "Qwen/Qwen3-235B-A22B-fp8-tput"
            model_str = f"together-{model_name}"
        elif args.provider == "ollama":
            model_str = args.model or "qwen3:14b"
    
    # If no provider specified but model is, assume Ollama
    elif args.model:
        model_str = args.model
    
    # Load user preferences if nothing specified on command line
    if model_str is None:
        model_str = load_user_preference_model()

    # Initialize the app
    coder = App(model=model_str, files=args.files, continue_chat=args.continue_chat, verbose=args.verbose)

    # Save the model preference for next time
    save_user_preference(coder.client.__class__.__name__, coder.model)

    if args.code:
        coder.mode = "code"
        coder.run_one(args.code, preproc=False, non_interactive=True)
    else:
        coder.run()

if __name__ == "__main__":
    main()
