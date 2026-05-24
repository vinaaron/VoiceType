import Carbon
import AppKit

/// Global hotkey registration via the Carbon RegisterEventHotKey API.
/// Carbon's hotkey API is still the standard way for native macOS apps to
/// register system-wide hotkeys — it doesn't require Accessibility
/// permission (that's only needed if you also want to *consume* keys
/// via CGEventTap). Works on macOS 26.
///
/// Usage:
///     let hk = HotKey(keyCode: UInt32(kVK_ANSI_V), modifiers: [.control, .option])
///     hk.onPressed = { ... }
///     hk.register()
final class HotKey {
    struct Modifiers: OptionSet {
        let rawValue: UInt32
        static let command  = Modifiers(rawValue: UInt32(cmdKey))
        static let option   = Modifiers(rawValue: UInt32(optionKey))
        static let control  = Modifiers(rawValue: UInt32(controlKey))
        static let shift    = Modifiers(rawValue: UInt32(shiftKey))
    }

    let keyCode: UInt32
    let modifiers: Modifiers
    var onPressed: (() -> Void)?

    private var hotKeyRef: EventHotKeyRef?
    private static var nextHotKeyID: UInt32 = 1
    private static var registry: [UInt32: HotKey] = [:]
    private static var handlerInstalled = false

    init(keyCode: UInt32, modifiers: Modifiers) {
        self.keyCode = keyCode
        self.modifiers = modifiers
    }

    /// Install the process-wide Carbon event handler that dispatches
    /// kEventHotKeyPressed to the right HotKey instance via its ID.
    private static func ensureHandlerInstalled() {
        guard !handlerInstalled else { return }
        handlerInstalled = true

        var eventSpec = EventTypeSpec(
            eventClass: OSType(kEventClassKeyboard),
            eventKind: UInt32(kEventHotKeyPressed)
        )
        InstallEventHandler(
            GetApplicationEventTarget(),
            { _, eventRef, _ -> OSStatus in
                guard let eventRef else { return noErr }
                var hkID = EventHotKeyID()
                let status = GetEventParameter(
                    eventRef,
                    EventParamName(kEventParamDirectObject),
                    EventParamType(typeEventHotKeyID),
                    nil,
                    MemoryLayout<EventHotKeyID>.size,
                    nil,
                    &hkID
                )
                if status == noErr, let hk = HotKey.registry[hkID.id] {
                    DispatchQueue.main.async { hk.onPressed?() }
                }
                return noErr
            },
            1,
            &eventSpec,
            nil,
            nil
        )
    }

    /// Register this hotkey with the system. Returns true on success.
    @discardableResult
    func register() -> Bool {
        Self.ensureHandlerInstalled()
        let myID = Self.nextHotKeyID
        Self.nextHotKeyID += 1

        let hotKeyID = EventHotKeyID(signature: OSType(0x76636C69), id: myID) // 'vcli'
        var ref: EventHotKeyRef?
        let status = RegisterEventHotKey(
            keyCode,
            modifiers.rawValue,
            hotKeyID,
            GetApplicationEventTarget(),
            0,
            &ref
        )
        if status == noErr, let ref {
            self.hotKeyRef = ref
            Self.registry[myID] = self
            return true
        }
        NSLog("VoiceCLIVisual: RegisterEventHotKey failed status=\(status)")
        return false
    }

    deinit {
        if let hotKeyRef {
            UnregisterEventHotKey(hotKeyRef)
        }
    }
}
