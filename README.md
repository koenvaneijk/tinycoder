

# <p align="center">✨ tinycoder ✨</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.8+-blue.svg" alt="Python Version">
  <img src="https://img.shields.io/badge/license-AGPLv3-green.svg" alt="License">
  <img src="https://img.shields.io/github/last-commit/koenvaneijk/tinycoder" alt="Last Commit">
  <a href="#-using-on-android-termux"><img src="https://img.shields.io/badge/Android-Termux-brightgreen" alt="Runs on Termux"></a>
</p>

<p align="center">
  <strong>Your command-line AI coding assistant 🤖 integrated with Git! Pure Python, zero dependencies.</strong>
</p>

TinyCoder is a Python-based tool designed to help you interact with Large Language Models (LLMs) for coding tasks directly within your terminal. It analyzes your codebase, builds context for the LLM, applies suggested code changes safely, and integrates seamlessly with your Git workflow. Minimal dependencies, maximum productivity!

![TinyCoder Demo](https://github.com/koenvaneijk/tinycoder/blob/main/screenshots/demo.gif?raw=true)


## 🚀 Key Features

*   **💻 Command-Line Interface:** Smooth terminal interaction with multiline input and potential path autocompletion.
*   **📓 Jupyter Notebook Support:** Read, edit, and write `.ipynb` files. Notebooks are automatically converted to a plain Python representation for the LLM and converted back to `.ipynb` format upon saving.
*   **🧠 Intelligent Context Building:**
    *   **File Management:** Easily add/remove files (`/add`, `/drop`, `/files`).
    *   **Automatic File Identification:** Suggests relevant files to add to the context based on your request (`/ask` for files feature).
    *   **Repo Map:** Generates a high-level codebase map (`RepoMap`) for broader LLM understanding. Controlled via `/repomap [on|off|show]`.
    *   **Customizable Repo Map Exclusions:** Fine-tune the `RepoMap` by adding or removing exclusion patterns for files/directories via `/repomap exclude add|remove|list`.
    *   **Code Snippet Context:** Quickly add specific functions or classes to the context using `@path/to/file.py::EntityName` syntax in your prompts (e.g., `@app.py::MyClass`).
    *   **Smart Prompts:** Constructs detailed prompts using file content and repo structure (`PromptBuilder`).
*   **🤖 Multiple LLM Support:** Works with **Google Gemini**, **DeepSeek**, **Anthropic**, **Together AI**, **Groq**, and **Ollama**. Configure via `--provider` and `--model` flags, or environment variables (`GEMINI_API_KEY`, `DEEPSEEK_API_KEY`, `ANTHROPIC_API_KEY`, `TOGETHER_API_KEY`, `GROQ_API_KEY`).
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
*   **🧪 Test Runner:** Execute project unit tests (using Python's `unittest` framework) using the `/tests` command (`test_runner.py`).
*   **💾 Chat History:** Persists conversations to `tinycoder_chat_history.md` in a `tinycoder` subdirectory within your user's standard application data directory (location varies by OS, e.g., `~/.local/share/tinycoder/` on Linux) (`ChatHistoryManager`) and allows resuming with `--continue-chat`.
*   **🐳 Docker Integration (Experimental):**
    *   Helps manage Docker workflows alongside coding changes.
    *   Can identify affected Docker services based on modified files if a `docker-compose.yml` is present.
    *   Prompts to rebuild or restart services if live-reload isn't detected (requires Docker and `docker-compose`).
    *   Provides commands like `/docker ps`, `/docker logs <service>`, `/docker restart <service>`, `/docker build <service>`, and `/docker exec <service> <command>`.
    *   Warns about files in context that might not be covered by Docker volume mounts.
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

**Recommended: Install from PyPI**
The easiest way to install TinyCoder is from PyPI:
```bash
pip install tinycoder
```

**Alternative: Install from GitHub (latest version)**
To get the very latest changes, you can install directly from the repository:
```bash
pip install git+https://github.com/koenvaneijk/tinycoder.git
```

**For Development: Clone and Install Locally**
If you want to contribute to TinyCoder, you can clone the repository and install it in editable mode:
```bash
# 1. Clone the repository
git clone https://github.com/koenvaneijk/tinycoder.git
cd tinycoder

# 2. Install in editable mode
pip install -e .
```

**🔑 API Keys:**

*   Set the required environment variables for your chosen cloud LLM provider:
    *   Gemini: `GEMINI_API_KEY`
    *   DeepSeek: `DEEPSEEK_API_KEY`
    *   Anthropic: `ANTHROPIC_API_KEY`
    *   Together AI: `TOGETHER_API_KEY`
    *   Groq: `GROQ_API_KEY`
*   Ollama runs locally and does not require an API key.
*   You can also set `OLLAMA_HOST` if your Ollama instance is not at the default `http://localhost:11434`.

---

### 📱 Using on Android (Termux)

TinyCoder runs effectively on Android devices using the [Termux](https://termux.dev/en/) terminal emulator, allowing you to have a powerful AI coding assistant in your pocket.

**1. Prerequisites**

*   Install the **Termux** application from [F-Droid](https://f-droid.org/en/packages/com.termux/). The version on the Google Play Store is deprecated and will not work correctly.

**2. Installation Steps in Termux**

*   First, open Termux and ensure its packages are up-to-date:
    ```bash
    pkg update && pkg upgrade
    ```
*   Install the necessary dependencies, `python` and `git`:
    ```bash
    pkg install python git
    ```
*   Install `tinycoder` from PyPI:
    ```bash
    pip install tinycoder
    ```

**3. Configuration**

*   You'll need to set your LLM API key as an environment variable. A common way to do this is to add it to your shell's startup file (e.g., `~/.bashrc`):
    ```bash
    # Replace with your actual key and provider variable
    echo 'export GEMINI_API_KEY="YOUR_API_KEY_HERE"' >> ~/.bashrc
    
    # Reload the shell configuration
    source ~/.bashrc
    ```
*   You can now use `tinycoder` as you would on a desktop system.

---

## ▶️ Usage

**Start TinyCoder in your project's root directory:**

You can specify the LLM provider and model:

```bash
# Use the default model for a specific provider
tinycoder --provider gemini # Uses default Gemini model
tinycoder --provider anthropic # Uses default Anthropic model
tinycoder --provider together # Uses default Together AI model
tinycoder --provider groq # Uses default Groq model
tinycoder --provider ollama # Uses default Ollama model (e.g., qwen3:14b)

# Specify both provider and model name (no prefix needed on model)
tinycoder --provider gemini --model gemini-1.5-flash
tinycoder --provider deepseek --model deepseek-reasoner
tinycoder --provider ollama --model llama3
tinycoder --provider anthropic --model claude-3-sonnet-20240229
tinycoder --provider groq --model llama3-8b-8192

# If --provider is omitted, --model assumes Ollama or uses legacy prefixes
tinycoder --model llama3 # Assumes Ollama provider
tinycoder --model gemini-2.5-pro # Uses legacy prefix detection
tinycoder --model deepseek-reasoner # Uses legacy prefix detection
tinycoder --model groq-llama3-8b-8192 # Uses legacy prefix detection
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
*   **Pro Tip for Context:** Use `@path/to/file.py::EntityName` (e.g., `@src/utils.py::helper_function`) in your messages to include specific code snippets directly.
*   `/edit <filename>`: Open the specified file in a built-in text editor.
*   `/ask`: Switch to ASK mode (answer questions, no edits).
*   `/code`: Switch to CODE mode (make edits).
*   `/commit`: Commit the changes applied by the last successful LLM edit.
*   `/undo`: Revert the last TinyCoder commit.
*   `/tests`: Run project unit tests (using Python's `unittest` framework in `./tests`).
*   `/rules list`: List available rules and their status for the project.
*   `/rules enable <rule_name>`: Enable a specific rule.
*   `/rules disable <rule_name>`: Disable a specific rule.
*   `/repomap [on|off|show]`: Enable, disable, or show the inclusion of the repository map in prompts.
*   `/repomap exclude add <pattern>`: Add a file/directory pattern to exclude from RepoMap.
*   `/repomap exclude remove <pattern>`: Remove an exclusion pattern.
*   `/repomap exclude list`: List current exclusion patterns.
*   `/docker ps`: Show status of docker-compose services.
*   `/docker logs <service_name>`: Stream logs for a service.
*   `/docker restart <service_name>`: Restart a service.
*   `/docker build <service_name>`: Build a service.
*   `/docker exec <service_name> <command...>`: Execute a command in a service container.
*   `/clear`: Clear the chat history.
*   `/reset`: Clear history and remove all files from context.
*   `/help`: Show help message.
*   `/quit` or `/exit` or `Ctrl+C`/`Ctrl+D`: Exit.
*   `!<command>`: Execute a shell command. You'll be prompted to add the output to the chat.

---

## 🤝 Contributing

Contributions are welcome! Please read the `CONTRIBUTING.md` file (if it exists) for guidelines. (Placeholder - create this file if needed)

---

## 💼 Commercial Use & Professional Services

While TinyCoder is provided under the AGPLv3+ license for open-source use, I understand that this may not be suitable for all business needs. I offer professional services and alternative licensing for commercial applications.

Please feel free to contact me at **vaneijk.koen@gmail.com** for inquiries related to:

*   **Commercial Licensing:** If you need to integrate TinyCoder into a proprietary product or require a license without the obligations of AGPLv3.
*   **Paid Feature Development:** If you would like to sponsor the development of specific features or customizations tailored to your workflow.
*   **Integration Support:** If you require expert assistance in embedding TinyCoder into your company's systems or development environment.

I am happy to discuss how TinyCoder can best serve your business needs.

---

## 📜 License

This project is licensed under the AGPLv3+ License.

---

## 🙏 Credits

TinyCoder draws inspiration and ideas from the excellent [Aider.Chat](https://aider.chat/) project. 