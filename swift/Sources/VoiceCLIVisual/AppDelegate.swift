import AppKit
import Carbon
import SwiftUI
import ServiceManagement

/// Owns the HUD window, the long-lived daemon subscription, and the
/// global hotkey. Replaces Raycast as the entry point.
final class AppDelegate: NSObject, NSApplicationDelegate {
    private var hud: HUDWindow!
    private var client: DaemonClient!
    private var hotkey: HotKey!
    private var statusItem: NSStatusItem!
    private let viewModel = HUDViewModel()

    func applicationDidFinishLaunching(_ notification: Notification) {
        hud = HUDWindow(viewModel: viewModel)

        client = DaemonClient(viewModel: viewModel) { [weak self] event in
            DispatchQueue.main.async {
                guard let self else { return }
                switch event {
                case .recordingStarted:
                    self.hud.show(near: NSEvent.mouseLocation)
                case .recordingEnded, .pasteDone, .sessionFailed:
                    self.hud.hideAfter(delay: 0.4)
                case .level, .transcribing, .subscribed:
                    break
                }
            }
        }
        client.start()

        // Make sure the daemon is up at startup, so the first hotkey
        // press doesn't pay full cold-start. (The daemon idle-reapers
        // models internally if unused for 30 min; the process itself
        // stays alive.)
        DaemonLauncher.ensureRunning()

        // Register Ctrl+Opt+V as our global hotkey.
        hotkey = HotKey(keyCode: UInt32(kVK_ANSI_V), modifiers: [.control, .option])
        hotkey.onPressed = { [weak self] in
            self?.handleHotkey()
        }
        if !hotkey.register() {
            NSLog("VoiceCLIVisual: failed to register Ctrl+Opt+V hotkey")
        } else {
            NSLog("VoiceCLIVisual: Ctrl+Opt+V registered")
        }

        // Menu bar status item — gives a way to quit, toggle login item,
        // and verify the app is running. Since LSUIElement=true we have
        // no Dock icon, so this is the only visible affordance.
        installStatusItem()
    }

    private func handleHotkey() {
        // If the daemon isn't running, spawn it now. The toggle send
        // races with the daemon coming up — that's fine on first press
        // (slow), but every subsequent press hits a warm daemon.
        DaemonLauncher.ensureRunning()
        client.sendToggle()
    }

    private func installStatusItem() {
        statusItem = NSStatusBar.system.statusItem(withLength: NSStatusItem.variableLength)
        if let button = statusItem.button {
            button.title = "🎤"
            button.toolTip = "VoiceCLI — Ctrl+Opt+V to dictate"
        }
        let menu = NSMenu()
        menu.addItem(NSMenuItem(title: "Voice CLI is listening for ⌃⌥V",
                                action: nil, keyEquivalent: ""))
        menu.addItem(.separator())
        let loginItem = NSMenuItem(title: "Open at Login",
                                   action: #selector(toggleLoginItem(_:)),
                                   keyEquivalent: "")
        loginItem.target = self
        loginItem.state = (SMAppService.mainApp.status == .enabled) ? .on : .off
        menu.addItem(loginItem)
        menu.addItem(.separator())
        let quit = NSMenuItem(title: "Quit", action: #selector(NSApp.terminate(_:)), keyEquivalent: "q")
        menu.addItem(quit)
        statusItem.menu = menu
    }

    @objc private func toggleLoginItem(_ sender: NSMenuItem) {
        let service = SMAppService.mainApp
        do {
            if service.status == .enabled {
                try service.unregister()
                sender.state = .off
            } else {
                try service.register()
                sender.state = .on
            }
        } catch {
            NSLog("VoiceCLIVisual: SMAppService toggle failed: \(error)")
        }
    }

    func applicationShouldTerminateAfterLastWindowClosed(_ sender: NSApplication) -> Bool {
        false
    }
}
