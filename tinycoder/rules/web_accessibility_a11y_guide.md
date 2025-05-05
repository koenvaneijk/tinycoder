# Web Accessibility (a11y) Quick Guide

Ensure web content is usable by everyone, including people with disabilities.

1.  **Use Semantic HTML:**
    *   Choose HTML elements based on their *meaning*, not just appearance (`<nav>`, `<main>`, `<button>`, `<h1>`-`<h6>`, `<ul>`, `<ol>`, `<li>`).
    *   Structure content logically with proper heading levels.
    *   Use `<button>` for actions, `<a>` for navigation.

2.  **Ensure Keyboard Navigability:**
    *   All interactive elements (links, buttons, form controls) must be reachable and operable using the Tab key (and Shift+Tab).
    *   Logical focus order: Ensure the tab sequence follows the visual flow.
    *   Visible focus indicator: Don't disable the default outline without providing a clear alternative (`:focus-visible`).

3.  **Use ARIA Sparingly & Correctly:**
    *   **Prefer Native HTML:** Use standard HTML elements whenever possible.
    *   **Enhance, Don't Replace:** Use ARIA roles (`role="alert"`, `role="dialog"`) and attributes (`aria-label`, `aria-hidden`, `aria-expanded`, `aria-required`) to clarify semantics or state, especially for custom JavaScript widgets.
    *   **Don't Guess:** Validate ARIA usage; incorrect ARIA is worse than none.

4.  **Maintain Sufficient Color Contrast:**
    *   Ensure text has adequate contrast against its background (WCAG AA: 4.5:1 for normal text, 3:1 for large text). Use contrast checker tools.
    *   Don't rely on color alone to convey information (use icons, text, patterns).

5.  **Design Accessible Forms:**
    *   **Labels:** Associate every form control (`<input>`, `<textarea>`, `<select>`) explicitly with a `<label for="control-id">`.
    *   **Grouping:** Use `<fieldset>` and `<legend>` to group related controls (e.g., radio buttons).
    *   **Instructions & Errors:** Provide clear instructions and associate error messages programmatically with the relevant input (e.g., using `aria-describedby`).
    *   **Required Fields:** Clearly indicate required fields visually and programmatically (`required`, `aria-required="true"`).

6.  **Provide Text Alternatives for Non-Text Content:**
    *   Use meaningful `alt` text for informative images (`<img alt="Description">`).
    *   Use empty `alt=""` for purely decorative images.
    *   Provide transcripts/captions for audio and video content.

Following these core principles significantly improves the accessibility of your web content.