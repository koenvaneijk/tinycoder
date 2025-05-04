# Python `unittest` Best Practices

Follow these best practices for writing effective, maintainable unit tests using Python's standard `unittest` library.

## Test Structure & Organization

-   **Files**: Start with `test_` (e.g., `test_my_module.py`).
-   **Directories**: Use `tests/` for test files. Keep them separate from production code.
-   **Classes**: Inherit `unittest.TestCase`, name `Test<Something>` (e.g., `TestUserModel`).
-   **Methods**: *Must* start with `test_`. Name descriptively to indicate the tested behavior (e.g., `test_add_positive_numbers`).
-   **Setup/Teardown**:
    -   `setUp()` / `tearDown()`: For setup/cleanup needed *before/after each test method*. Keep fast.
    -   `setUpClass()` / `tearDownClass()`: For setup/cleanup needed *once per class*. Use for expensive operations.

## Writing Effective Tests

-   **AAA Pattern**: Structure tests clearly: **Arrange** (setup), **Act** (execute code), **Assert** (verify result).
-   **Test One Behavior**: Each test method should verify a single logical behavior or condition.
-   **Independence**: Ensure tests can run in any order and do not affect each other. Use setup/teardown for a clean state.
-   **Readability**: Write clear, concise tests. They act as documentation for your code.

## Assertions

-   **Use Specific Asserts**: Prefer methods like `assertEqual`, `assertTrue`, `assertRaises` over generic ones for clearer failure messages.
-   **Assert Outcomes**: Verify the *observable result* or *state change* (the "what"), not the internal implementation details (the "how").
-   **Test Exceptions**: Use `assertRaises()` (method or context manager) to confirm expected exceptions are raised. Check messages with `assertRaisesRegex`.

## Mocking Dependencies

-   **Isolate the Unit**: Use `unittest.mock` (e.g., `@patch`, `patch.object`) to replace external collaborators (database, APIs, other classes) with mocks or stubs.
-   **Verify Interactions**: Use mock assertion methods (`assert_called_with`, `call_count`, etc.) to check that the unit under test interacts correctly with its dependencies.

## Avoiding Common Pitfalls

-   **Don't Test Private Methods**: Test behavior through the public interface.
-   **Simplify Setup**: Complex `setUp` might indicate the tested unit has too many responsibilities.
-   **Cover Edge Cases**: Test boundaries (null, empty, zero, min/max) and error conditions.
-   **Eliminate Flaky Tests**: Fix tests that yield inconsistent results immediately.
-   **Keep Tests Fast**: Unit tests should execute quickly. Separate slower integration tests.

## Running Tests

-   **Discovery**: Use `python -m unittest discover` to find and run tests.
-   **CI Integration**: Automate test execution in your Continuous Integration pipeline.

Adhering to these practices leads to robust tests that provide confidence, facilitate refactoring, and improve code design.