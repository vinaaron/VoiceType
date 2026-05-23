"""
Streaming transcription via Moonshine v2 (UsefulSensors).

Moonshine v2 processes audio incrementally — partial text is emitted while
the user is still speaking. End-of-speech-to-final-text latency drops from
~20% of audio length (MLX Whisper batch) to a flat ~150ms regardless of
utterance length.

This module exposes:

- `open_stream(config)` — context manager that yields an active streaming
  Transcriber. The caller pushes audio chunks via `tx.add_audio(...)`
  and reads the final transcript via `tx.update_transcription()` at end.
- `get_moonshine_model(config)` — lazy-load + cache the underlying model
  weights (idempotent; reused across sessions).
- `unload_moonshine_model()` — drop the cache (used by the daemon's idle
  reaper to free RAM).

The model files (~235MB for small-streaming-en) are downloaded on first
use to ~/Library/Caches/moonshine_voice/.

Install: ~/.voice-cli-venv/bin/pip install moonshine-voice
"""

import os
from pathlib import Path

# Cached Transcriber + Stream — reused across recording sessions so the
# model only loads once per daemon lifetime AND each new session doesn't
# pay first-call ONNX cold-start latency.
_transcriber = None
_current_variant = None
_stream = None  # one warm Stream, reset (not recreated) per session


# Where moonshine-voice stashes downloaded models on macOS.
_CACHE_ROOT = Path.home() / "Library" / "Caches" / "moonshine_voice" / "download.moonshine.ai" / "model"


def _model_cache_path(variant: str) -> Path:
    """Maps a variant name like 'small-streaming-en' to its cached files."""
    return _CACHE_ROOT / variant / "quantized"


def _arch_for_variant(variant: str):
    """Map variant string to the matching ModelArch enum value."""
    from moonshine_voice import ModelArch
    return {
        "tiny-streaming-en": ModelArch.TINY_STREAMING,
        "base-streaming-en": ModelArch.BASE_STREAMING,
        "small-streaming-en": ModelArch.SMALL_STREAMING,
        "medium-streaming-en": ModelArch.MEDIUM_STREAMING,
    }.get(variant, ModelArch.SMALL_STREAMING)


def _ensure_downloaded(variant: str) -> Path:
    """Trigger moonshine-voice's lazy downloader to fetch model assets if
    they aren't already cached. Returns the local quantized-model dir."""
    cache_path = _model_cache_path(variant)
    if cache_path.exists() and any(cache_path.iterdir()):
        return cache_path

    # log_model_info is the side-effect-free way to trigger the downloader
    # without instantiating the Transcriber.
    import moonshine_voice as mv
    mv.log_model_info(wanted_language="en", wanted_model_arch=_arch_for_variant(variant))
    return cache_path


def get_moonshine_model(config: dict | None = None):
    """Lazy-load and cache the Moonshine streaming Transcriber AND one
    warm Stream. Subsequent calls reuse the cached pair — fast for
    daemon use."""
    global _transcriber, _current_variant, _stream
    variant = (config or {}).get("moonshine_variant", "small-streaming-en")

    if _transcriber is not None and _current_variant == variant:
        return _transcriber

    # Different variant requested — drop the old one first.
    if _stream is not None:
        try:
            _stream.stop()
            _stream.close()
        except Exception:
            pass
        _stream = None
    if _transcriber is not None:
        try:
            _transcriber.stop()
            _transcriber.close()
        except Exception:
            pass
        _transcriber = None

    try:
        import moonshine_voice as mv
    except ImportError as e:
        raise ImportError(
            "moonshine-voice not installed. Run: "
            "~/.voice-cli-venv/bin/pip install moonshine-voice"
        ) from e

    cache_path = _ensure_downloaded(variant)
    arch = _arch_for_variant(variant)

    tx = mv.Transcriber(
        model_path=str(cache_path),
        model_arch=arch,
        update_interval=0.1,
    )
    tx.start()

    # Warm up the Transcriber itself.
    tx.add_audio([0.0] * 1600, sample_rate=16000)
    tx.update_transcription()

    # Pre-create the long-lived per-daemon Stream and warm it up too.
    stream = tx.create_stream(update_interval=0.1)
    stream.start()
    stream.add_audio([0.0] * 1600, sample_rate=16000)
    stream.update_transcription()

    _transcriber = tx
    _current_variant = variant
    _stream = stream
    return _transcriber


def unload_moonshine_model() -> bool:
    """Drop the cached Transcriber AND Stream so the OS can reclaim RAM.
    The next call to get_moonshine_model reloads them (~700ms one-time)."""
    global _transcriber, _current_variant, _stream
    if _transcriber is None and _stream is None:
        return False
    if _stream is not None:
        try:
            _stream.stop()
            _stream.close()
        except Exception:
            pass
        _stream = None
    if _transcriber is not None:
        try:
            _transcriber.stop()
            _transcriber.close()
        except Exception:
            pass
        _transcriber = None
    _current_variant = None
    return True


def open_session_stream(config: dict | None = None):
    """
    Return the daemon's one warm Stream, reset for a fresh session.

    Architecture: we keep a single long-lived Stream alive in module
    state (created and warmed up in get_moonshine_model). Each session
    calls stop()/start() on it to clear the encoder accumulator state,
    then re-warms with 100ms of silence. Round-trip cost: ~6ms — vs
    creating a fresh Stream per session which was paying ~3-4 seconds
    of cold-start ONNX allocation overhead.

    No state leaks across sessions (verified): stop+start fully clears
    the encoder's internal cache; the warmup primes the next inference.
    """
    # Make sure the model + warm stream exist.
    get_moonshine_model(config)
    global _stream
    if _stream is None:
        raise RuntimeError("moonshine stream not initialised")

    # Reset for a fresh session.
    try:
        _stream.stop()
    except Exception:
        pass
    _stream.start()
    # Re-warm so the first real-audio chunk doesn't pay any cold-start.
    _stream.add_audio([0.0] * 1600, sample_rate=16000)
    _stream.update_transcription()
    return _stream


def close_session_stream(stream) -> None:
    """No-op — the Stream is long-lived and shared across sessions.
    State is cleared on the next open_session_stream() via stop+start.
    Kept as a hook for any future per-session cleanup."""
    return


def finalize(stream, max_iters: int = 40, settle_delay_s: float = 0.05) -> str:
    """Drain any remaining partial output from a Stream and return the
    final transcript as a single space-joined string. Polls until the
    text stabilises (two consecutive identical reads).

    max_iters * settle_delay_s caps total wait at 2s — enough headroom
    for long utterances where the model is still catching up with
    queued audio chunks at end-of-recording."""
    import time
    prev = None
    final_lines = []
    for _ in range(max_iters):
        t = stream.update_transcription()
        cur = " ".join(line.text.strip() for line in t.lines if line.text.strip())
        if cur == prev:
            final_lines = [line.text.strip() for line in t.lines if line.text.strip()]
            break
        prev = cur
        time.sleep(settle_delay_s)
    # Join lines with a single space — Moonshine may split a single
    # utterance across multiple TranscriptLines on internal pauses.
    return " ".join(final_lines).strip()
