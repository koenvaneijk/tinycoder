

# <p align="center">✨ tinycoder ✨</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.8+-blue.svg" alt="Python Version">
  <img src="https://img.shields.io/badge/license-AGPLv3-green.svg" alt="License">
  <img src="https://img.shields.io/github/last-commit/koenvaneijk/tinycoder" alt="Last Commit">
</p>

<p align="center">
  <strong>Your command-line AI coding assistant 🤖 integrated with Git! Pure Python, zero dependencies.</strong>
</p>

TinyCoder is a Python-based tool designed to help you interact with Large Language Models (LLMs) for coding tasks directly within your terminal. It analyzes your codebase, builds context for the LLM, applies suggested code changes safely, and integrates seamlessly with your Git workflow. Minimal dependencies, maximum productivity!

![TinyCoder Demo](https://github.com/koenvaneijk/tinycoder/blob/main/screenshots/demo.gif?raw=true)


## 🚀 Key Features

*   **💻 Command-Line Interface:** Smooth terminal interaction with multiline input and potential path autocompletion.
*   **🧠 Intelligent Context Building:**
    *   **File Management:** Easily add/remove files (`/add`, `/drop`, `/files`).
    *   **Automatic File Identification:** Suggests relevant files to add to the context based on your request (`/ask` for files feature).
    *   **Repo Map:** Generates a high-level codebase map (`RepoMap`) for broader LLM understanding. Controlled via `/repomap [on|off]`.
    *   **Smart Prompts:** Constructs detailed prompts using file content and repo structure (`PromptBuilder`).
*   **🤖 Multiple LLM Support:** Works with **Google Gemini**, **DeepSeek**, **Anthropic**, **Together AI**, and **Ollama**. Configure via `--provider` and `--model` flags, or environment variables (`GEMINI_API_KEY`, `DEEPSEEK_API_KEY`, `ANTHROPIC_API_KEY`, `TOGETHER_API_KEY`).
*   **✏️ Safe Code Editing:**
    *   Parses LLM responses using a structured XML format (`EditParser`).
    *   Applies changes with user confirmation and diff previews (`CodeApplier`).
    *   Handles file creation and modification reliably.
    *   **Linting & Reflection:** Automatically lints applied code and prompts user to let the LLM fix errors.
*   **🔄 Modes of Operation:** Switch between `code` mode (for edits) and `ask` mode (for questions) using `/code` and `/ask`.
*   **🌿 Git Integration:**
    *   Initializes Git repo if needed (`GitManager`).
    *   Commits changes applied by the last successful LLM edit (`/commit`).
    *   Rolls back the last TinyCoder commit (`/undo`).
*   **✅ Linters & Validation:** Includes built-in linters for **Python**, **HTML**, and **CSS** to catch issues *after* applying edits, with an option to auto-fix.
*   **📜 Rules Engine:**
    *   Define project-specific coding standards (e.g., `style_guide.md`) in `.tinycoder/rules/` (custom) or use built-in rules.
    *   Manage active rules per-project using `/rules list|enable|disable`.
    *   Configuration stored in the user's standard application config directory.
*   **🧪 Test Runner:** Execute project tests (like `pytest`) using the `/tests` command (`test_runner.py`).
*   **💾 Chat History:** Persists conversations to `.tinycoder_history` in the user's standard application data directory (`ChatHistoryManager`) and allows resuming with `--continue-chat`.
*   **⚙️ Command Handling:** Rich set of commands for session control (`CommandHandler`).
*   **🐚 Shell Execution:** Run shell commands directly using `!<command>`. Output can optionally be added to the chat context.
*   **📝 Built-in Text Editor:** A simple, integrated text editor (`/edit <filename>`) for quick modifications with features like:
    *   Syntax highlighting (Python).
    *   Line numbers and status bar.
    *   Basic editing: insert, delete, tab, enter with auto-indent.
    *   Navigation: arrows, Home/End, PageUp/PageDown.
    *   Find functionality (Ctrl+F, F3 for next).
    *   File saving (Ctrl+S) and quitting (Ctrl+Q) with unsaved changes confirmation.
    *   Mouse support for cursor placement.

---

## 🛠️ Installation

**Requirements:** Python 3.8+

**Option 1: Install directly from GitHub**

```bash
python3 -m pip install git+https://github.com/koenvaneijk/tinycoder.git
```

**Option 2: Clone and install locally**

```bash
# 1. Clone the repository
git clone https://github.com/koenvaneijk/tinycoder.git
cd tinycoder

# 2. Install (choose one)
#    Editable mode (for development)
python3 -m pip install -e .
#    Standard install
# python3 -m pip install .
```

**🔑 API Keys:**

*   Set the required environment variables for your chosen cloud LLM provider:
    *   Gemini: `GEMINI_API_KEY`
    *   DeepSeek: `DEEPSEEK_API_KEY`
    *   Anthropic: `ANTHROPIC_API_KEY`
    *   Together AI: `TOGETHER_API_KEY`
*   Ollama runs locally and does not require an API key.
*   You can also set `OLLAMA_HOST` if your Ollama instance is not at the default `http://localhost:11434`.

---

## ▶️ Usage

**Start TinyCoder in your project's root directory:**

You can specify the LLM provider and model:

```bash
# Use the default model for a specific provider
tinycoder --provider gemini # Uses default Gemini model
tinycoder --provider anthropic # Uses default Anthropic model
tinycoder --provider together # Uses default Together AI model
tinycoder --provider ollama # Uses default Ollama model (e.g., qwen3:14b)

# Specify both provider and model name (no prefix needed on model)
tinycoder --provider gemini --model gemini-1.5-flash
tinycoder --provider deepseek --model deepseek-coder
tinycoder --provider ollama --model llama3
tinycoder --provider anthropic --model claude-3-sonnet-20240229

# If --provider is omitted, --model assumes Ollama or uses legacy prefixes
tinycoder --model llama3 # Assumes Ollama provider
tinycoder --model gemini-1.5-pro # Uses legacy prefix detection
tinycoder --model deepseek-coder # Uses legacy prefix detection
# tinycoder --model my-custom-ollama-model # Assumes Ollama provider

# Use the legacy flag (still supported)
tinycoder --legacy-model gemini-1.5-flash

# Load the last used model from user preferences (default behavior if no flags)
tinycoder

# Override Ollama host if not default
export OLLAMA_HOST="http://my-ollama-server:11434"
tinycoder --provider ollama --model mistral

# Start with initial files and an instruction
tinycoder --provider gemini src/main.py src/utils.py "Refactor the main loop in main.py"

# Continue the last chat session
tinycoder --continue-chat

# Run non-interactively (applies changes and exits)
tinycoder --code "Implement the function foo in service.py using utils.bar"
```

**Quick Command Reference:**

*   `/add <file1> ["file 2"]...`: Add file(s) to the chat context.
*   `/drop <file1> ["file 2"]...`: Remove file(s) from the chat context.
*   `/files`: List files currently in the chat.
*   `/suggest_files [instruction]`: Ask the LLM to suggest relevant files. Uses last user message if no instruction.
*   `/edit <filename>`: Open the specified file in a built-in text editor.
*   `/ask`: Switch to ASK mode (answer questions, no edits).
*   `/code`: Switch to CODE mode (make edits).
*   `/commit`: Commit the changes applied by the last successful LLM edit.
*   `/undo`: Revert the last TinyCoder commit.
*   `/tests`: Run project tests (e.g., `pytest` in `./tests`).
*   `/rules list`: List available rules and their status for the project.
*   `/rules enable <rule_name>`: Enable a specific rule.
*   `/rules disable <rule_name>`: Disable a specific rule.
*   `/repomap [on|off|show]`: Enable, disable, or show the inclusion of the repository map in prompts.
*   `/clear`: Clear the chat history.
*   `/reset`: Clear history and remove all files from context.
*   `/help`: Show help message.
*   `/quit` or `/exit` or `Ctrl+C`/`Ctrl+D`: Exit.
*   `!<command>`: Execute a shell command. You'll be prompted to add the output to the chat.

---

## 🤝 Contributing

Contributions are welcome! Please read the `CONTRIBUTING.md` file (if it exists) for guidelines. (Placeholder - create this file if needed)

---

## 📜 License

This project is licensed under the AGPLv3+ License. If you need a different license, please contact me at vaneijk.koen@gmail.com.

---

## 🙏 Credits

TinyCoder draws inspiration and ideas from the excellent [Aider.Chat](https://aider.chat/) project. 