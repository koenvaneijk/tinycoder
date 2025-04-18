# TinyCoder

TinyCoder is a zero dependencies, pure Python, simplified, command-line AI coding assistant designed to help you interact with Large Language Models (LLMs) for coding tasks directly within your terminal and integrated with your Git workflow.

It allows you to add .py files to a chat context, ask questions, request code changes, and have the assistant apply those changes using a specific diff-like format.

## Features

*   **Command-Line Interface:** Interact with the AI assistant entirely through your terminal.
*   **File Context Management:** Add and remove files (`/add`, `/drop`, `/files`) to provide relevant context to the LLM.
*   **Multiple LLM Support:** Currently supports Google Gemini and DeepSeek models. Specify the model using the `--model` flag (e.g., `gemini-1.5-pro-latest`, `deepseek-chat`). Defaults to Gemini if unspecified.
*   **Code Editing:** In `code` mode (default), the assistant attempts to apply requested changes using `SEARCH/REPLACE` blocks within fenced code blocks.
*   **Question Answering:** Switch to `ask` mode (`/ask`) to ask questions without the assistant attempting file edits.
*   **Git Integration:**
    *   Automatically commit successful changes made by the assistant (`/commit`).
    *   Undo the last commit made by the assistant (`/undo`).
*   **Basic Linting:** Performs a basic Python syntax check on edited files.
*   **Chat History:** Saves the conversation history to `.tinycoder.chat.history.md`.
*   **Repo Map:** Provides the LLM with a high-level overview of the repository structure for files *not* explicitly added to the chat.

## Installation

```bash
pip install .
# Or for development:
pip install -e .
# Or straight from GitHub:
pip install git+https://github.com/koenvaneijk/tinycoder.git
```


Ensure you have the necessary API keys set up as environment variables for your chosen LLM provider (e.g., `GOOGLE_API_KEY` for Gemini, `DEEPSEEK_API_KEY` for DeepSeek).

## Usage

Start the assistant:

```bash
tinycoder
```

Add files to the context:

```bash
tinycoder path/to/your/file.py "another file with spaces.txt"
```

Or add them during the chat:

```
(code) >>> /add my_module.py
```

Interact with the assistant:

```
(code) >>> Refactor the `process_data` function in `my_module.py` to be more efficient.
```

The assistant will respond, and if in `code` mode, may propose changes using the following format:

```
ASSISTANT: Okay, I can refactor that function. Here are the changes:

my_module.py
```python
<<<<<<< SEARCH
    # Old inefficient code
    result = []
    for item in data:
        result.append(item * 2)
    return result
```

## Credits
A lot of credit goes to the Aider.Chat project for many of the ideas that tinycoder was built upon.