"""
Fast transcription using Lightning Whisper MLX.
Optimized for Apple Silicon (M1/M2/M3/M4) - 10x faster than Whisper CPP.
"""

import os

# Lazy loading to avoid import overhead
_whisper_model = None
_current_model_name = None


def unload_mlx_model() -> bool:
    """Drop the cached model so the OS can reclaim its RAM. The next
    transcribe call will reload it (~3-4s one-time cost). Returns True
    if there was a model loaded to unload."""
    global _whisper_model, _current_model_name
    if _whisper_model is None:
        return False
    _whisper_model = None
    _current_model_name = None
    return True


def get_mlx_model(model_name: str = "distil-medium.en"):
    """
    Get or create the Lightning Whisper MLX model.
    Uses lazy loading - model is cached after first load.

    Args:
        model_name: Model to use. Options:
            - tiny, tiny.en: Fastest, least accurate
            - base, base.en: Fast, good accuracy
            - small, small.en: Balanced
            - medium, medium.en: More accurate
            - large, large-v2, large-v3: Most accurate
            - distil-small.en: Fast English-only (recommended for speed)
            - distil-medium.en: Balanced English-only (default)
            - distil-large-v3: Accurate English-only

    Returns:
        LightningWhisperMLX model instance
    """
    global _whisper_model, _current_model_name

    if _whisper_model is None or _current_model_name != model_name:
        from lightning_whisper_mlx import LightningWhisperMLX
        _whisper_model = LightningWhisperMLX(model=model_name, batch_size=12, quant=None)
        _current_model_name = model_name

    return _whisper_model


def transcribe_with_mlx(
    audio_path: str,
    model_name: str = "distil-medium.en",
) -> str:
    """
    Transcribe audio using Lightning Whisper MLX.

    Args:
        audio_path: Path to the audio file (WAV recommended)
        model_name: Model to use (see get_mlx_model for options)

    Returns:
        Transcribed text as a string

    Raises:
        FileNotFoundError: If audio file doesn't exist
    """
    if not os.path.exists(audio_path):
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    whisper = get_mlx_model(model_name)
    result = whisper.transcribe(audio_path)

    return result.get('text', '').strip()
