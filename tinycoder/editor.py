import os
import sys
import traceback
from typing import Optional, List, Tuple

from prompt_toolkit.application import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout.containers import HSplit, Window
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.layout import Layout
from prompt_toolkit.lexers import PygmentsLexer, DynamicLexer
from prompt_toolkit.styles import Style, StyleTransformation, Attrs
from prompt_toolkit.widgets import Dialog, Button, Label, SearchToolbar

from pygments.lexers import get_lexer_for_filename, guess_lexer
from pygments.util import ClassNotFound

# --- Editor State and Configuration ---

# Global variable to hold a message for the status bar
status_message = ""

def get_status_bar_text(buffer: Buffer) -> List[Tuple[str, str]]:
    """Generates the text for the status bar."""
    global status_message
    if status_message:
        text = status_message
        status_message = "" # Clear after displaying once
        return [("class:status.message", text)]

    filename = os.path.basename(buffer.name) if buffer.name else "[No Name]"
    modified_indicator = " [*]" if buffer.is_dirty() else ""
    
    return [
        ("class:status", f" {filename}{modified_indicator} | {buffer.document.line_count} lines"),
        ("class:status.right", f"Ln {buffer.document.cursor_position_row + 1}, Col {buffer.document.cursor_position_col + 1} "),
        ("class:status", " | Ctrl-S: Save | Ctrl-Q: Quit | Ctrl-F: Find "),
    ]

# --- Main Editor Application Setup ---

def launch_editor_cli(filepath: Optional[str]) -> None:
    """
    Launches a full-screen text editor using prompt_toolkit.
    """
    global status_message
    
    # --- Key Bindings ---
    kb = KeyBindings()

    @kb.add("c-q")
    def _(event):
        """Ctrl+Q to quit."""
        app = event.app
        if app.layout.buffer.is_dirty():
            # Show "Save changes?" dialog
            async def coroutine():
                dialog = Dialog(
                    title="Unsaved Changes",
                    body=Label("Save changes before quitting?"),
                    buttons=[
                        Button(text="Yes", handler=lambda: "save_and_exit"),
                        Button(text="No", handler=lambda: "exit_no_save"),
                        Button(text="Cancel", handler=lambda: None),
                    ],
                    with_background=True,
                )
                result = await app.show_dialog_as_future(dialog)
                if result == "save_and_exit":
                    app.layout.buffer.save()
                    app.exit()
                elif result == "exit_no_save":
                    app.exit()
            
            app.create_background_task(coroutine())
        else:
            event.app.exit()

    @kb.add("c-s")
    def _(event):
        """Ctrl+S to save."""
        event.app.layout.buffer.save()
        status_message = f"File '{os.path.basename(event.app.layout.buffer.name)}' saved."


    # --- Buffer and Lexer ---
    try:
        # Try to guess language for syntax highlighting
        with open(filepath, "r", encoding="utf-8") as f:
            text_content = f.read()
            try:
                lexer = get_lexer_for_filename(filepath, text_content)
            except ClassNotFound:
                lexer = guess_lexer(text_content)
    except (FileNotFoundError, TypeError):
        text_content = ""
        lexer = None # No lexer for new files yet
    except Exception as e:
        text_content = f"Error loading file: {e}"
        lexer = None

    # DynamicLexer allows us to change the lexer later if needed (e.g., "Save As")
    dynamic_lexer = DynamicLexer(lexer)
    
    # The main buffer for the editor window
    editor_buffer = Buffer(
        name=filepath,
        document=None,  # We set it manually to handle loading
        read_only=False,
    )
    editor_buffer.text = text_content # Load content

    # --- Layout ---
    search_toolbar = SearchToolbar() # Search toolbar widget

    main_editor_window = Window(
        control=BufferControl(
            buffer=editor_buffer,
            lexer=dynamic_lexer,
            search_buffer_control=search_toolbar.control,
        ),
        line_numbers=True,
        wrap_lines=False,
    )

    status_bar = Window(
        content=FormattedTextControl(
            lambda: get_status_bar_text(editor_buffer),
            style="class:status",
        ),
        height=1,
        style="class:status",
    )

    root_container = HSplit([
        main_editor_window,
        search_toolbar,
        status_bar,
    ])

    layout = Layout(
        container=root_container,
        focused_element=main_editor_window
    )
    layout.buffer = editor_buffer # Attach buffer to layout for easy access

    # --- Style ---
    # A basic style for the editor
    style = Style.from_dict({
        "status": "reverse",
        "status.right": "reverse",
        "status.message": "bg:ansiblue fg:ansiwhite",
        "line-number": "bg:ansigray fg:ansibrightblack",
        "line-number.current": "bold bg:ansidarkgray fg:ansiwhite",
        "dialog": "bg:ansiblue",
        "dialog frame.label": "fg:ansiwhite",
        "dialog.body": "bg:ansigray fg:ansiwhite",
        "dialog shadow": "bg:ansigray",
    })

    # --- Application ---
    app = Application(
        layout=layout,
        key_bindings=kb,
        full_screen=True,
        style=style,
        mouse_support=True,
    )

    # --- Run Application ---
    try:
        app.run()
    except Exception as e:
        # Exit fullscreen mode gracefully to show the error
        app.reset()
        print(f"An unexpected error occurred in the editor: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    _initial_filepath: Optional[str] = None
    if len(sys.argv) > 1:
        _initial_filepath = sys.argv[1]
    
    if _initial_filepath and not os.path.exists(_initial_filepath):
        # Create an empty file if it doesn't exist
        try:
            with open(_initial_filepath, 'w') as f:
                pass
            print(f"Created new file: {_initial_filepath}")
        except Exception as e:
            print(f"Error: Could not create file '{_initial_filepath}': {e}")
            sys.exit(1)

    launch_editor_cli(_initial_filepath)
