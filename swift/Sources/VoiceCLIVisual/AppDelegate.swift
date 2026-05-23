import AppKit
import SwiftUI

/// Owns the HUD window and the long-lived daemon connection.
final class AppDelegate: NSObject, NSApplicationDelegate {
    private var hud: HUDWindow!
    private var client: DaemonClient!
    private let viewModel = HUDViewModel()

    func applicationDidFinishLaunching(_ notification: Notification) {
        hud = HUDWindow(viewModel: viewModel)
        client = DaemonClient(viewModel: viewModel) { [weak self] event in
            // Show / hide the HUD based on session lifecycle events.
            // UI updates must happen on the main thread.
            DispatchQueue.main.async {
                guard let self else { return }
                switch event {
                case .recordingStarted:
                    self.hud.show(near: NSEvent.mouseLocation)
                case .recordingEnded, .pasteDone, .sessionFailed:
                    self.hud.hideAfter(delay: 0.4)
                case .level, .transcribing, .subscribed:
                    break  // pure UI updates, no window change
                }
            }
        }
        client.start()
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        false  // keep running in background even if HUD is hidden
    }
}
