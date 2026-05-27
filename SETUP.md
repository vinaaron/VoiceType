# Setting up VoiceCLI on a new Mac

A solo-dev voice-to-text app. Press a hotkey, speak, transcript pastes
into your focused app. Streaming Moonshine v2 on Apple Silicon so the
end-of-speech latency is ~150 ms regardless of utterance length.

This guide assumes a fresh Apple Silicon Mac running macOS 26 (Tahoe)
or newer. Most things will work on macOS 14+ but the floating Liquid
Glass HUD needs 26.

## Prerequisites

- **Apple Silicon Mac** — required for MLX (Moonshine streaming) +
  the macOS 26 Glass HUD.
- **Homebrew** — install from <https://brew.sh>.
- **Python 3.11, 3.12, or 3.13** — 3.14 has compatibility issues with
  some pip dependencies. `brew install python@3.13` works.
- **Swift toolchain (Xcode or Command Line Tools)** — `xcode-select --install`
  if missing. The app needs `swift build`.

## Install

```bash
git clone https://github.com/vinaaron/VoiceType.git
cd VoiceType
./setup.sh
```

What `setup.sh` does, in order:

1. Installs `sox` and `portaudio` (audio capture) via Homebrew
2. Creates a Python venv at `~/.voice-cli-venv`
3. Installs requirements: `silero-vad`, `faster-whisper`, `pyaudio`,
   `lightning-whisper-mlx`, `moonshine-voice`, plus deps
4. Pre-downloads Whisper base.en + Silero VAD model weights (~50 MB)
5. Creates default config at `~/.voice-cli/config.yaml`
6. Marks `bin/voice-cli` executable
7. Builds `swift/VoiceCLIVisual.app` and installs to `~/Applications/`

The Swift build also ad-hoc-codesigns the .app so macOS remembers
permissions you grant it.

## First-run permissions

Open `~/Applications/VoiceCLIVisual.app` (or it auto-opens at the end
of setup). Look for the 🎤 icon in your menu bar.

Press your hotkey (default ⌃⌥V = Control+Option+V). On the very first
press, macOS will prompt twice:

1. **Microphone access** — the daemon needs this to record. Click *Allow*.
2. **Accessibility access** — needed to paste the transcript via
   keystroke. Click *Open System Settings*, toggle VoiceCLIVisual on
   in the Accessibility list.

After that, no more prompts. The daemon process inherits the grants
because it was spawned by VoiceCLIVisual.app.

## Auto-launch at login

Click 🎤 in the menu bar → **Open at Login** (a checkmark appears).
VoiceCLIVisual will now start every time you log in.

Alternatively: System Settings → General → Login Items → Open at Login
→ add `~/Applications/VoiceCLIVisual.app`.

## Changing the hotkey

Edit `~/.voice-cli/config.yaml`:

```yaml
swift_hotkey:
  key: V                          # A-Z, 0-9, F1-F12, Space, Return, Tab, Escape
  modifiers: [control, option]    # any subset of: command, control, option, shift
```

Restart the app (menu 🎤 → Quit, then open it again, or run
`swift/make_app.sh open` from the repo). No rebuild needed.

## Architecture (so you know what to debug)

```
⌃⌥V hotkey  →  VoiceCLIVisual.app (Carbon RegisterEventHotKey)
                       │
                       │ sends {"op":"toggle"} over Unix socket
                       ▼
                ~/.voice-cli/voice-cli.sock
                       │
                       ▼
                src/daemon.py (long-running, in venv)
                       │
                       │ records via PyAudio + Silero VAD
                       │ transcribes via Moonshine v2 streaming
                       │ pastes via osascript Cmd+V
                       │
                       │ broadcasts session events back over the socket:
                       │   {"event":"level","value":0.42}
                       │   {"event":"transcribing"}
                       ▼
                VoiceCLIVisual.app subscribes, renders the blob HUD
```

The daemon stays alive across sessions (idle reaper unloads the MLX
model after 30 min of inactivity, but the daemon process itself
persists). Memory baseline: ~580 MB resident with models loaded.

## Important files

| Path | What it is |
|---|---|
| `~/.voice-cli/config.yaml` | All user settings: model, hotkey, triggers, dictionary |
| `~/.voice-cli/dictionary.txt` | One term per line — boosts Whisper accuracy on your jargon. Optional. |
| `~/.voice-cli/raycast.log` | Stage timings + errors. Auto-rotated to last 2000 lines. |
| `~/.voice-cli/voice-cli.sock` | Unix socket — daemon ⇄ Swift app |
| `~/.voice-cli/daemon.pid` | Daemon's PID file |

## Troubleshooting

**Hotkey doesn't fire**: Open the menu bar 🎤. If it's missing,
VoiceCLIVisual isn't running — open it from `~/Applications/`. If it's
there but pressing the hotkey does nothing, check Console.app for
`VoiceCLIVisual: RegisterEventHotKey failed` — another app may be
holding the same key (Spotlight, Raycast, etc.). Change the key in
config.yaml.

**Recording works but nothing pastes**: Tail `~/.voice-cli/raycast.log`
and re-press the hotkey. Look for `osascript ... failed` lines — those
are now logged explicitly. The two common causes are:

- `(1002) osascript is not allowed to send keystrokes` → grant
  Accessibility to VoiceCLIVisual in System Settings.
- `(-1728) Can't get application ...` → activate_app couldn't focus
  the target app. Should auto-recover; if not, file an issue.

**Daemon won't restart**: `pkill -if "python -m daemon"` (the `-i` is
critical, the process name is `Python` not `python`). Next hotkey press
will respawn it via VoiceCLIVisual's `DaemonLauncher`.

**Transcription quality is poor on your jargon**: Add terms to
`~/.voice-cli/dictionary.txt`, one per line. They get passed to
Moonshine/Whisper as the `initial_prompt`.

## Bringing it to a second laptop

Same steps as above. The repo is the source of truth; clone, run
`setup.sh`, grant permissions, done. No syncing of credentials or
settings — everything lives in the repo and `~/.voice-cli/`.

If you want to copy your `~/.voice-cli/config.yaml` and
`dictionary.txt` over from machine A: just `scp` or copy them
manually. The model weights are downloaded fresh from the network.
