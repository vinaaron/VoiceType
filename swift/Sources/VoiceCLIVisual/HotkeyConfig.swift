import Foundation
import Carbon
import Yams

/// Reads the user's hotkey preferences from ~/.voice-cli/config.yaml.
/// Falls back to ⌃⌥V (Ctrl+Opt+V) if the config is missing or invalid.
///
/// Expected YAML:
///
///   swift_hotkey:
///     key: V                  # single letter, digit, or named key
///     modifiers: [control, option]   # any subset of: command, control, option, shift
///
/// Restart VoiceCLIVisual.app after editing for the change to take effect.
enum HotkeyConfig {
    struct Resolved {
        let keyCode: UInt32
        let modifiers: HotKey.Modifiers
        let display: String  // for menubar tooltip etc.
    }

    static let defaultResolved = Resolved(
        keyCode: UInt32(kVK_ANSI_V),
        modifiers: [.control, .option],
        display: "⌃⌥V"
    )

    static func load() -> Resolved {
        let home = FileManager.default.homeDirectoryForCurrentUser.path
        let configPath = "\(home)/.voice-cli/config.yaml"
        guard FileManager.default.fileExists(atPath: configPath),
              let text = try? String(contentsOfFile: configPath, encoding: .utf8) else {
            NSLog("VoiceCLIVisual: no config.yaml, using default ⌃⌥V")
            return defaultResolved
        }

        do {
            guard let yaml = try Yams.load(yaml: text) as? [String: Any],
                  let block = yaml["swift_hotkey"] as? [String: Any] else {
                NSLog("VoiceCLIVisual: config.yaml has no swift_hotkey block, using ⌃⌥V")
                return defaultResolved
            }
            return parse(block) ?? defaultResolved
        } catch {
            NSLog("VoiceCLIVisual: config.yaml parse error: \(error)")
            return defaultResolved
        }
    }

    private static func parse(_ block: [String: Any]) -> Resolved? {
        let keyName = (block["key"] as? String) ?? "V"
        let mods = (block["modifiers"] as? [String]) ?? []
        guard let keyCode = keyCodeMap[keyName.uppercased()] else {
            NSLog("VoiceCLIVisual: unknown key '\(keyName)', falling back to V")
            return nil
        }
        var modifiers: HotKey.Modifiers = []
        var display = ""
        for m in mods {
            switch m.lowercased() {
            case "command", "cmd":      modifiers.insert(.command); display += "⌘"
            case "control", "ctrl":     modifiers.insert(.control); display += "⌃"
            case "option", "opt", "alt":modifiers.insert(.option);  display += "⌥"
            case "shift":               modifiers.insert(.shift);   display += "⇧"
            default:
                NSLog("VoiceCLIVisual: unknown modifier '\(m)'")
            }
        }
        return Resolved(keyCode: keyCode, modifiers: modifiers,
                        display: display + keyName.uppercased())
    }

    /// Map of human-readable key names → Carbon kVK_* constants.
    /// Covers the keys anyone reasonably wants for a dictation hotkey.
    private static let keyCodeMap: [String: UInt32] = [
        // Letters
        "A": UInt32(kVK_ANSI_A), "B": UInt32(kVK_ANSI_B), "C": UInt32(kVK_ANSI_C),
        "D": UInt32(kVK_ANSI_D), "E": UInt32(kVK_ANSI_E), "F": UInt32(kVK_ANSI_F),
        "G": UInt32(kVK_ANSI_G), "H": UInt32(kVK_ANSI_H), "I": UInt32(kVK_ANSI_I),
        "J": UInt32(kVK_ANSI_J), "K": UInt32(kVK_ANSI_K), "L": UInt32(kVK_ANSI_L),
        "M": UInt32(kVK_ANSI_M), "N": UInt32(kVK_ANSI_N), "O": UInt32(kVK_ANSI_O),
        "P": UInt32(kVK_ANSI_P), "Q": UInt32(kVK_ANSI_Q), "R": UInt32(kVK_ANSI_R),
        "S": UInt32(kVK_ANSI_S), "T": UInt32(kVK_ANSI_T), "U": UInt32(kVK_ANSI_U),
        "V": UInt32(kVK_ANSI_V), "W": UInt32(kVK_ANSI_W), "X": UInt32(kVK_ANSI_X),
        "Y": UInt32(kVK_ANSI_Y), "Z": UInt32(kVK_ANSI_Z),
        // Digits
        "0": UInt32(kVK_ANSI_0), "1": UInt32(kVK_ANSI_1), "2": UInt32(kVK_ANSI_2),
        "3": UInt32(kVK_ANSI_3), "4": UInt32(kVK_ANSI_4), "5": UInt32(kVK_ANSI_5),
        "6": UInt32(kVK_ANSI_6), "7": UInt32(kVK_ANSI_7), "8": UInt32(kVK_ANSI_8),
        "9": UInt32(kVK_ANSI_9),
        // Function & special
        "F1": UInt32(kVK_F1), "F2": UInt32(kVK_F2), "F3": UInt32(kVK_F3),
        "F4": UInt32(kVK_F4), "F5": UInt32(kVK_F5), "F6": UInt32(kVK_F6),
        "F7": UInt32(kVK_F7), "F8": UInt32(kVK_F8), "F9": UInt32(kVK_F9),
        "F10": UInt32(kVK_F10), "F11": UInt32(kVK_F11), "F12": UInt32(kVK_F12),
        "SPACE": UInt32(kVK_Space),
        "RETURN": UInt32(kVK_Return),
        "TAB": UInt32(kVK_Tab),
        "ESC": UInt32(kVK_Escape), "ESCAPE": UInt32(kVK_Escape),
    ]
}
