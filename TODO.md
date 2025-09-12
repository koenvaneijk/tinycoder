# TinyCoder — Critical Flaws and Actionable TODOs

This document captures the most critical shortcomings identified across the project and provides concrete, prioritized action items. Use this as a living plan; update and check off items as they’re completed.

Legend:
- P0 = Must fix immediately (stability/security/breakage)
- P1 = High priority (correctness/UX)
- P2 = Medium priority (maintainability)
- P3 = Nice-to-have (polish/roadmap)

---

## P0 — Must Fix

- [ ] Fix circular/wrong imports in LLM modules (breakage risk)
  - Problem: Modules in tinycoder/llms import symbols from tinycoder/__init__.py (e.g., tinycoder/llms/__init__.py and tinycoder/llms/zen_client.py). This is a design smell and can cause circular imports at runtime.
  - Action:
    - [ ] Import LLMClient from tinycoder/llms/base.py in consumers.
    - [ ] Import ZenLLMClient from tinycoder/llms/zen_client.py directly instead of via tinycoder/__init__.py.
    - [ ] Ensure tinycoder/__init__.py does NOT re-export these to avoid cycles.
    - [ ] Add a smoke test to instantiate the client: from tinycoder.llms import create_llm_client; assert it returns a client for several models.
  - Owner: LLM
  - Risk: High
  - Files: tinycoder/llms/__init__.py, tinycoder/llms/zen_client.py, tinycoder/llms/base.py, tinycoder/__init__.py

- [ ] Git root detection only checks CWD (functional bug)
  - Problem: GitManager._find_git_root checks ONLY the current directory for .git; typical behavior is to search parent directories. Many repos run tools from subdirectories.
  - Action:
    - [ ] Walk parents until filesystem root to find .git.
    - [ ] Add tests covering nested invocation.
  - Owner: Git
  - Files: tinycoder/git_manager.py

- [ ] Shell/Docker command execution safety (security)
  - Problem: ShellExecutor executes arbitrary commands via !, DockerManager runs docker-compose commands. No allowlisting/sandboxing; non-interactive mode could be abused.
  - Action:
    - [ ] Add a config flag to disable shell/Docker execution by default; require explicit opt-in.
    - [ ] Add confirmation prompts and redact sensitive output when adding to chat.
    - [ ] Add an allowlist or a “dangerous mode” flag with big warnings.
  - Owner: Security
  - Files: tinycoder/shell_executor.py, tinycoder/docker_manager.py, tinycoder/command_handler.py

- [ ] Path traversal and file-add validation (security/robustness)
  - Problem: Adding files from LLM suggestions or user input might allow paths outside repo root (../../etc/passwd) or symlink escapes.
  - Action:
    - [ ] Enforce resolution to absolute paths and verify they are within git root or CWD root (no traversal/symlinks outside).
    - [ ] Validate requested files in _handle_llm_file_requests and _ask_llm_for_files flows.
    - [ ] Harden FileManager.get_abs_path to guard against traversal/symlink issues.
  - Owner: Security
  - Files: tinycoder/app.py, tinycoder/file_manager.py

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

- [ ] CI and test coverage not enforced (quality gate)
  - Problem: Tests exist but coverage/CI status is unknown; workflows build binaries/publish but no clear unit test gating.
  - Action:
    - [ ] Add a GitHub Actions workflow to run unit tests on PRs (Linux/Windows/macOS).
    - [ ] Fail on any test failure; report coverage.
  - Owner: Build/CI
  - Files: .github/workflows (new), tests

---

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

- [ ] RepoMap performance and scope
  - Problem: RepoMap includes Python/HTML only; no caching; large repos may be slow.
  - Action:
    - [ ] Add simple cache keyed by mtime/size.
    - [ ] Expand optional support for JS/TS/Markdown with lightweight parsers.
    - [ ] Expose controls to limit depth and file count.
  - Owner: RepoMap
  - Files: tinycoder/repo_map.py

- [ ] Docker compose parser reliability
  - Problem: Custom YAML parser is fragile.
  - Action:
    - [ ] Add an optional dependency on PyYAML and prefer it when available; fallback to simple parser.
    - [ ] Add tests for typical compose structures (services/volumes/build/context).
  - Owner: Docker
  - Files: tinycoder/docker_manager.py

- [ ] Documentation mismatches
  - Problem: README mentions a “Built-in Text Editor (/edit)” but no implementation is visible in the repository map. Chat history filenames and locations may also differ from docs.
  - Action:
    - [ ] Either implement /edit (MVP) or remove from README until available.
    - [ ] Align README with ChatHistoryManager behavior (file name/location).
  - Owner: Docs
  - Files: README.md, tinycoder/chat_history.py

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

- [ ] Requests shim vs real requests
  - Problem: Custom tinycoder/requests.py mimics requests; edge cases (SSL verification, redirects, proxies, streaming) may behave differently.
  - Action:
    - [ ] Gate with an optional “use_real_requests” flag; use stdlib urllib fallback only when necessary.
    - [ ] Add parity tests for common cases (timeouts, JSON, errors).
  - Owner: Net
  - Files: tinycoder/requests.py

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

---

## Quick Wins (Do these first)

- [ ] Implement parent-walk in GitManager._find_git_root with tests.
- [ ] Replace broken imports in tinycoder/llms/* to avoid circularities.
- [ ] Add CI workflow “tests.yml” to run unit tests on PRs and main.
- [ ] Guard ShellExecutor and Docker commands behind an opt-in config flag.
- [ ] Enforce repository-root confinement for all user/LLM file additions.
- [ ] Make CodeApplier writes atomic; rollback on lint failure.
- [ ] Update README to remove or implement the “/edit” feature and correct chat history details.

Keep this TODO up-to-date as fixes land. Prioritize P0 first to ensure users get a stable, safe experience.