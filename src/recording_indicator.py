"""
Recording indicator stub.

Visual indicator is currently disabled due to PyObjC/AppHelper conflicts with
the audio recording loop. The macOS orange microphone indicator, Ping/Pop sounds,
and notifications provide feedback instead.

TODO: Implement using a separate Swift helper app for proper floating window.
"""


class RecordingIndicator:
    """Stub indicator - no visual display."""

    def __init__(self):
        pass

    def show(self):
        """No-op."""
        pass

    def update_level(self, level):
        """No-op."""
        pass

    def hide(self):
        """No-op."""
        pass


_indicator = None


def show_recording_indicator():
    """Show the recording indicator (currently no-op)."""
    global _indicator
    _indicator = RecordingIndicator()
    _indicator.show()
    return _indicator


def hide_recording_indicator(indicator=None):
    """Hide the recording indicator (currently no-op)."""
    global _indicator
    target = indicator or _indicator
    if target:
        target.hide()
    _indicator = None
