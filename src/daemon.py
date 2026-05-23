"""
Voice CLI daemon.

Long-running process that keeps the VAD (and optionally MLX) models loaded
in memory so hotkey presses skip Python cold-start and model load latency.
Listens on a Unix socket at ~/.voice-cli/voice-cli.sock and accepts one-line
JSON commands:

    {"op": "toggle"}   — start a session, or stop the active one
    {"op": "status"}   — report whether a session is active
    {"op": "shutdown"} — graceful exit (mainly for tests)

The session pipeline (record → transcribe → paste) is delegated to
src/session.run_voice_session, so behaviour matches bin/voice-cli exactly.
"""

import json
import os
import signal
import socket
import subprocess
import sys
import threading
import time
from collections import deque
from pathlib import Path

SRC_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SRC_DIR)

try:
    from dotenv import load_dotenv
    for env_path in [
        os.path.join(os.path.dirname(SRC_DIR), ".env"),
        os.path.expanduser("~/.voice-cli/.env"),
    ]:
        if os.path.exists(env_path):
            load_dotenv(env_path)
            break
except ImportError:
    pass

from logger import get_logger, log_stage, log_info, log_error
from session import run_voice_session

SOCK_PATH = Path.home() / ".voice-cli" / "voice-cli.sock"
PIDFILE = Path.home() / ".voice-cli" / "daemon.pid"

_state_lock = threading.Lock()
_current_session: "Session | None" = None
_shutdown_event = threading.Event()
_last_activity = time.monotonic()  # bumped each time a command arrives
_transcript_history: deque = deque(maxlen=10)  # recent finished sessions for revert/replay


class Session:
    """One recording-→-paste run, owned by the daemon."""

    def __init__(self, config: dict):
        self.config = config
        self.stop_event = threading.Event()
        self.thread = threading.Thread(target=self._run, daemon=False)
        self.started_at = time.monotonic()

    def start(self):
        self.thread.start()

    def stop(self):
        self.stop_event.set()

    def alive(self) -> bool:
        return self.thread.is_alive()

    def _run(self):
        try:
            result = run_voice_session(self.config, self.stop_event, models_preloaded=True)
            if result.get("ok"):
                with _state_lock:
                    _transcript_history.append({
                        "final": result.get("text", ""),
                        "raw": result.get("raw", ""),
                        "llm_mode": result.get("llm_mode"),
                        "target_app": result.get("target_app"),
                        "at": time.time(),
                    })
        except Exception as e:
            log_error(f"session crashed: {e}")
            import traceback
            traceback.print_exc(file=sys.stderr)
        finally:
            global _current_session
            with _state_lock:
                if _current_session is self:
                    _current_session = None


def load_config() -> dict:
    """Same config loader as bin/voice-cli, duplicated here to avoid importing
    a file from bin/ (which has shebang + argparse, not import-friendly)."""
    import json as _json
    config_dir = os.path.expanduser("~/.voice-cli")
    yaml_path = os.path.join(config_dir, "config.yaml")
    json_path = os.path.join(config_dir, "config.json")

    defaults = {
        "model": "distil-medium.en",
        "transcription_mode": "mlx",
        "groq_api_key": None,
        "silence_duration": 1.2,
        "silence_threshold": "1%",
        "sound_feedback": True,
        "convert_numbers": True,
        "show_notifications": True,
        "show_recording_indicator": True,
        "vad_mode": True,
        "vad_threshold": 0.5,
        "max_duration": 300,
        "duration": 5.0,
        "auto_enter": True,
        "enter_triggers": ["enter", "send", "submit", "return"],
        "llm_refinement": True,
        "llm_backend": "groq",
        "llm_model": "llama-3.3-70b-versatile",
        "ollama_url": "http://localhost:11434",
        "llm_triggers": None,
        "daemon_mlx_idle_minutes": 30,
    }
    if os.path.exists(yaml_path):
        try:
            import yaml
            with open(yaml_path) as f:
                user_config = yaml.safe_load(f) or {}
            defaults.update(user_config)
            return defaults
        except Exception:
            pass
    if os.path.exists(json_path):
        try:
            with open(json_path) as f:
                user_config = _json.load(f) or {}
            defaults.update(user_config)
        except Exception:
            pass
    return defaults


def preload_models(config: dict) -> None:
    """Warm the heavy stuff at daemon startup so the first toggle is fast."""
    log_info("preloading models...")
    if config.get("vad_mode", True):
        from vad_record import get_vad_model
        get_vad_model()
        log_stage("daemon_vad_ready")

    mode = config.get("transcription_mode", "mlx")
    if mode == "moonshine":
        try:
            from moonshine_transcribe import get_moonshine_model
            get_moonshine_model(config)
            log_stage("daemon_moonshine_ready")
        except ImportError:
            log_info("moonshine-voice not installed; will fall back to MLX at runtime")
        except Exception as e:
            log_error(f"Moonshine preload failed: {e}")
        return  # streaming model is what we'll use; skip Whisper preload

    if mode == "parakeet":
        try:
            from parakeet_transcribe import get_parakeet_model
            get_parakeet_model(config.get("parakeet_model", "mlx-community/parakeet-tdt-0.6b-v3"))
            log_stage("daemon_parakeet_ready")
        except ImportError:
            log_info("parakeet-mlx not installed; will fall back to Whisper at runtime")
        except Exception as e:
            log_error(f"Parakeet preload failed: {e}")
        return  # don't also preload Whisper if Parakeet is the chosen mode

    # Pre-load MLX too if that's the transcription mode. This costs ~250MB
    # of RAM idle but makes transcription effectively instant.
    if mode == "mlx":
        try:
            from mlx_transcribe import transcribe_with_mlx  # noqa: F401
            # The module-level cache in mlx_transcribe loads on first call,
            # not on import. We trigger it by transcribing a tiny dummy clip.
            import tempfile, wave, struct
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp_path = tmp.name
            with wave.open(tmp_path, "wb") as wf:
                wf.setnchannels(1)
                wf.setsampwidth(2)
                wf.setframerate(16000)
                wf.writeframes(struct.pack("<" + "h" * 1600, *([0] * 1600)))  # 0.1s silence
            try:
                transcribe_with_mlx(tmp_path, model_name=config["model"])
            except Exception as e:
                log_info(f"MLX warmup skipped: {e}")
            finally:
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass
            log_stage("daemon_mlx_ready")
        except ImportError:
            log_info("MLX not installed; transcription will cold-start on first use")


def _last_transcript_entry() -> dict | None:
    with _state_lock:
        return _transcript_history[-1] if _transcript_history else None


def _paste_text(text: str, target_app: str | None) -> None:
    """Paste text via clipboard. Save/restore the user's clipboard."""
    from output import type_text_via_clipboard
    type_text_via_clipboard(text, target_app=target_app)


def _backspace(n: int) -> None:
    """Issue n Backspace keystrokes via AppleScript. Used by revert to
    delete the just-pasted cleaned text before pasting the raw version."""
    if n <= 0:
        return
    # System Events 'key code 51' = Delete (Backspace). We issue them in
    # chunks of 50 so the AppleScript doesn't time out on very long pastes.
    chunks = (n + 49) // 50
    per_chunk = min(50, n)
    remainder = n - chunks * 50 if n > chunks * 50 else 0
    script_template = '''
    tell application "System Events"
        repeat {COUNT} times
            key code 51
        end repeat
    end tell
    '''
    try:
        for _ in range(chunks):
            cnt = min(50, n)
            n -= cnt
            subprocess.run(
                ["osascript", "-e", script_template.replace("{COUNT}", str(cnt))],
                check=False, capture_output=True, timeout=3.0,
            )
            if n <= 0:
                break
    except Exception as e:
        log_error(f"backspace failed: {e}")


def handle_command(conn: socket.socket) -> None:
    global _current_session, _last_activity
    try:
        conn.settimeout(5.0)
        data = conn.recv(4096).decode("utf-8").strip()
        if not data:
            return
        cmd = json.loads(data)
        op = cmd.get("op")
        _last_activity = time.monotonic()
        log_info(f"daemon recv op={op}")

        if op == "toggle":
            with _state_lock:
                if _current_session is not None and _current_session.alive():
                    _current_session.stop()
                    conn.sendall(b'{"state":"stopping"}\n')
                else:
                    _current_session = Session(load_config())
                    _current_session.start()
                    conn.sendall(b'{"state":"recording"}\n')
        elif op == "status":
            recording = _current_session is not None and _current_session.alive()
            conn.sendall((json.dumps({"recording": recording}) + "\n").encode())
        elif op == "replay":
            entry = _last_transcript_entry()
            if entry is None:
                conn.sendall(b'{"error":"no recent transcript"}\n')
            else:
                _paste_text(entry["final"], entry.get("target_app"))
                conn.sendall((json.dumps({"state": "replayed", "len": len(entry["final"])}) + "\n").encode())
        elif op == "revert":
            entry = _last_transcript_entry()
            if entry is None:
                conn.sendall(b'{"error":"no recent transcript"}\n')
            elif not entry.get("raw") or entry["raw"] == entry["final"]:
                conn.sendall(b'{"error":"last transcript had no LLM cleanup, nothing to revert"}\n')
            else:
                final_len = len(entry["final"])
                _backspace(final_len)
                _paste_text(entry["raw"], entry.get("target_app"))
                conn.sendall((json.dumps({"state": "reverted", "removed": final_len}) + "\n").encode())
        elif op == "shutdown":
            conn.sendall(b'{"state":"shutting_down"}\n')
            _shutdown_event.set()
        else:
            conn.sendall(b'{"error":"unknown op"}\n')
    except Exception as e:
        log_error(f"command handler error: {e}")
        try:
            conn.sendall(json.dumps({"error": str(e)}).encode() + b"\n")
        except OSError:
            pass
    finally:
        try:
            conn.close()
        except OSError:
            pass


def write_daemon_pidfile() -> None:
    PIDFILE.parent.mkdir(parents=True, exist_ok=True)
    PIDFILE.write_text(str(os.getpid()))


def remove_daemon_pidfile() -> None:
    try:
        if PIDFILE.exists() and PIDFILE.read_text().strip() == str(os.getpid()):
            PIDFILE.unlink()
    except OSError:
        pass


def is_daemon_already_running() -> bool:
    if not PIDFILE.exists():
        return False
    try:
        pid = int(PIDFILE.read_text().strip() or "0")
    except (ValueError, OSError):
        return False
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def cleanup_socket() -> None:
    try:
        if SOCK_PATH.exists():
            SOCK_PATH.unlink()
    except OSError:
        pass


def idle_reaper(timeout_seconds: float) -> None:
    """Unload the MLX model when the daemon has been idle for too long.
    The daemon stays alive — only the model is dropped. Next press pays a
    one-time ~3-4s reload cost; subsequent presses are fast again."""
    if timeout_seconds <= 0:
        return
    while not _shutdown_event.is_set():
        _shutdown_event.wait(timeout=60.0)
        if _shutdown_event.is_set():
            break
        idle = time.monotonic() - _last_activity
        if idle < timeout_seconds:
            continue
        with _state_lock:
            if _current_session is not None and _current_session.alive():
                continue  # active recording — don't yank the model out
        try:
            from mlx_transcribe import unload_mlx_model
            mlx_dropped = unload_mlx_model()
        except Exception as e:
            log_error(f"idle reaper MLX unload failed: {e}")
            mlx_dropped = False
        try:
            from parakeet_transcribe import unload_parakeet_model
            parakeet_dropped = unload_parakeet_model()
        except Exception:
            parakeet_dropped = False
        try:
            from moonshine_transcribe import unload_moonshine_model
            moonshine_dropped = unload_moonshine_model()
        except Exception:
            moonshine_dropped = False
        if mlx_dropped or parakeet_dropped or moonshine_dropped:
            log_info(
                f"idle {int(idle)}s ≥ {int(timeout_seconds)}s — "
                f"models unloaded (mlx={mlx_dropped}, parakeet={parakeet_dropped}, moonshine={moonshine_dropped})"
            )


def main() -> int:
    get_logger()

    if is_daemon_already_running():
        log_info("daemon already running, exiting")
        return 0

    write_daemon_pidfile()
    cleanup_socket()
    SOCK_PATH.parent.mkdir(parents=True, exist_ok=True)

    config = load_config()
    log_stage("daemon_start")

    try:
        preload_models(config)
    except Exception as e:
        log_error(f"preload failed: {e}")

    idle_minutes = float(config.get("daemon_mlx_idle_minutes", 30))
    if idle_minutes > 0:
        threading.Thread(
            target=idle_reaper, args=(idle_minutes * 60.0,), daemon=True,
        ).start()
        log_info(f"idle reaper enabled: unload MLX after {idle_minutes}min idle")

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(str(SOCK_PATH))
    server.listen(8)
    server.settimeout(1.0)  # so we can check _shutdown_event periodically
    os.chmod(SOCK_PATH, 0o600)

    log_info(f"daemon listening on {SOCK_PATH}")

    def _handle_sig(signum, frame):
        log_info(f"daemon got signal {signum}, shutting down")
        _shutdown_event.set()

    signal.signal(signal.SIGTERM, _handle_sig)
    signal.signal(signal.SIGINT, _handle_sig)

    try:
        while not _shutdown_event.is_set():
            try:
                conn, _ = server.accept()
            except socket.timeout:
                continue
            threading.Thread(
                target=handle_command, args=(conn,), daemon=True,
            ).start()
    finally:
        server.close()
        cleanup_socket()
        remove_daemon_pidfile()
        log_info("daemon stopped")

    return 0


if __name__ == "__main__":
    sys.exit(main())
