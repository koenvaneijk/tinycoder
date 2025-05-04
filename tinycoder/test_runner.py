import io
import logging
import sys
import unittest
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Optional

if TYPE_CHECKING:
    from tinycoder.git_manager import GitManager

def run_tests(
    write_history_func: Callable[[str, str], None],
    git_manager: Optional["GitManager"],
) -> None:
    """
    Discovers and runs unit tests in the ./tests directory relative to the project root.

    Args:
        write_history_func: Function to record tool output in chat history.
        git_manager: The GitManager instance to find the repository root.
        logger: Optional logger instance. If None, a default logger is used.
    """
    logger = logging.getLogger(__name__)
    logger.info("Running tests...")

    # Determine the root directory (Git root if available, else CWD)
    test_dir_rel = "tests"
    root_dir: Optional[Path] = None
    if git_manager and git_manager.is_repo():
        root_dir_str = git_manager.get_root()
        if root_dir_str:
            root_dir = Path(root_dir_str)
            logger.info(f"Using Git repository root: {root_dir}")
        else:
            # Should not happen if is_repo() is true, but handle defensively
            logger.error(
                "Could not determine Git repository root despite being in a repo."
            )
            root_dir = Path.cwd()
            logger.info(f"Falling back to current working directory: {root_dir}")

    else:
        # Fallback to current working directory if not in a git repo or git_manager is None/not repo
        root_dir = Path.cwd()
        logger.info(
            f"Not in a Git repository. Using current working directory as project root: {root_dir}"
        )

    if not root_dir:  # Should be set by now, but check again
        logger.error("Failed to determine project root directory.")
        return

    test_dir_abs = root_dir / test_dir_rel

    if not test_dir_abs.is_dir():
        logger.error(f"Test directory '{test_dir_abs}' not found.")
        return

    # Discover tests
    loader = unittest.TestLoader()
    original_sys_path = list(sys.path)  # Store original path
    suite = None
    try:
        # Add root_dir to sys.path temporarily for imports
        if str(root_dir) not in sys.path:
            sys.path.insert(0, str(root_dir))

        logger.info(
            f"Discovering tests in: {test_dir_abs} (pattern: test_*.py, top_level: {root_dir})"
        )
        suite = loader.discover(
            start_dir=str(test_dir_abs),
            pattern="test_*.py",
            top_level_dir=str(root_dir),
        )

    except ImportError as e:
        logger.error(f"Error during test discovery: {e}")
        logger.error(
            f"Ensure that '{root_dir}' or its relevant subdirectories are importable (e.g., check __init__.py files or PYTHONPATH)."
        )
        return  # Exit if discovery fails
    except Exception as e:
        logger.exception("An unexpected error occurred during test discovery.") # Use logger.exception for better traceback
        return  # Exit if discovery fails
    finally:
        # Restore original sys.path regardless of success or failure
        sys.path = original_sys_path

    if not suite or suite.countTestCases() == 0:
        logger.info(f"No tests found in '{test_dir_abs}' matching 'test_*.py'.")
        # Write history even if no tests found
        write_history_func("tool", "Test run complete: No tests found.")
        return

    # Run tests and capture output
    stream = io.StringIO()
    runner = unittest.TextTestRunner(stream=stream, verbosity=2)
    result = runner.run(suite)

    # Print the output
    output = stream.getvalue()
    stream.close()

    # Determine logging level based on test results
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
