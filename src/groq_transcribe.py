"""
Fast cloud transcription using Groq API.
299x real-time speed - 10 min audio in 3.7 seconds.
"""

import os
from typing import Optional


def transcribe_with_groq(
    audio_path: str,
    api_key: Optional[str] = None,
    model: str = "whisper-large-v3-turbo",
) -> str:
    """
    Transcribe audio using Groq's Whisper API.

    Args:
        audio_path: Path to the audio file
        api_key: Groq API key (or set GROQ_API_KEY env var)
        model: Groq model to use:
            - whisper-large-v3-turbo: Fast, good accuracy (default)
            - whisper-large-v3: Most accurate
            - distil-whisper-large-v3-en: English-only, fastest

    Returns:
        Transcribed text as a string

    Raises:
        FileNotFoundError: If audio file doesn't exist
        ValueError: If no API key provided
    """
    if not os.path.exists(audio_path):
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    # Get API key from argument or environment
    key = api_key or os.environ.get("GROQ_API_KEY")
    if not key:
        raise ValueError(
            "Groq API key required. Set GROQ_API_KEY env var or pass api_key argument."
        )

    from groq import Groq

    client = Groq(api_key=key)

    with open(audio_path, "rb") as audio_file:
        transcription = client.audio.transcriptions.create(
            file=audio_file,
            model=model,
            response_format="text",
            language="en",
        )

    # Groq returns the text directly when response_format="text"
    return transcription.strip() if isinstance(transcription, str) else transcription.text.strip()
