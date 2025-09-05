import io
import logging
import os
import sys
import unittest
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Optional, List, Set

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

def run_tests(
    write_history_func: Callable[[str, str], None],
    git_manager: Optional["GitManager"],
) -> None:
    """
    Discovers and runs unit tests across the project:
      - tests located in the conventional ./tests directory, and
      - tests colocated with code (e.g., pkg/module/test_*.py or pkg/test_module.py),
    while skipping common non-source directories (venv, .git, build, dist, etc.).
    """
    logger = logging.getLogger(__name__)
    logger.info("Running tests...")

    # Determine the root directory (Git root if available, else CWD)
    root_dir: Optional[Path] = None
    if git_manager and git_manager.is_repo():
        root_dir_str = git_manager.get_root()
        if root_dir_str:
            root_dir = Path(root_dir_str)
            logger.info(f"Using Git repository root: {root_dir}")
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
        logger.info("Discovering tests in the following directories (pattern: test_*.py):\n- " + "\n- ".join(rel_dirs))

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

    # Run tests and capture output
    stream = io.StringIO()
    runner = unittest.TextTestRunner(stream=stream, verbosity=2)
    result = runner.run(master_suite)

    output = stream.getvalue()
    stream.close()

    if result.wasSuccessful():
        logger.info(f"Test Results:\n{output}")
        write_history_func("tool", f"Tests run successfully ({result.testsRun} tests).")
    else:
        logger.error(f"Test Results:\n{output}")
        errors_count = len(result.errors)
        failures_count = len(result.failures)
        write_history_func(
            "tool",
            f"Tests run with {errors_count} errors and {failures_count} failures ({result.testsRun} total tests).",
        )
