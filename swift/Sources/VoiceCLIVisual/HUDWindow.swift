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

/// Borderless floating panel that hosts the SwiftUI blob view.
/// .nonactivatingPanel + ignoresMouseEvents means it never steals focus
/// from whatever app the user was typing into.
final class HUDWindow {
    private let panel: NSPanel
    private let viewModel: HUDViewModel
    private var hideTask: DispatchWorkItem?

    init(viewModel: HUDViewModel) {
        self.viewModel = viewModel

        let size = NSSize(width: 160, height: 160)
        panel = NSPanel(
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
        panel.hasShadow = false
        panel.ignoresMouseEvents = true
        panel.isMovableByWindowBackground = false
        panel.titleVisibility = .hidden
        panel.titlebarAppearsTransparent = true
        panel.alphaValue = 0

        let host = NSHostingView(rootView: BlobView(viewModel: viewModel))
        host.frame = NSRect(origin: .zero, size: size)
        panel.contentView = host
    }

    /// Show the HUD positioned near a screen point (typically the mouse).
    /// Animates alpha from 0 → 1 over ~150ms.
    func show(near anchor: NSPoint) {
        hideTask?.cancel()
        hideTask = nil

        let size = panel.frame.size
        // Position slightly above-and-right of anchor, clamped to the
        // current screen so we never spawn off-edge.
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
