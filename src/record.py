"""
Fixed-duration audio recorder using sox.

Used only as a fallback when VAD recording fails or is explicitly disabled
via --no-vad. The primary recorder is src/vad_record.py.
"""

import subprocess
import os
from pathlib import Path


def get_recording_path():
    """Get the path for temporary recording storage."""
    config_dir = Path.home() / ".voice-cli"
    config_dir.mkdir(exist_ok=True)
    return str(config_dir / "recording.wav")


def record_fixed_duration(output_path=None, duration=5.0, sample_rate=16000):
    """
    Record audio for a fixed duration.

    Args:
        output_path: Where to save the audio
        duration: Recording duration in seconds
        sample_rate: Audio sample rate in Hz

    Returns:
        Path to the recorded audio file
    """
    if output_path is None:
        output_path = get_recording_path()

    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    if os.path.exists(output_path):
        os.remove(output_path)

    cmd = [
        "sox",
        "-d",
        "-c", "1",
        "-r", str(sample_rate),
        output_path,
        "trim", "0", str(duration),
    ]

    subprocess.run(cmd, check=True, capture_output=True)
    return output_path
