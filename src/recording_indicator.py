"""
Floating recording indicator using PyObjC.
Wispr Flow-style minimal window that doesn't steal focus.
"""

import threading


class RecordingIndicator:
    """Manages a floating recording indicator window using PyObjC."""

    def __init__(self):
        self.window = None
        self._thread = None
        self._running = False
        self._ready = threading.Event()

    def show(self):
        """Show the recording indicator in a background thread."""
        self._running = True
        self._thread = threading.Thread(target=self._run_indicator, daemon=True)
        self._thread.start()
        # Wait for window to be ready (up to 1 second)
        self._ready.wait(timeout=1.0)

    def _run_indicator(self):
        """Create and display the floating window."""
        try:
            from AppKit import (
                NSWindow, NSView, NSColor, NSFont, NSScreen,
                NSBackingStoreBuffered, NSBezierPath, NSAttributedString,
                NSApplication,
            )
            from Foundation import NSMakeRect
            from PyObjCTools import AppHelper

            # Initialize NSApplication (required for windows to display)
            NSApplication.sharedApplication()

            # Window style constants
            NSBorderlessWindowMask = 0
            NSFloatingWindowLevel = 5

            # Create borderless window
            width, height = 145, 34
            frame = NSMakeRect(0, 0, width, height)

            self.window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
                frame,
                NSBorderlessWindowMask,
                NSBackingStoreBuffered,
                False
            )

            # Configure window properties
            self.window.setLevel_(NSFloatingWindowLevel)
            self.window.setOpaque_(False)
            self.window.setBackgroundColor_(NSColor.clearColor())
            self.window.setHasShadow_(True)
            self.window.setIgnoresMouseEvents_(True)  # Click-through
            self.window.setCollectionBehavior_(1 << 0)  # Can join all spaces

            # Position at top-center of main screen
            screen = NSScreen.mainScreen()
            if screen:
                screen_frame = screen.frame()
                x = (screen_frame.size.width - width) / 2
                y = screen_frame.size.height - 70  # Near top, below menu bar
                self.window.setFrameOrigin_((x, y))

            # Create custom view class for drawing
            class IndicatorView(NSView):
                def drawRect_(self_, rect):
                    bounds = self_.bounds()

                    # Draw rounded rectangle background (dark, semi-transparent)
                    NSColor.colorWithCalibratedRed_green_blue_alpha_(
                        0.12, 0.12, 0.12, 0.92
                    ).set()
                    path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(
                        bounds, 10, 10
                    )
                    path.fill()

                    # Draw pulsing red recording dot
                    NSColor.colorWithCalibratedRed_green_blue_alpha_(
                        0.92, 0.25, 0.25, 1.0
                    ).set()
                    dot_rect = NSMakeRect(14, 12, 10, 10)
                    NSBezierPath.bezierPathWithOvalInRect_(dot_rect).fill()

                    # Draw "Recording..." text
                    attrs = {
                        "NSFont": NSFont.systemFontOfSize_(13),
                        "NSColor": NSColor.whiteColor(),
                    }
                    text = NSAttributedString.alloc().initWithString_attributes_(
                        "Recording...", attrs
                    )
                    text.drawAtPoint_((32, 9))

            # Add view to window
            view = IndicatorView.alloc().initWithFrame_(frame)
            self.window.setContentView_(view)

            # Show window without activating (won't steal focus)
            self.window.orderFrontRegardless()

            # Signal that window is ready
            self._ready.set()

            # Run event loop to keep window visible and responsive
            while self._running:
                AppHelper.runConsoleEventLoop(installInterrupt=False, maxTimeout=0.1)

        except Exception as e:
            # If PyObjC fails, just continue silently (sound feedback still works)
            self._ready.set()

    def hide(self):
        """Hide and cleanup the recording indicator."""
        self._running = False

        if self.window:
            try:
                self.window.orderOut_(None)
            except Exception:
                pass
            self.window = None

        # Give thread time to clean up
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=0.3)


# Module-level functions for easy use
_indicator = None


def show_recording_indicator():
    """Show the floating recording indicator. Returns the indicator instance."""
    global _indicator
    _indicator = RecordingIndicator()
    _indicator.show()
    return _indicator


def hide_recording_indicator(indicator=None):
    """Hide the recording indicator."""
    global _indicator
    target = indicator or _indicator
    if target:
        target.hide()
    _indicator = None
