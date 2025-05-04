

# <p align="center">✨ TinyCoder ✨</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.8+-blue.svg" alt="Python Version">
  <img src="https://img.shields.io/badge/license-AGPLv2-green.svg" alt="License"> <!-- Assuming MIT, change if needed -->
  <img src="https://img.shields.io/github/last-commit/koenvaneijk/tinycoder" alt="Last Commit">
</p>

<p align="center">
  <strong>Your command-line AI coding assistant 🤖 integrated with Git!</strong>
</p>

TinyCoder is a Python-based tool designed to help you interact with Large Language Models (LLMs) for coding tasks directly within your terminal. It analyzes your codebase, builds context for the LLM, applies suggested code changes safely, and integrates seamlessly with your Git workflow. Minimal dependencies, maximum productivity!

![TinyCoder Screenshot](https://raw.githubusercontent.com/koenvaneijk/tinycoder/main/screenshots/image.png)

## 🚀 Key Features

*   **💻 Command-Line Interface:** Smooth terminal interaction with multiline input and potential path autocompletion.
*   **🧠 Intelligent Context Building:**
    *   **File Management:** Easily add/remove files (`/add`, `/drop`, `/files`) or mention them in prompts.
    *   **Repo Map:** Generates a high-level codebase map (`RepoMap`) for broader LLM understanding.
    *   **Smart Prompts:** Constructs detailed prompts using file content and repo structure (`PromptBuilder`).
*   **🤖 Multiple LLM Support:** Works with **Google Gemini**, **DeepSeek**, and **Ollama**. Configure via `--model` flag and environment variables (`GEMINI_API_KEY`, `DEEPSEEK_API_KEY`).
*   **✏️ Safe Code Editing:**
    *   Parses LLM responses using a structured XML format (`EditParser`).
    *   Applies changes with user confirmation and diff previews (`CodeApplier`).
    *   Handles file creation and modification reliably.
*   **🔄 Modes of Operation:** Switch between `code` mode (for edits) and `ask` mode (for questions) using `/code`, `/ask`, or `/mode`.
*   **🌿 Git Integration:**
    *   Initializes Git repo if needed (`GitManager`).
    *   Commits applied changes (`/commit [files]`).
    *   Rolls back the last TinyCoder commit (`/undo`).
*   **✅ Linters & Validation:** Includes built-in linters for **Python**, **HTML**, and **CSS** to catch issues before applying edits.
*   **📜 Rules Engine:** Define project-specific coding standards (e.g., `style_guide.md`) in `.tinycoder/rules/` and manage them with `/rules`, `/enable`, `/disable`.
*   **🧪 Test Runner:** Execute project tests (like `pytest`) using the `/test` command (`test_runner.py`).
*   **💾 Chat History:** Persists conversations to `.tinycoder.chat.history.md` (`ChatHistoryManager`) and allows resuming with `--continue`.
*   **⚙️ Command Handling:** Rich set of commands for session control (`CommandHandler`).

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

*   Set the required environment variables for your chosen LLM:
    *   Gemini: `GEMINI_API_KEY`
    *   DeepSeek: `DEEPSEEK_API_KEY`
*   Ollama typically runs locally and may not require a key.

---

## ▶️ Usage

**Start TinyCoder in your project's root directory:**

```bash
# Use default LLM (see code/config for the default)
tinycoder

# Specify an LLM model
tinycoder --model ollama/llama3

# Start with initial files and an instruction
tinycoder src/main.py src/utils.py "Refactor the main loop in main.py"

# Continue the last chat session
tinycoder --continue
```

**Example Interaction Flow:**

```plaintext
(code) >>> /add src/parser.py
Added src/parser.py to chat context. (1 file total)

(code) >>> Please add robust error handling to the parse_line function in src/parser.py using try-except blocks.
Okay, I will add error handling to the `parse_line` function in `src/parser.py`.

<file path="./src/parser.py">
<edit_block>
<old_code>
def parse_line(line):
    # Current implementation
    parts = line.split(',')
    return parts[0], int(parts[1])
</old_code>
<new_code>
import logging

def parse_line(line):
    """Parses a line, handling potential errors."""
    try:
        parts = line.strip().split(',')
        if len(parts) != 2:
            logging.warning(f"Skipping malformed line: {line}")
            return None, None
        return parts[0], int(parts[1])
    except ValueError:
        logging.warning(f"Skipping line with invalid number: {line}")
        return None, None
    except Exception as e:
        logging.error(f"Unexpected error parsing line '{line}': {e}")
        return None, None
</new_code>
</edit_block>
</file>

--- DIFF ---
... (diff output shown here) ...
--- END DIFF ---
Applying edits...
File ./src/parser.py updated successfully.
Successfully applied 1 edit.
(code) >>> /commit
Committed changes to 1 file with message: Applied AI edit to src/parser.py
```

**Quick Command Reference:**

*   `/add <file>` / `/drop <file>`: Manage files in context.
*   `/files`: List context files.
*   `/ask` / `/code` / `/mode [ask|code]`: Change interaction mode.
*   `/commit [files...]`: Commit applied changes.
*   `/undo`: Revert last TinyCoder commit.
*   `/test`: Run project tests.
*   `/rules` / `/enable <rule>` / `/disable <rule>`: Manage coding rules.
*   `/quit` or `Ctrl+C`: Exit.

---

## 🤝 Contributing

Contributions are welcome! Please read the `CONTRIBUTING.md` file (if it exists) for guidelines. (Placeholder - create this file if needed)

---

## 📜 License

This project is licensed under the AGPLv2 License. If you need a different license, please contact me at vaneijk.koen@gmail.com.

---

## 🙏 Credits

TinyCoder draws inspiration and ideas from the excellent [Aider.Chat](https://aider.chat/) project. 