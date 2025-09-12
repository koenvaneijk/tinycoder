- [ ] Edit application safety and atomicity (correctness)
  - Problem: CodeApplier applies edits, then lints, and only after that we commit. But:
    - No atomic write or backup/rollback per file.
    - Mixed line-endings or encoding edge cases can corrupt files.
  - Action:
    - [ ] Write to temp files and atomically replace originals.
    - [ ] Normalize line endings and ensure preserved file encoding.
    - [ ] On lint failures, auto-rollback file changes unless user chooses to keep them.
  - Owner: Edits
  - Files: tinycoder/code_applier.py, tinycoder/file_manager.py

- [ ] EditParser robustness (correctness)
  - Problem: XML-like parsing of edits is brittle when models deviate slightly from format; malformed output can cause partial/incorrect application.
  - Action:
    - [ ] Add strict schema validation and tolerant recovery (e.g., ignore incomplete blocks, report actionable errors).
    - [ ] Emit precise diagnostics with block indices and expected tags.
    - [ ] Extend tests with malformed inputs.
  - Owner: Parser
  - Files: tinycoder/edit_parser.py, tests

- [ ] Async/sync consistency and streaming paths
  - Problem: App uses async prompt and awaits apply_edits; LLMResponseProcessor.process likely synchronous; ensure streaming path is consistent and non-blocking.
  - Action:
    - [ ] Ensure LLM calls do not block the event loop; support async streaming cleanly.
    - [ ] Add cancellation handling for Ctrl+C during streaming/generation.
  - Owner: Core
  - Files: tinycoder/llm_response_processor.py, tinycoder/app.py

- [ ] Error-handling standardization
  - Problem: Many functions log and return None/False inconsistently.
  - Action:
    - [ ] Adopt a standard error pattern (exceptions vs error returns) per layer.
    - [ ] Ensure user-facing errors are concise and actionable; internal logs have detail.
  - Owner: Core

- [ ] Logging and formatting hygiene
  - Problem: ANSI color-coded strings are mixed into messages that are also written to history files; could pollute artifacts.
  - Action:
    - [ ] Separate UI formatting (color) from log payloads; only format at sink.
    - [ ] Ensure history file saves plain content without ANSI.
  - Owner: UX
  - Files: tinycoder/ui/log_formatter.py, tinycoder/ui/app_formatter.py, tinycoder/chat_history.py

- [ ] Cross-platform robustness
  - Problem: Paths, coloring, binary detection, and shell commands are OS-sensitive.
  - Action:
    - [ ] Add Windows CI; test path normalization, shell exec quoting, encoding.
    - [ ] Normalize EOLs and encodings in FileManager.read/write.
  - Owner: Build/CI, Core

- [ ] Type-safety and linting
  - Problem: Many modules lack strict typing checks beyond annotations.
  - Action:
    - [ ] Add mypy, ruff, black via pre-commit; fix findings incrementally.
  - Owner: DX

- [ ] Config management
  - Problem: Several features would benefit from a project/user config (e.g., toggles for shell/Docker, repo map settings).
  - Action:
    - [ ] Introduce TOML config at project root (.tinycoder.toml) and merge with user config.
  - Owner: Core

- [ ] Coverage tooling safety/cleanup
  - Problem: coverage_tool modifies import machinery; ensure it restores hooks.
  - Action:
    - [ ] Add try/finally to restore sys.meta_path and state; document usage.
  - Owner: Tests
  - Files: tinycoder/coverage_tool.py

- [ ] Rule system improvements
  - Action:
    - [ ] Support project-local rules with hot reload and validation.
    - [ ] Add docs on writing custom rules.
  - Owner: Rules
  - Files: tinycoder/rule_manager.py

- [ ] Better token budgeting and context previews
  - Action:
    - [ ] Show per-file token estimates; allow user to trim sections interactively.
  - Owner: UX
