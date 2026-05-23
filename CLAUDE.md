# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

VoiceType is a macOS voice-to-text tool for terminal sessions. Press a hotkey, speak, and text appears at your cursor. Uses Silero VAD for intelligent speech detection and multiple transcription backends.

## Commands

```bash
# Install/setup
./setup.sh

# Run directly (uses venv)
~/.voice-cli-venv/bin/python bin/voice-cli

# Debug mode (prints instead of typing)
~/.voice-cli-venv/bin/python bin/voice-cli --debug

# Test with fixed duration (bypass VAD)
~/.voice-cli-venv/bin/python bin/voice-cli --no-vad --duration 3

# Test LLM refinement directly
~/.voice-cli-venv/bin/python -c "
from src.llm_refine import refine_text
result = refine_text('um so like add a button', 'claude', {'llm_backend': 'ollama', 'ollama_model': 'gemma2:2b'})
print(result)
"
```

No test suite exists yet.

## Architecture

```
Raycast hotkey → voice-toggle.sh → bin/voice-cli-client
                                        │
                  ┌─────────────────────┴──────────────────────┐
                  │ fast path                  fallback path   │
                  ▼                                            ▼
       Unix socket → src/daemon.py        bin/voice-cli (standalone)
                  │                                            │
                  └──────────── src/session.py ────────────────┘
                                        │
                              src/vad_record.py (Silero VAD)
                                        ↓
                    ┌───────────────────┼───────────────────┐
                    ↓                   ↓                   ↓
            mlx_transcribe.py   transcribe.py      groq_transcribe.py
            (MLX - fastest)     (faster-whisper)   (Groq cloud API)
                    └───────────────────┼───────────────────┘
                                        ↓
                              llm_refine.py (optional, trigger-based)
                                        ↓
                              number_words.py (optional)
                                        ↓
                              output.py (clipboard + osascript paste)
```

**Daemon mode (default since 2026-05-23):** `bin/voice-cli-client` is what
the hotkey actually runs. It sends `{"op":"toggle"}` to `src/daemon.py`
over the Unix socket at `~/.voice-cli/voice-cli.sock`. The daemon keeps
the VAD + MLX models preloaded in RAM (~250MB), so toggle round-trip is
~1ms vs ~1.5s for a cold `bin/voice-cli` invocation.

If the daemon isn't running (e.g. first press of a session, crash), the
client spawns it in the background and falls back to `bin/voice-cli` for
that one press. The next press hits the now-warm daemon.

To restart the daemon: `pkill -f "python -m daemon"`; next hotkey press
will respawn it. To stop it without restart: send `{"op":"shutdown"}` over
the socket.

### Additional hotkeys (Raycast scripts)

- `raycast/voice-toggle.sh` — start/stop a recording (the main hotkey)
- `raycast/voice-replay.sh` — re-paste the most recent transcript (useful
  when Cmd+V silently failed in some Electron field)
- `raycast/voice-revert.sh` — delete the last LLM-cleaned transcript and
  paste the pre-cleanup raw version (best-effort: assumes cursor is
  still where the cleaned text ended)

The replay/revert hotkeys only work while the daemon is running, since
they read from in-memory transcript history (last 10 sessions).

### Personal dictionary

Drop one term per line in `~/.voice-cli/dictionary.txt` (project names,
repos, weird jargon, people-names). The file is read each session and
passed to Whisper as `initial_prompt`, which biases transcription toward
those terms. Lines starting with `#` are ignored.

### Visual HUD (swift/)

A separate SwiftUI app (`VoiceCLIVisual`) subscribes to the daemon's
socket and renders a floating audio-reactive blob during recording. See
`swift/README.md` for build/run. It subscribes via `{"op":"subscribe"}`
and receives newline-delimited JSON events:

| Event | Fired by |
|-------|----------|
| `recording_started` | session start |
| `level` (0–1)       | each Silero VAD chunk during recording |
| `transcribing`      | record_end, before finalize |
| `paste_done`        | after clipboard paste |
| `recording_ended`   | after the Pop sound |
| `session_failed`    | exception in the streaming path |

The protocol is fan-out: multiple subscribers can connect simultaneously.
Disconnections are detected on next write and the daemon drops them.

### Transcription Backends

| Mode | Speed | Requires | Notes |
|------|-------|----------|-------|
| `mlx` | Fastest | Apple Silicon | Default. May cause crashes on some systems |
| `groq` | Fast | API key | Cloud-based, most reliable |
| `local` | Slower | CPU | faster-whisper, fallback option |

### LLM Refinement (Speech Cleanup)

Cleans transcribed speech by removing filler words (um, uh, like, etc.) when trigger phrases are detected.

**Trigger phrases** (say at END of speech):
- "for claude", "for claude code", "for clawde", "for clawed code" → claude mode
- "for chatgpt", "for gpt" → chatgpt mode
- "for code", "for codex" → code mode

**Backends** (configured in config.yaml):
- `auto` - Tries Ollama first, falls back to Groq
- `ollama` - Local only (requires `ollama serve`)
- `groq` - Cloud only (requires GROQ_API_KEY)

**Recommended Ollama models**:
- `gemma2:2b` - Fast (~0.5s), good for simple cleanup, no preambles
- `qwen3:4b-instruct-2507-q4_K_M` - Slower (~1.5s), better at preserving meaning

**Important**: Do NOT use `qwen3:4b` (base) - it has thinking mode enabled by default causing 30+ second delays. Use the `-instruct` variant instead.

### Key Data Flow

1. **Recording**: `vad_record.py` uses PyAudio + Silero VAD to record until silence (32ms chunks, 512 samples at 16kHz)
2. **Transcription**: Depends on `transcription_mode` in config
3. **LLM Refinement**: If trigger phrase detected, cleans up speech via Ollama/Groq
4. **Output**: `output.py` copies to clipboard, activates original app, pastes via Cmd+V

### Critical Implementation Details

- **VAD chunk size**: Silero VAD requires exactly 512 samples at 16kHz (32ms). Other sizes will error.
- **Model pre-loading**: VAD model must load BEFORE the Ping sound plays, otherwise first words get missed
- **Async sound**: `play_sound()` uses `subprocess.Popen` (not `.run`) to avoid blocking recording start
- **Enter triggers**: `check_enter_trigger()` strips punctuation (`.!?,;:`) before checking for "send"/"enter"
- **Whisper mishearing**: Whisper often transcribes "Claude" as "clawde" or "clawed" - trigger detection handles this
- **Qwen3 thinking mode**: Must pass `"think": False` in Ollama API payload to disable thinking mode

### File Storage

| File | Purpose | Accumulates? |
|------|---------|--------------|
| `~/.voice-cli/config.yaml` | User settings | No |
| `~/.voice-cli/recording.wav` | Temp audio | No (overwritten each time) |
| `~/.voice-cli/raycast.log` | Debug logs | Yes (may need cleanup) |
| `~/.voice-cli/voice-cli.lock` | Prevents double-run | No |

**Transcripts are NOT stored** - they go directly to clipboard.

### Configuration

User config: `~/.voice-cli/config.yaml`

Key settings:
```yaml
# Transcription mode: mlx (fastest), groq (cloud), local (fallback)
transcription_mode: mlx

# MLX/local models: distil-small.en (fastest), distil-medium.en (balanced)
model: distil-medium.en

# LLM refinement (speech cleanup)
llm_refinement: true
llm_backend: auto  # auto, ollama, or groq
ollama_model: gemma2:2b  # or qwen3:4b-instruct-2507-q4_K_M
```

### Environment Variables

Create `.env` file in project root (loaded automatically):
```bash
GROQ_API_KEY=gsk_...  # Required for groq transcription or LLM fallback
```

## macOS Permissions

Raycast needs both Microphone and Accessibility permissions (not the terminal) because Raycast spawns the subprocess.

## Ollama Setup

```bash
# Install Ollama
brew install ollama

# Start server (required for local LLM refinement)
ollama serve

# Pull recommended models
ollama pull gemma2:2b                          # Fast, no preambles
ollama pull qwen3:4b-instruct-2507-q4_K_M      # Better quality

# Models stored in: ~/.ollama/models/
# Server runs on: http://localhost:11434
```

## Known Issues

1. **Mac crashes during transcription**: MLX mode with distil-medium.en may cause system crashes on some configurations. Try switching to `groq` mode or using `distil-small.en`.

2. **Groq 403 errors**: Check GROQ_API_KEY is set correctly in `.env` file.

3. **Ollama connection refused**: Run `ollama serve` before using Ollama backend.

4. **Qwen3 30+ second delays**: Use `qwen3:4b-instruct-*` variant, not base `qwen3:4b`.

## System Prompt Design (for LLM refinement)

The prompts in `src/llm_refine.py` are optimized for small models (2B-4B params):

- **Context**: "Clean transcribed speech for a coding assistant"
- **Positive framing**: "Output only X" instead of "Do NOT do Y"
- **Examples**: 5 input/output pairs guide the model
- **Filler words**: um, uh, like, you know, so, basically, I mean, okay, well, right, actually, yeah

The prompts are CONSERVATIVE - they clean up speech without adding assumptions about technology or approach, because Claude Code already has full project context.
