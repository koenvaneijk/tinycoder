# Concise Logging Guidelines

Log effectively for debugging, monitoring, and auditing.

1.  **Log Purpose:** Understand issues, track health, record key events.
2.  **What to Log:**
    *   Key events: App start/stop, major state changes, job status.
    *   Errors & Exceptions: All uncaught exceptions (with stack traces), significant handled ones.
    *   External Calls: Service requests/responses (status, latency, key params *excluding secrets*).
    *   User Actions: Significant actions (login, data changes) - **avoid PII unless essential and compliant.**
    *   Decision Points: Outcomes of complex logic if helpful for debugging.
    *   Performance: Timings for critical operations (sparingly).
3.  **Use Log Levels Consistently:**
    *   `DEBUG`: Detailed diagnostics (dev/temp only).
    *   `INFO`: Routine operations confirmation.
    *   `WARNING`: Unexpected events, potential future issues.
    *   `ERROR`: Action/function failed.
    *   `CRITICAL`: Severe error; application may fail.
4.  **Format Logs (JSON Recommended):**
    *   Include: Timestamp (ISO 8601), Level, Clear Message, Source (module/function), Request ID, User ID (safe), Stack Trace (for errors).
5.  **Do NOT Log:**
    *   **Sensitive Data:** Passwords, API keys, tokens, most PII, financial/health details.
    *   Large data objects.
    *   Redundant information.
6.  **Key Practices:**
    *   Use Python's standard `logging` module.
    *   Configure logging externally (files/dicts).
    *   Use module-level loggers (`getLogger(__name__)`).
    *   Consider centralized logging systems.
    *   Implement log rotation.
