# Foundation CSS & Embedded Vanilla JS

Best practices for using Foundation CSS with embedded vanilla JavaScript.

1.  **Setup (CDN):**
    *   **CSS (in `<head>`):**
        ```html
        <!-- Compressed Foundation CSS -->
        <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/foundation-sites@6.9.0/dist/css/foundation.min.css" crossorigin="anonymous">
        <!-- Your Custom CSS (After Foundation) -->
        <link rel="stylesheet" href="path/to/your/custom.css">
        ```
    *   **JS (before `</body>`):**
        ```html
        <!-- jQuery (Required by Foundation 6) -->
        <script src="https://code.jquery.com/jquery-3.6.0.min.js" integrity="sha256-/xUj+3OJU5yExlq6GSYGSHk7tPXikynS7ogEvDej/m4=" crossorigin="anonymous"></script>
        <!-- Compressed Foundation JavaScript -->
        <script src="https://cdn.jsdelivr.net/npm/foundation-sites@6.9.0/dist/js/foundation.min.js" crossorigin="anonymous"></script>
        <!-- Your Embedded JS / Link to JS File -->
        <script>
          // Initialize Foundation JS
          $(document).foundation();

          // Your custom vanilla JS init (optional, inside DOMContentLoaded)
          document.addEventListener('DOMContentLoaded', () => {
            // ... your vanilla JS setup ...
          });
        </script>
        ```
    *   Ensure custom CSS loads *after* Foundation CSS.
    *   Ensure custom JS runs *after* Foundation JS and its initialization (`$(document).foundation();`).

2.  **HTML Structure:**
    *   Use Foundation grid (`grid-x`, `cell`) and component classes extensively.
    *   Use semantic HTML5 elements.
    *   Use `id` or dedicated `js-*` classes for JS hooks, **not** style classes.
    *   Include necessary ARIA attributes, sync with JS state changes.

3.  **CSS:**
    *   Prioritize Foundation utility classes over custom CSS.
    *   Write minimal custom CSS for branding/unique styles.
    *   Load custom CSS *after* Foundation's.
    *   Use specific selectors for overrides; avoid `!important`.

4.  **JavaScript (Embedded Vanilla):**
    *   Place custom `<script>` tags *after* Foundation JS initialization, before `</body>`.
    *   Wrap code needing DOM elements in `DOMContentLoaded` listener.
    *   Use efficient selectors (`getElementById`, `querySelector`); cache elements.
    *   Use `addEventListener`; favor event delegation for dynamic content.
    *   Manipulate Foundation primarily via CSS classes (`.is-active`, `.hide`) and ARIA attributes.
    *   Use Foundation's JS API (`$('#el').foundation('method')`) only when necessary for component control.
    *   Avoid global scope (use IIFE, functions).
    *   Keep embedded JS focused on UI behavior, not complex logic.

5.  **Key Principles:**
    *   Maintain separation of concerns (HTML: structure, CSS: presentation, JS: behavior).
    *   Prioritize readability and maintainability.
    *   Optimize for performance (delegation, minimize DOM access).