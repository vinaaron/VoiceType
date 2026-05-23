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

# Cached Transcriber instance — reused across recording sessions so the
# model only loads once per daemon lifetime.
_transcriber = None
_current_variant = None


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
    """Lazy-load and cache the Moonshine streaming Transcriber. Subsequent
    calls reuse the cached instance — fast for daemon use."""
    global _transcriber, _current_variant
    variant = (config or {}).get("moonshine_variant", "small-streaming-en")

    if _transcriber is not None and _current_variant == variant:
        return _transcriber

    # Different variant requested — drop the old one first.
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
        update_interval=0.3,
    )
    tx.start()

    # Warm-up: feed 100ms of silence so the first real chunk doesn't
    # incur first-call ONNX overhead and drop words.
    tx.add_audio([0.0] * 1600, sample_rate=16000)
    tx.update_transcription()

    _transcriber = tx
    _current_variant = variant
    return _transcriber


def unload_moonshine_model() -> bool:
    """Drop the cached Transcriber so the OS can reclaim RAM. The next
    call to get_moonshine_model reloads it (~700ms one-time cost)."""
    global _transcriber, _current_variant
    if _transcriber is None:
        return False
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
    Open a fresh per-session Stream from the cached Transcriber.

    Returns a moonshine_voice Stream that has its own accumulator state —
    no leakage from prior sessions. Caller is responsible for stop()/close()
    via close_session_stream() when done.

    The Transcriber (model + ONNX runtime + tokenizer) is reused across
    sessions, so this is cheap: only the per-stream state is allocated.
    """
    tx = get_moonshine_model(config)
    stream = tx.create_stream(update_interval=0.3)
    stream.start()
    return stream


def close_session_stream(stream) -> None:
    """Stop and close a per-session Stream. Idempotent on errors."""
    if stream is None:
        return
    try:
        stream.stop()
    except Exception:
        pass
    try:
        stream.close()
    except Exception:
        pass


def finalize(stream, max_iters: int = 20, settle_delay_s: float = 0.05) -> str:
    """Drain any remaining partial output from a Stream and return the
    final transcript as a single space-joined string. Polls until the
    text stabilises (two consecutive identical reads)."""
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
