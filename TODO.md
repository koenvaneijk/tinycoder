# TinyCoder — Critical Flaws and Actionable TODOs
## P0 — Must Fix

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


## P1 — High Priority

- [ ] Async/sync consistency and streaming paths
  - Problem: App uses async prompt and awaits apply_edits; LLMResponseProcessor.process likely synchronous; ensure streaming path is consistent and non-blocking.
  - Action:
    - [ ] Ensure LLM calls do not block the event loop; support async streaming cleanly.
    - [ ] Add cancellation handling for Ctrl+C during streaming/generation.
  - Owner: Core
  - Files: tinycoder/llm_response_processor.py, tinycoder/app.py

- [ ] Provider/model mapping and pricing consistency
  - Problem: README promises multiple providers via ZenLLM; ensure create_llm_client handles provider/model mappings; pricing used for cost estimate must match actual provider output.
  - Action:
    - [ ] Add provider matrix tests for basic chat completion and pricing lookups.
    - [ ] Validate env var requirements per provider; fail fast with clear messages.
  - Owner: LLM
  - Files: tinycoder/llms/__init__.py, tinycoder/llms/pricing.py, tinycoder/llm_response_processor.py



- [ ] Docker compose parser reliability
  - Problem: Custom YAML parser is fragile.
  - Action:
    - [ ] Add an optional dependency on PyYAML and prefer it when available; fallback to simple parser.
    - [ ] Add tests for typical compose structures (services/volumes/build/context).
  - Owner: Docker
  - Files: tinycoder/docker_manager.py


- [ ] InputPreprocessor placeholders
  - Problem: check_for_file_mentions and check_for_urls are placeholders; @entity extraction exists but coverage is unknown.
  - Action:
    - [ ] Implement URL fetching with safety rules (size limit, content-type allowlist) and add to context optionally.
    - [ ] Implement file mention detection globs and prompt user to add.
    - [ ] Add tests for @path::Entity extraction on sample files.
  - Owner: Context
  - Files: tinycoder/input_preprocessor.py

- [ ] Error-handling standardization
  - Problem: Many functions log and return None/False inconsistently.
  - Action:
    - [ ] Adopt a standard error pattern (exceptions vs error returns) per layer.
    - [ ] Ensure user-facing errors are concise and actionable; internal logs have detail.
  - Owner: Core

---

## P2 — Medium Priority

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

---

## P3 — Nice-to-have / Roadmap

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

- [ ] Optional telemetry (strictly opt-in)
  - Action:
    - [ ] Basic anonymous usage metrics to prioritize features (behind an explicit flag).
  - Owner: Core

- [ ] Enhanced built-in editor (if kept)
  - Action:
    - [ ] Syntax highlighting for multiple languages, simple search/replace, unsaved change indicators.
  - Owner: UX

---

## Milestones

- M1 (Stability/Security): Fix P0 items (imports, git root, command safety, path validation, edit atomicity, parser robustness, CI gate).
- M2 (Correctness/UX): Streaming consistency, provider mapping/pricing, repo map caching, Docker YAML improvements, docs alignment, input preprocessing.
- M3 (DX/Maintainability): Logging hygiene, requests parity, cross-platform hardening, typing/linting, config system, coverage tool safety.


- [ ] Make CodeApplier writes atomic; rollback on lint failure.
