import io
import logging
import os
import sys
import time
import unittest
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Optional, List, Set, Tuple

from tinycoder.ui.log_formatter import COLORS, RESET

if TYPE_CHECKING:
    from tinycoder.git_manager import GitManager

# Common directories to exclude from test discovery
EXCLUDED_DIR_NAMES: Set[str] = {
    ".git",
    ".hg",
    ".svn",
    ".tox",
    ".venv",
    "venv",
    "env",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".idea",
    ".vscode",
    ".eggs",
    "build",
    "dist",
    "node_modules",
}

def _find_test_start_dirs(root_dir: Path) -> List[Path]:
    """
    Walk the project tree and return a minimal set of directories to start unittest discovery from.
    A directory is included if it contains at least one test_*.py file. We prune excluded dirs, and
    once we include a directory, we do not descend into it further to avoid duplicate discovery.
    """
    start_dirs: List[Path] = []

    for current_dir, dirs, files in os.walk(root_dir, topdown=True):
        # Prune excluded directories
        dirs[:] = [d for d in dirs if d not in EXCLUDED_DIR_NAMES]

        has_tests_here = any(f.startswith("test_") and f.endswith(".py") for f in files)
        if has_tests_here:
            start_dirs.append(Path(current_dir))
            # Prevent descending; discovery from this dir will handle subdirs
            dirs[:] = []

    # Deduplicate while preserving order
    seen: Set[Path] = set()
    unique_dirs: List[Path] = []
    for d in start_dirs:
        rp = d.resolve()
        if rp not in seen:
            seen.add(rp)
            unique_dirs.append(d)
    return unique_dirs

def _format_test_id(test: unittest.case.TestCase) -> str:
    try:
        return test.id()
    except Exception:
        return str(test)

def _color(name: str) -> str:
    # Gracefully handle if COLORS is missing a key
    return COLORS.get(name, "")

def run_tests(
    write_history_func: Callable[[str, str], None],
    git_manager: Optional["GitManager"],
) -> None:
    """
    Discovers and runs unit tests across the project:
      - tests located in the conventional ./tests directory, and
      - tests colocated with code (e.g., pkg/module/test_*.py or pkg/test_module.py),
    while skipping common non-source directories (venv, .git, build, dist, etc.).

    Output formatting:
      - If all tests pass: print a single concise green line with a checkmark.
      - If failures/errors exist: print a compact summary and only the failing/erroring tests
        with their tracebacks. Use colors, emojis, and separators for readability.
    """
    logger = logging.getLogger(__name__)
    logger.info("🧪 Running tests...")

    # Determine the root directory (Git root if available, else CWD)
    root_dir: Optional[Path] = None
    if git_manager and git_manager.is_repo():
        root_dir_str = git_manager.get_root()
        if root_dir_str:
            root_dir = Path(root_dir_str)
        else:
            logger.error("Could not determine Git repository root despite being in a repo.")
            root_dir = Path.cwd()
            logger.info(f"Falling back to current working directory: {root_dir}")
    else:
        root_dir = Path.cwd()
        logger.info(f"Not in a Git repository. Using current working directory as project root: {root_dir}")

    if not root_dir:
        logger.error("Failed to determine project root directory.")
        return

    # Discover tests in multiple locations (tests directory and alongside code)
    loader = unittest.TestLoader()
    master_suite = unittest.TestSuite()
    original_sys_path = list(sys.path)

    try:
        # Ensure project root is importable
        if str(root_dir) not in sys.path:
            sys.path.insert(0, str(root_dir))

        start_dirs = _find_test_start_dirs(root_dir)
        if not start_dirs:
            logger.info("No test_*.py files found in project (after excluding common directories).")
            write_history_func("tool", "Test run complete: No tests found.")
            return

        # Log discovered start directories (relative to root)
        rel_dirs = [str(Path(d).resolve().relative_to(root_dir.resolve())) or "." for d in start_dirs]
        logger.debug("Discovering tests in the following directories (pattern: test_*.py):\n- " + "\n- ".join(rel_dirs))

        for start_dir in start_dirs:
            try:
                suite = loader.discover(
                    start_dir=str(start_dir),
                    pattern="test_*.py",
                    top_level_dir=str(root_dir),
                )
                master_suite.addTests(suite)
            except Exception:
                logger.exception(f"An error occurred during test discovery in '{start_dir}'. Continuing with other directories.")

    finally:
        # Restore original sys.path regardless of success or failure
        sys.path = original_sys_path

    total_tests = master_suite.countTestCases()
    if total_tests == 0:
        logger.info("No tests collected after discovery.")
        write_history_func("tool", "Test run complete: No tests found.")
        return

    # Run tests with buffered output so only failing tests show captured stdout/stderr
    stream = io.StringIO()
    runner = unittest.TextTestRunner(stream=stream, verbosity=0, buffer=True)
    t0 = time.perf_counter()
    result = runner.run(master_suite)
    duration_s = time.perf_counter() - t0

    # Build concise summary
    failures: List[Tuple[unittest.case.TestCase, str]] = result.failures
    errors: List[Tuple[unittest.case.TestCase, str]] = result.errors
    skipped_list = getattr(result, "skipped", [])
    expected_failures_list = getattr(result, "expectedFailures", [])
    unexpected_successes_list = getattr(result, "unexpectedSuccesses", [])

    failures_count = len(failures)
    errors_count = len(errors)
    skipped_count = len(skipped_list)
    expected_failures_count = len(expected_failures_list)
    unexpected_successes_count = len(unexpected_successes_list)
    passed_count = (
        result.testsRun
        - failures_count
        - errors_count
        - skipped_count
        - expected_failures_count
    )

    green = _color("green")
    red = _color("red")
    yellow = _color("yellow")
    cyan = _color("cyan")
    bold = _color("bold")
    reset = RESET
    sep = "-" * 70

    if result.wasSuccessful():
        msg = f"✅ {bold}{green}{passed_count} tests passed{reset} ⏱️ {duration_s:.2f}s"
        if skipped_count:
            msg += f"  |  {yellow}{skipped_count} skipped{reset}"
        logger.info(msg)
        write_history_func("tool", f"✅ {passed_count} tests passed in {duration_s:.2f}s" + (f" ({skipped_count} skipped)" if skipped_count else ""))
        return

    # Failures/errors present – show only those
    header = (
        f"❌ {bold}{red}Test failures detected{reset} "
        f"(total={result.testsRun}, {failures_count} failures, {errors_count} errors, "
        f"{skipped_count} skipped, {unexpected_successes_count} unexpected successes) "
        f"⏱️ {duration_s:.2f}s"
    )
    logger.error(header)
    logger.error(sep)

    def _print_section(title: str, items: List[Tuple[unittest.case.TestCase, str]]) -> None:
        if not items:
            return
        logger.error(f"{bold}{title}{reset} ({len(items)}):")
        for test, tb in items:
            test_name = _format_test_id(test)
            logger.error(f"{cyan}{test_name}{reset}")
            # Truncate very long tracebacks
            lines = tb.rstrip().splitlines()
            if len(lines) > 200:
                tb_display = "\n".join(lines[-120:])
                logger.error("(traceback truncated to last 120 lines)")
            else:
                tb_display = tb
            logger.error(tb_display)
            logger.error(sep)

    _print_section("FAILURES", failures)
    _print_section("ERRORS", errors)

    tail_summary = (
        f"⚠️  Summary: {failures_count} failure(s), {errors_count} error(s), "
        f"{skipped_count} skipped, {unexpected_successes_count} unexpected success(es)."
    )
    logger.error(tail_summary)

    # Write a compact summary to history (details stay in logs)
    write_history_func(
        "tool",
        f"❌ Tests run with {errors_count} error(s) and {failures_count} failure(s) "
        f"({result.testsRun} total, {skipped_count} skipped) in {duration_s:.2f}s.",
    )
