"""
Audio recording with Silero VAD for intelligent speech detection.
Stops recording automatically when user stops speaking.
"""

import pyaudio
import numpy as np
import torch
import wave
import os
from pathlib import Path
from silero_vad import load_silero_vad

# Audio settings (optimized for Whisper + Silero VAD)
SAMPLE_RATE = 16000
CHANNELS = 1
# Silero VAD requires exactly 512 samples at 16kHz (32ms chunks)
CHUNK_SAMPLES = 512
CHUNK_MS = CHUNK_SAMPLES * 1000 / SAMPLE_RATE  # ~32ms
FORMAT = pyaudio.paInt16

# Cache the VAD model
_vad_model = None


def get_vad_model():
    """Get cached VAD model (loads once, reuses)."""
    global _vad_model
    if _vad_model is None:
        _vad_model = load_silero_vad()
    return _vad_model


def int2float(sound):
    """Convert int16 audio to float32 for VAD model."""
    abs_max = np.abs(sound).max()
    sound = sound.astype('float32')
    if abs_max > 0:
        sound *= 1 / 32768
    return sound


def get_recording_path():
    """Get the path for temporary recording storage."""
    config_dir = Path.home() / ".voice-cli"
    config_dir.mkdir(exist_ok=True)
    return str(config_dir / "recording.wav")


def record_with_vad(
    output_path=None,
    silence_duration=2.0,
    max_duration=30,
    speech_threshold=0.5,
    on_audio_level=None,
    stop_event=None,
):
    """
    Record audio until user stops speaking.

    Uses Silero VAD (Voice Activity Detection) neural network to detect
    when the user starts and stops speaking. Much more accurate than
    simple threshold-based silence detection.

    Args:
        output_path: Where to save the WAV file. Defaults to ~/.voice-cli/recording.wav
        silence_duration: Seconds of silence before stopping (default: 2.0)
        max_duration: Maximum recording time in seconds (default: 30)
        speech_threshold: VAD confidence threshold 0-1 (default: 0.5)
        on_audio_level: Optional callback(level) for real-time audio visualization.
                        Level is normalized 0-1 based on RMS.
        stop_event: Optional threading.Event. When set, the recording loop
                    breaks early and the partial audio is saved. Used to
                    implement second-press toggle ("stop & transcribe now").

    Returns:
        Path to recorded audio file

    Raises:
        RuntimeError: If PyAudio fails to open audio stream
    """
    if output_path is None:
        output_path = get_recording_path()

    # Ensure parent directory exists
    os.makedirs(os.path.dirname(output_path), exist_ok=True)

    # Remove existing file if present
    if os.path.exists(output_path):
        os.remove(output_path)

    # Load VAD model (cached after first load)
    model = get_vad_model()

    # Initialize PyAudio
    audio = pyaudio.PyAudio()
    stream = None

    try:
        stream = audio.open(
            format=FORMAT,
            channels=CHANNELS,
            rate=SAMPLE_RATE,
            input=True,
            frames_per_buffer=CHUNK_SAMPLES
        )

        # Warm up the audio stream - discard first few chunks
        # This helps avoid initial buffer garbage and ensures clean capture
        for _ in range(3):  # ~96ms warmup
            stream.read(CHUNK_SAMPLES, exception_on_overflow=False)

        frames = []
        silence_chunks = 0
        chunks_for_silence = int(silence_duration * 1000 / CHUNK_MS)
        max_chunks = int(max_duration * 1000 / CHUNK_MS)
        speech_detected = False

        for _ in range(max_chunks):
            if stop_event is not None and stop_event.is_set():
                break

            # Read audio chunk
            data = stream.read(CHUNK_SAMPLES, exception_on_overflow=False)
            frames.append(data)

            # Convert to numpy array for processing
            audio_int16 = np.frombuffer(data, np.int16)

            # Calculate audio level for visualization
            if on_audio_level:
                # Calculate RMS using numpy (audioop removed in Python 3.13)
                rms = np.sqrt(np.mean(audio_int16.astype(np.float32) ** 2))
                # Normalize to 0-1 (background ~5, soft speech ~50, loud speech ~500)
                # Use log scale for better visual response
                if rms > 1:
                    normalized = min(1.0, (np.log10(rms) + 1) / 3)  # log10(1)=0, log10(1000)=3
                else:
                    normalized = 0.0
                on_audio_level(normalized)

            # Convert to tensor for VAD
            audio_float32 = int2float(audio_int16)
            tensor = torch.from_numpy(audio_float32)

            # Get speech probability from VAD model
            speech_prob = model(tensor, SAMPLE_RATE).item()

            if speech_prob >= speech_threshold:
                # Speech detected
                speech_detected = True
                silence_chunks = 0
            else:
                # Silence detected
                if speech_detected:
                    # Only count silence after speech has been detected
                    silence_chunks += 1
                    if silence_chunks >= chunks_for_silence:
                        # User stopped speaking
                        break

    finally:
        if stream is not None:
            stream.stop_stream()
            stream.close()
        audio.terminate()

    # Save to WAV file
    with wave.open(output_path, 'wb') as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(audio.get_sample_size(FORMAT))
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(b''.join(frames))

    return output_path
