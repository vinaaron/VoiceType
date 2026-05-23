import AppKit
import SwiftUI
import Combine

/// State shared between the SwiftUI view and the daemon client.
final class HUDViewModel: ObservableObject {
    /// Smoothed audio level 0.0–1.0. Smoothing is done in the daemon
    /// client (exponential moving average) before publishing here.
    @Published var level: CGFloat = 0
    /// Coarse session state — drives the blob's colour and pulse.
    @Published var state: SessionState = .idle
}

enum SessionState {
    case idle
    case listening
    case transcribing
}

/// A non-key, non-activating panel that hosts the HUD. Critical that
/// canBecomeKey returns false so the panel never steals focus from the
/// app the user is dictating into, even momentarily during animation.
final class NonActivatingPanel: NSPanel {
    override var canBecomeKey: Bool { false }
    override var canBecomeMain: Bool { false }
}

/// Custom NSView that clips its layer to a circle. Used as the host
/// for NSVisualEffectView so we get a perfect circular glass pill.
final class CircularClipView: NSView {
    override var wantsUpdateLayer: Bool { true }

    override func updateLayer() {
        layer?.cornerRadius = bounds.width / 2
        layer?.masksToBounds = true
    }

    override func layout() {
        super.layout()
        layer?.cornerRadius = bounds.width / 2
    }
}

/// Borderless floating panel that hosts an NSVisualEffectView (the glass)
/// containing a SwiftUI NSHostingView (the blob). Uses NSVisualEffectView
/// directly rather than SwiftUI's `.glassEffect()` because the latter
/// renders flat on a transparent NSPanel — there's no backdrop for it
/// to sample. NSVisualEffectView samples the screen content behind the
/// window properly.
final class HUDWindow {
    private let panel: NonActivatingPanel
    private let viewModel: HUDViewModel
    private let visualEffectView: NSVisualEffectView
    private var hideTask: DispatchWorkItem?

    /// Outer pill diameter. Blob/halo scale relative to this.
    private let pillSize: CGFloat = 108

    init(viewModel: HUDViewModel) {
        self.viewModel = viewModel

        let size = NSSize(width: pillSize, height: pillSize)
        panel = NonActivatingPanel(
            contentRect: NSRect(origin: .zero, size: size),
            styleMask: [.nonactivatingPanel, .borderless],
            backing: .buffered,
            defer: false
        )
        panel.isFloatingPanel = true
        panel.level = .floating
        panel.collectionBehavior = [.canJoinAllSpaces, .stationary, .fullScreenAuxiliary]
        panel.isOpaque = false
        panel.backgroundColor = .clear
        panel.hasShadow = true
        panel.ignoresMouseEvents = true
        panel.isMovableByWindowBackground = false
        panel.titleVisibility = .hidden
        panel.titlebarAppearsTransparent = true
        panel.alphaValue = 0
        panel.hidesOnDeactivate = false

        // Circular glass via NSVisualEffectView. .hudWindow gives a
        // classic translucent vibrancy; .behindWindow blending samples
        // what's behind the panel on screen so it actually looks like
        // glass (not just a tinted solid).
        let circular = CircularClipView(frame: NSRect(origin: .zero, size: size))
        circular.wantsLayer = true
        circular.layer?.backgroundColor = .clear

        visualEffectView = NSVisualEffectView(frame: NSRect(origin: .zero, size: size))
        visualEffectView.material = .hudWindow
        visualEffectView.blendingMode = .behindWindow
        visualEffectView.state = .active
        visualEffectView.autoresizingMask = [.width, .height]
        visualEffectView.wantsLayer = true
        circular.addSubview(visualEffectView)

        // Blob host. Same size as the pill — the blob draws itself with
        // a generous safety margin inside, so it never touches the
        // circular clip even at peak energy.
        let host = NSHostingView(rootView: BlobView(viewModel: viewModel))
        host.frame = NSRect(origin: .zero, size: size)
        host.autoresizingMask = [.width, .height]
        host.wantsLayer = true
        host.layer?.backgroundColor = .clear
        circular.addSubview(host)

        panel.contentView = circular
    }

    /// Show the HUD positioned near a screen point (typically the mouse).
    /// Animates alpha from 0 → 1 over ~150ms.
    func show(near anchor: NSPoint) {
        hideTask?.cancel()
        hideTask = nil

        let size = panel.frame.size
        var origin = NSPoint(
            x: anchor.x - size.width / 2,
            y: anchor.y + 30
        )
        if let screen = NSScreen.screens.first(where: { $0.frame.contains(anchor) }) ?? NSScreen.main {
            let vis = screen.visibleFrame
            origin.x = max(vis.minX + 8, min(origin.x, vis.maxX - size.width - 8))
            origin.y = max(vis.minY + 8, min(origin.y, vis.maxY - size.height - 8))
        }
        panel.setFrameOrigin(origin)
        // orderFrontRegardless doesn't activate the app for a
        // .nonactivatingPanel, but combined with our canBecomeKey=false
        // override we have belt+braces against focus stealing.
        panel.orderFrontRegardless()

        viewModel.state = .listening

        NSAnimationContext.runAnimationGroup { ctx in
            ctx.duration = 0.15
            panel.animator().alphaValue = 1.0
        }
    }

    /// Schedule a fade-out + close. Cancels any in-flight hide and
    /// debounces so quick state transitions don't flicker.
    func hideAfter(delay: TimeInterval) {
        hideTask?.cancel()
        let task = DispatchWorkItem { [weak self] in
            guard let self else { return }
            NSAnimationContext.runAnimationGroup { ctx in
                ctx.duration = 0.25
                self.panel.animator().alphaValue = 0
            } completionHandler: {
                self.panel.orderOut(nil)
                self.viewModel.level = 0
                self.viewModel.state = .idle
            }
        }
        hideTask = task
        DispatchQueue.main.asyncAfter(deadline: .now() + delay, execute: task)
    }
}
