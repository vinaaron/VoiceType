"""
Fast transcription using NVIDIA Parakeet V3 via parakeet-mlx (Apple Silicon).

Parakeet V3 ASR runs natively on the Apple Neural Engine through MLX and
benchmarks competitively with Whisper distil-medium — often faster, similar
accuracy, ~470MB. Switch to this backend by setting in ~/.voice-cli/config.yaml:

    transcription_mode: parakeet
    parakeet_model: mlx-community/parakeet-tdt-0.6b-v3

Install: ~/.voice-cli-venv/bin/pip install parakeet-mlx
"""

import os

_parakeet_model = None
_current_parakeet_name = None


def get_parakeet_model(model_name: str = "mlx-community/parakeet-tdt-0.6b-v3"):
    """Lazy-load and cache the Parakeet MLX model."""
    global _parakeet_model, _current_parakeet_name
    if _parakeet_model is None or _current_parakeet_name != model_name:
        try:
            from parakeet_mlx import from_pretrained
        except ImportError as e:
            raise ImportError(
                "parakeet-mlx is not installed. Run: "
                "~/.voice-cli-venv/bin/pip install parakeet-mlx"
            ) from e
        _parakeet_model = from_pretrained(model_name)
        _current_parakeet_name = model_name
    return _parakeet_model


def unload_parakeet_model() -> bool:
    """Drop the cached Parakeet model. Used by the daemon idle reaper."""
    global _parakeet_model, _current_parakeet_name
    if _parakeet_model is None:
        return False
    _parakeet_model = None
    _current_parakeet_name = None
    return True


def transcribe_with_parakeet(
    audio_path: str,
    model_name: str = "mlx-community/parakeet-tdt-0.6b-v3",
) -> str:
    """
    Transcribe audio using Parakeet MLX.

    Note: Parakeet writes numbers as words ("one", "two", "three"). The
    existing number_words.convert_number_words() call in session.py will
    convert these to digits same as it does for Whisper output.
    """
    if not os.path.exists(audio_path):
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    model = get_parakeet_model(model_name)
    result = model.transcribe(audio_path)
    # parakeet-mlx returns an object with a .text attribute (or a dict)
    if hasattr(result, "text"):
        return result.text.strip()
    if isinstance(result, dict):
        return result.get("text", "").strip()
    return str(result).strip()
