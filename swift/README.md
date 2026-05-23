# VoiceCLIVisual — SwiftUI HUD for voice-cli

A floating, audio-reactive blob that appears while voice-cli is recording. Siri-style organic morph, driven by live audio levels streamed from the daemon over its Unix socket. Replaces the menubar `🔴` dot with something actually pleasant to look at.

## How it works

```
Raycast hotkey → voice-cli-client → daemon (records + transcribes)
                                       │
                                       │  publishes events:
                                       │    {"event":"recording_started"}
                                       │    {"event":"level","value":0.42}
                                       │    {"event":"transcribing"}
                                       │    {"event":"paste_done","text":"..."}
                                       ▼
                                  Unix socket  ←─── VoiceCLIVisual subscribes
                                                    via {"op":"subscribe"}
                                                    │
                                                    ▼
                                              SwiftUI NSPanel
                                              (animated blob)
```

The daemon is the source of truth — it broadcasts session events to any subscribed socket. VoiceCLIVisual is just one consumer; you could write a CLI sniffer or web dashboard against the same protocol.

## Build & run

```bash
cd swift
swift build -c release
.build/release/VoiceCLIVisual &
```

Leave it running in the background — it will auto-reconnect if the daemon is restarted. Quit with `pkill -f VoiceCLIVisual` or `kill %1` if you started it as a job.

## Auto-launch at login

Add to `~/Library/LaunchAgents/com.voicecli.visual.plist`:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>          <string>com.voicecli.visual</string>
    <key>ProgramArguments</key>
    <array>
        <string>/Users/avini/Documents/GitHub/voice-cli/swift/.build/release/VoiceCLIVisual</string>
    </array>
    <key>RunAtLoad</key>      <true/>
    <key>KeepAlive</key>      <true/>
</dict>
</plist>
```

Then `launchctl bootstrap gui/$UID ~/Library/LaunchAgents/com.voicecli.visual.plist`.

## Files

- `Package.swift` — SPM manifest, Swift 5 language mode (Swift 6 strict concurrency complained about the long-lived `DaemonClient` class)
- `Sources/VoiceCLIVisual/main.swift` — NSApplication setup, `.accessory` activation (no dock icon)
- `Sources/VoiceCLIVisual/AppDelegate.swift` — wires together HUDWindow + DaemonClient + ViewModel
- `Sources/VoiceCLIVisual/HUDWindow.swift` — borderless NSPanel + show/hide lifecycle
- `Sources/VoiceCLIVisual/DaemonClient.swift` — Unix-socket subscriber, auto-reconnect, EMA-smoothed levels
- `Sources/VoiceCLIVisual/BlobView.swift` — SwiftUI Canvas drawing the morphing blob

## Customising the visual

`BlobView.swift` is where the look lives:

- **Colour palette** — `gradient(for:level:)` defines listening (cyan→indigo) and transcribing (amber→magenta). Edit those `Color(red:green:blue:)` calls.
- **Wobble intensity** — `energy` variable controls how dramatically the blob morphs with audio level.
- **Spin speed** — `spinSpeed` controls how fast the noise pattern rotates.
- **Size** — `baseRadius` multiplier on the canvas size.
- **Halo** — `haloR` and `haloColor()` control the faint outer glow.

## Why a separate Swift app?

- Native macOS animations look better than anything we could fake from Python+rumps.
- The HUD never touches PyAudio or the model — it's purely a subscriber. Crashes in the HUD can never affect a recording session.
- Future polish (window per-screen, settings UI, fancier visuals) lives here cleanly.
