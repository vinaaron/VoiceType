"""
Recording indicator.

Spawns menu_bar_indicator as a subprocess so the rumps/PyObjC event loop
runs in isolation from the PyAudio recording loop in the parent process.
Audio levels are streamed into the subprocess via stdin (one float per line)
so the menubar title shows a small sliding VU meter while recording.
"""

import os
import subprocess
import sys


SRC_DIR = os.path.dirname(os.path.abspath(__file__))


class RecordingIndicator:
    def __init__(self):
        self._proc: subprocess.Popen | None = None

    def show(self):
        if self._proc is not None:
            return
        env = os.environ.copy()
        env["PYTHONPATH"] = SRC_DIR + os.pathsep + env.get("PYTHONPATH", "")
        try:
            self._proc = subprocess.Popen(
                [sys.executable, "-m", "menu_bar_indicator"],
                env=env,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            self._proc = None

    def update_level(self, level: float):
        """Push an audio level (0.0–1.0) to the menubar subprocess."""
        if self._proc is None or self._proc.stdin is None:
            return
        try:
            self._proc.stdin.write(f"{float(level):.3f}\n".encode())
            self._proc.stdin.flush()
        except (BrokenPipeError, OSError, ValueError):
            pass

    def hide(self):
        if self._proc is None:
            return
        try:
            if self._proc.stdin:
                try:
                    self._proc.stdin.close()
                except OSError:
                    pass
            self._proc.terminate()
            try:
                self._proc.wait(timeout=0.5)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        except Exception:
            pass
        finally:
            self._proc = None


_indicator: RecordingIndicator | None = None


def show_recording_indicator():
    global _indicator
    _indicator = RecordingIndicator()
    _indicator.show()
    return _indicator


def hide_recording_indicator(indicator=None):
    global _indicator
    target = indicator or _indicator
    if target:
        target.hide()
    _indicator = None
