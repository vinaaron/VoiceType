"""
Menubar indicator subprocess.

Runs as a separate process (spawned by recording_indicator.py) so the
PyObjC/AppHelper event loop does not deadlock with the PyAudio recording
loop in the parent. Parent kills this with SIGTERM when recording ends.

Reads one float per line from stdin (audio level 0.0–1.0). Shows a tiny
sliding VU meter using Unicode block characters in the menubar title.

Usage: python -m menu_bar_indicator
"""

import signal
import sys
import threading
from collections import deque

import rumps

BARS = " ▁▂▃▄▅▆▇█"
WINDOW = 6  # number of historical bars to show
TICK_HZ = 20  # title refresh rate


def render(levels: deque) -> str:
    bars = "".join(BARS[min(len(BARS) - 1, int(l * (len(BARS) - 1)))] for l in levels)
    return f"🔴 {bars}"


class RecordingApp(rumps.App):
    def __init__(self):
        super().__init__("🔴", quit_button=None)
        self._levels: deque = deque([0.0] * WINDOW, maxlen=WINDOW)
        self._lock = threading.Lock()
        self._reader = threading.Thread(target=self._read_stdin, daemon=True)
        self._reader.start()
        self.timer = rumps.Timer(self._tick, 1.0 / TICK_HZ)
        self.timer.start()

    def _read_stdin(self):
        try:
            for line in sys.stdin:
                try:
                    level = float(line.strip())
                except ValueError:
                    continue
                level = max(0.0, min(1.0, level))
                with self._lock:
                    self._levels.append(level)
        except Exception:
            pass

    def _tick(self, _sender):
        with self._lock:
            levels = list(self._levels)
        self.title = render(levels)


def _handle_sigterm(signum, frame):
    rumps.quit_application()
    sys.exit(0)


def main():
    signal.signal(signal.SIGTERM, _handle_sigterm)
    signal.signal(signal.SIGINT, _handle_sigterm)
    RecordingApp().run()


if __name__ == "__main__":
    main()
