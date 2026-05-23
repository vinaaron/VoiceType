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

    `app_name` here is the System Events PROCESS name (e.g. "wezterm-gui"),
    which is what get_frontmost_app() returns. `tell application "X"`
    wants the BUNDLE display name (e.g. "WezTerm") and silently errors
    with -1728 for process names. So we use the `application process`
    form which accepts the process name directly.

    If anything goes wrong, log the AppleScript stderr instead of
    swallowing it — this paste-failure cause cost us hours of debugging.
    """
    if not app_name:
        return
    script = f'''
    tell application "System Events"
        set frontmost of (first application process whose name is "{app_name}") to true
    end tell
    '''
    result = subprocess.run(
        ["osascript", "-e", script],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 and result.stderr:
        try:
            from logger import log_error
            log_error(f"activate_app({app_name!r}) osascript failed: {result.stderr.strip()}")
        except ImportError:
            pass


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


def read_clipboard() -> bytes:
    """Return the current clipboard contents as bytes (binary-safe)."""
    try:
        result = subprocess.run(
            ["pbpaste"], capture_output=True, timeout=1.0,
        )
        return result.stdout
    except (subprocess.TimeoutExpired, FileNotFoundError):
        return b""


def write_clipboard_bytes(data: bytes) -> None:
    """Write raw bytes to the clipboard (binary-safe pbcopy)."""
    try:
        process = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE)
        process.communicate(data, timeout=1.0)
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass


def paste_from_clipboard() -> None:
    """
    Simulate Cmd+V keystroke to paste from clipboard.

    Logs osascript errors instead of swallowing them. The classic
    failure is `(1002) osascript is not allowed to send keystrokes`,
    which means the binary launching us doesn't have Accessibility
    permission. When the daemon is spawned by Raycast (the normal
    hotkey path), it inherits Raycast's grant. When spawned manually
    from a terminal without that inheritance, paste silently fails.
    """
    script = '''
    tell application "System Events"
        keystroke "v" using command down
    end tell
    '''
    result = subprocess.run(
        ["osascript", "-e", script],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 and result.stderr:
        try:
            from logger import log_error
            log_error(f"paste_from_clipboard osascript failed: {result.stderr.strip()}")
        except ImportError:
            pass


def press_enter() -> None:
    """Simulate pressing Return. Same permission requirement as paste."""
    script = '''
    tell application "System Events"
        keystroke return
    end tell
    '''
    result = subprocess.run(
        ["osascript", "-e", script],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 and result.stderr:
        try:
            from logger import log_error
            log_error(f"press_enter osascript failed: {result.stderr.strip()}")
        except ImportError:
            pass


def type_text_via_clipboard(text: str, target_app: str = None) -> None:
    """
    Type text into an application using the clipboard method.

    Saves the user's existing clipboard before pasting and restores it
    after, so dictation doesn't clobber whatever was previously copied.

    Args:
        text: Text to type
        target_app: App to activate before pasting. If None, pastes to current frontmost.
    """
    if not text:
        return

    saved_clipboard = read_clipboard()

    copy_to_clipboard(text)

    if target_app:
        activate_app(target_app)
        import time
        time.sleep(0.03)

    paste_from_clipboard()

    # Give the receiving app a beat to actually consume the paste before
    # we swap the clipboard back. 300ms is conservative — even slow
    # Electron-based targets (Cursor, VSCode, Claude Code) finish their
    # paste handling within ~200ms, but we'd rather have a slow restore
    # than risk pasting our restored content into the wrong field.
    import time as _time
    _time.sleep(0.30)
    write_clipboard_bytes(saved_clipboard)


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


_TERMINAL_NOTIFIER = "/opt/homebrew/bin/terminal-notifier"


def notify(title: str, message: str) -> None:
    """
    Show a macOS notification.

    Prefers terminal-notifier (clickable, dismissable, no AppleScript stall)
    when present; falls back to osascript display notification.
    """
    if os.path.exists(_TERMINAL_NOTIFIER):
        subprocess.Popen(
            [_TERMINAL_NOTIFIER, "-title", title, "-message", message, "-group", "voice-cli"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return

    script = f'display notification "{message}" with title "{title}"'
    subprocess.run(
        ["osascript", "-e", script],
        check=False,
        capture_output=True,
    )
