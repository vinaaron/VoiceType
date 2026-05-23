# Daemon Mode

> **Status (2026-05-23):** The lazy-start daemon described below has shipped.
> `bin/voice-cli-client` is what the Raycast hotkey runs; it talks to
> `src/daemon.py` over `~/.voice-cli/voice-cli.sock`. The daemon auto-spawns
> on first press of a session and stays alive until reboot. **launchd
> integration is the optional next step** — see the bottom of this doc.

## Why daemon mode

Every Option+Cmd+V press currently cold-starts Python: venv activation, module imports, VAD model load. Even with lazy imports and the `silence_duration: 1.2` cut, the unavoidable Python startup + `silero_vad` load is **~1–2 seconds** before the Ping sound. A long-lived background process keeps interpreter state and the VAD model warm so the hotkey response feels instant.

This is deferred from the main `voice-cli` cleanup because it's a real architecture shift and the quick wins already deliver most of the perceived speedup. Revisit when the residual startup cost feels worse than the operational complexity of running a background process.

## Architecture sketch

```
Raycast hotkey ──► voice-toggle.sh ──► voice-cli-client (thin)
                                              │
                                       (Unix socket / signal)
                                              ▼
                                      voice-cli-daemon
                                      (managed by launchd)
                                              │
                                              ▼
                              already-loaded VAD + Whisper models
```

### Components

1. **`voice-cli-daemon`** — long-running Python process started by launchd at login.
   - Loads `silero_vad` once, keeps it cached.
   - Optionally pre-loads the MLX Whisper model (still lazy on first record if we want to avoid memory cost when idle).
   - Listens on `~/.voice-cli/voice-cli.sock` (Unix domain socket) for one-line JSON commands: `{"op":"toggle"}`, `{"op":"status"}`.

2. **`voice-cli-client`** — tiny script that the hotkey actually runs.
   - Connects to the socket, sends `{"op":"toggle"}`, prints any response.
   - Falls back to spawning the standalone `voice-cli` if the socket doesn't exist (so the system stays usable if the daemon crashed).

3. **`voice-cli-daemon.plist`** — launchd agent at `~/Library/LaunchAgents/com.avini.voicecli.daemon.plist`. `RunAtLoad = true`, `KeepAlive = true`.

### Toggle semantics

- First `{"op":"toggle"}`: daemon spawns a recording session (thread or asyncio task) and replies `{"state":"recording","session":"abc"}`.
- Second `{"op":"toggle"}` while a session is active: daemon sets the existing session's `stop_event` and replies `{"state":"stopping","session":"abc"}`. Same code path as the current SIGUSR1 toggle, just routed via socket instead of POSIX signals.
- The session continues through transcribe → LLM refine → paste in the daemon process. Notifications and `terminal-notifier` calls work identically.

### Why a socket, not signals

PIDfile + SIGUSR1 (the current design) works for two short-lived processes but is awkward when only one process exists. A socket gives:
- Structured replies (state, error messages) — the client can print them or surface them as notifications.
- Multiple op types without spreading signal numbers (`toggle`, `cancel`, `status`, `reload-config`).
- Auth-by-filesystem (the socket lives under `~/.voice-cli/`, only the user can connect).

## Migration path

The current PID+SIGUSR1 design becomes the **fallback path** when the daemon isn't running — so nothing breaks if the daemon crashes or is intentionally stopped.

1. Ship a `voice-cli-daemon` script that reuses `src/vad_record.py`, `src/llm_refine.py`, `src/output.py` as-is.
2. Reuse `bin/voice-cli` as the fallback binary; `voice-toggle.sh` first tries the socket, then falls back to `bin/voice-cli` if the connection fails.
3. Add `~/Library/LaunchAgents/com.avini.voicecli.daemon.plist`; `setup.sh` installs and loads it (`launchctl bootstrap gui/$UID …`).

## Open questions

- **Idle memory cost.** Silero VAD is small (~2MB). MLX Whisper distil-medium is ~250MB resident. Decide whether to keep MLX loaded between sessions or unload after N minutes of idle.
- **Microphone permission**. macOS prompts the *process* that opens the audio stream. The first time the daemon records, it'll prompt for permission — same as Raycast does today. Document this in setup.
- **Daemon crash recovery.** `KeepAlive` restarts the daemon, but in-flight recording is lost. The fallback path covers the next press while the daemon comes back up.
- **Config reloads.** Either re-read `config.yaml` on every toggle (simple, slight cost) or expose a `reload-config` socket op.

## Estimated effort

~1 day of focused work:
- 3 hours: daemon + socket protocol + thin client
- 2 hours: launchd plist + setup.sh integration
- 2 hours: socket-fallback wiring in `voice-toggle.sh`
- 1 hour: end-to-end test (login restart, kill -9 the daemon, etc.)
