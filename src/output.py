"""
Output module for typing text into the active terminal window.

Uses osascript (AppleScript) to simulate keystrokes in the frontmost application.
Includes clipboard-based approach for more reliable cross-app text transfer.
"""

import subprocess
import os


def get_frontmost_app() -> str:
    """
    Get the name of the currently frontmost (active) application.

    Returns:
        Name of the frontmost app (e.g., "WezTerm", "Terminal")
    """
    script = '''
    tell application "System Events"
        set frontApp to name of first application process whose frontmost is true
    end tell
    return frontApp
    '''

    result = subprocess.run(
        ["osascript", "-e", script],
        capture_output=True,
        text=True
    )
    return result.stdout.strip()


def activate_app(app_name: str) -> None:
    """
    Bring an application to the front (make it frontmost).

    Args:
        app_name: Name of the application to activate
    """
    script = f'''
    tell application "{app_name}"
        activate
    end tell
    '''

    subprocess.run(
        ["osascript", "-e", script],
        check=False,
        capture_output=True
    )


def copy_to_clipboard(text: str) -> None:
    """
    Copy text to the system clipboard using pbcopy.

    Args:
        text: Text to copy to clipboard
    """
    process = subprocess.Popen(
        ["pbcopy"],
        stdin=subprocess.PIPE
    )
    process.communicate(text.encode("utf-8"))


def paste_from_clipboard() -> None:
    """
    Simulate Cmd+V keystroke to paste from clipboard.
    """
    script = '''
    tell application "System Events"
        keystroke "v" using command down
    end tell
    '''

    subprocess.run(
        ["osascript", "-e", script],
        check=False,
        capture_output=True
    )


def press_enter() -> None:
    """
    Simulate pressing the Enter/Return key.
    """
    script = '''
    tell application "System Events"
        keystroke return
    end tell
    '''

    subprocess.run(
        ["osascript", "-e", script],
        check=False,
        capture_output=True
    )


def type_text_via_clipboard(text: str, target_app: str = None) -> None:
    """
    Type text into an application using the clipboard method.

    This is more reliable than direct keystrokes when the target app
    is not currently frontmost (e.g., when triggered from Raycast).

    Args:
        text: Text to type
        target_app: App to activate before pasting. If None, pastes to current frontmost.
    """
    if not text:
        return

    # Copy to clipboard
    copy_to_clipboard(text)

    # Activate target app if specified
    if target_app:
        activate_app(target_app)
        # Small delay to ensure app is frontmost
        import time
        time.sleep(0.1)

    # Paste
    paste_from_clipboard()


def type_text(text: str) -> None:
    """
    Type text into the frontmost application using osascript.

    This simulates keyboard input, so the text will appear wherever
    the cursor is currently focused.

    Args:
        text: The text to type

    Raises:
        subprocess.CalledProcessError: If osascript fails
    """
    if not text:
        return

    # Escape special characters for AppleScript string
    escaped = text.replace("\\", "\\\\").replace('"', '\\"')

    script = f'''
    tell application "System Events"
        keystroke "{escaped}"
    end tell
    '''

    subprocess.run(
        ["osascript", "-e", script],
        check=True,
        capture_output=True
    )


def type_text_with_return(text: str) -> None:
    """
    Type text and press Return/Enter at the end.

    Useful for submitting commands directly.
    """
    if not text:
        return

    escaped = text.replace("\\", "\\\\").replace('"', '\\"')

    script = f'''
    tell application "System Events"
        keystroke "{escaped}"
        keystroke return
    end tell
    '''

    subprocess.run(
        ["osascript", "-e", script],
        check=True,
        capture_output=True
    )


def play_sound(sound_name: str = "Ping", blocking: bool = False) -> None:
    """
    Play a system sound for audio feedback.

    Args:
        sound_name: Name of the system sound (without extension).
                   Common options: "Ping", "Pop", "Tink", "Purr", "Funk"
        blocking: If False (default), play asynchronously and return immediately.
                  If True, wait for sound to finish before returning.
    """
    sound_path = f"/System/Library/Sounds/{sound_name}.aiff"

    if os.path.exists(sound_path):
        if blocking:
            subprocess.run(
                ["afplay", sound_path],
                check=False,
                capture_output=True
            )
        else:
            # Play asynchronously - don't block waiting for sound to finish
            subprocess.Popen(
                ["afplay", sound_path],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )


def notify(title: str, message: str) -> None:
    """
    Show a macOS notification.

    Args:
        title: Notification title
        message: Notification body text
    """
    script = f'''
    display notification "{message}" with title "{title}"
    '''

    subprocess.run(
        ["osascript", "-e", script],
        check=False,
        capture_output=True
    )
