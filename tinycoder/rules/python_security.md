# Secure Python Coding Practices

Integrate security throughout development to protect users and data.

1.  **Validate & Sanitize Input:**
    *   Never trust external data (user input, APIs, files). Check type, format, length, range.
    *   Prevent Injection (SQL, Command): Use ORMs/parameterized queries; avoid unsanitized input in shell commands.
    *   Prevent XSS: Escape/sanitize user data for HTML output; use auto-escaping template engines.

2.  **Authentication & Authorization:**
    *   **Authentication (Who):** Use proven libraries, hash passwords strongly (e.g., Argon2, bcrypt), secure sessions, consider MFA.
    *   **Authorization (What):** Apply least privilege; enforce server-side permission checks on *every* request.

4.  **Secure Data Handling:**
    *   Avoid logging sensitive data (keys, PII, passwords).
    *   Always use HTTPS for transmission.
    *   Consider encrypting sensitive data at rest.

5.  **Secure Error Handling:**
    *   Avoid leaking implementation details or stack traces in user-facing errors.
    *   Log detailed errors securely for developers only.

6.  **Use Framework Features:**
    *   Leverage built-in security tools from your web framework (e.g., CSRF protection, XSS filters).
