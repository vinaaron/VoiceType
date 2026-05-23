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

    # Pad with 1s of silence at the end. Whisper hallucinates phrases like
    # "Thanks for watching!" when audio ends abruptly; trailing silence
    # gives the decoder a clean stop and dramatically reduces ghost text.
    silence_padding = b"\x00\x00" * SAMPLE_RATE  # 1s of int16 zeros

    with wave.open(output_path, 'wb') as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(audio.get_sample_size(FORMAT))
        wf.setframerate(SAMPLE_RATE)
        wf.writeframes(b''.join(frames) + silence_padding)

    return output_path


def record_with_vad_streaming(
    stream,
    silence_duration=2.0,
    max_duration=30,
    speech_threshold=0.5,
    on_audio_level=None,
    stop_event=None,
    chunks_per_feed=10,
):
    """
    Streaming counterpart to record_with_vad().

    Records via PyAudio + Silero VAD (same gate semantics as record_with_vad),
    but instead of accumulating frames and writing a WAV at the end, this
    function pushes audio chunks directly into a Moonshine `Stream` as
    they arrive — so the model processes audio while the user is still
    speaking and the final transcript is ready ~150ms after end-of-speech
    regardless of utterance length.

    Args:
        stream: A live moonshine_voice Stream (per-session, from
                Transcriber.create_stream(), already started). The caller
                owns its lifecycle and reads the final transcript via
                moonshine_transcribe.finalize(stream) after this returns.
                Each session MUST use a fresh Stream — sharing one across
                sessions leaks prior transcripts into new ones.
        silence_duration: Seconds of post-speech silence before stopping.
        max_duration: Safety cap in seconds.
        speech_threshold: VAD confidence threshold (0-1).
        on_audio_level: Optional callback(level∈[0,1]) for VU meter.
        stop_event: threading.Event — when set, recording ends early
                    (used by the SIGUSR1 / socket toggle).
        chunks_per_feed: How many 32ms Silero chunks to buffer before
                         each transcriber.add_audio call. Amortizes the
                         per-call ONNX overhead. Default 10 ≈ 320ms.

    Returns:
        None — the transcript lives in the Transcriber. Call
        moonshine_transcribe.finalize(transcriber) to extract it.
    """
    import queue
    import threading

    model = get_vad_model()

    audio_handle = pyaudio.PyAudio()
    pa_stream = None

    # Producer-consumer queue: PyAudio loop pushes audio chunks here;
    # a separate worker thread pulls them and feeds Moonshine. This
    # decouples the (real-time) audio capture from the (60-140ms) ONNX
    # inference that happens inside stream.add_audio(). Without this
    # decoupling, PyAudio's small ring buffer overflows during each
    # add_audio call and drops audio — which both truncates the
    # transcript AND makes Silero see false silences.
    feed_queue: "queue.Queue[bytes | None]" = queue.Queue(maxsize=64)
    consumer_error = []

    def consumer():
        """Pull audio from the queue and feed Moonshine. Runs in its
        own thread so the PyAudio loop never blocks on model inference."""
        try:
            while True:
                item = feed_queue.get()
                if item is None:
                    return  # sentinel — drain complete
                combined_float = (
                    np.frombuffer(item, np.int16).astype(np.float32) / 32768.0
                ).tolist()
                stream.add_audio(combined_float, sample_rate=SAMPLE_RATE)
        except Exception as e:
            consumer_error.append(e)

    consumer_thread = threading.Thread(target=consumer, daemon=True)
    consumer_thread.start()

    try:
        pa_stream = audio_handle.open(
            format=FORMAT,
            channels=CHANNELS,
            rate=SAMPLE_RATE,
            input=True,
            frames_per_buffer=CHUNK_SAMPLES,
        )

        # Warm-up: discard initial buffer garbage.
        for _ in range(3):
            pa_stream.read(CHUNK_SAMPLES, exception_on_overflow=False)

        silence_chunks = 0
        chunks_for_silence = int(silence_duration * 1000 / CHUNK_MS)
        max_chunks = int(max_duration * 1000 / CHUNK_MS)
        speech_detected = False

        # Local buffer that batches CHUNK_SAMPLES-size PyAudio reads
        # into ~320ms feeds. Stays small (≤chunks_per_feed entries).
        feed_buffer = []

        def enqueue_feed():
            if not feed_buffer:
                return
            combined_bytes = b"".join(f.tobytes() for f in feed_buffer)
            try:
                feed_queue.put(combined_bytes, timeout=1.0)
            except queue.Full:
                pass  # drop rather than block — better to lose audio than wedge
            feed_buffer.clear()

        for _ in range(max_chunks):
            if stop_event is not None and stop_event.is_set():
                break

            data = pa_stream.read(CHUNK_SAMPLES, exception_on_overflow=False)
            audio_int16 = np.frombuffer(data, np.int16)
            feed_buffer.append(audio_int16)

            if on_audio_level:
                rms = np.sqrt(np.mean(audio_int16.astype(np.float32) ** 2))
                if rms > 1:
                    normalized = min(1.0, (np.log10(rms) + 1) / 3)
                else:
                    normalized = 0.0
                on_audio_level(normalized)

            # VAD decision (same Silero pipeline as the batch path).
            audio_float32 = int2float(audio_int16)
            tensor = torch.from_numpy(audio_float32)
            speech_prob = model(tensor, SAMPLE_RATE).item()

            if speech_prob >= speech_threshold:
                speech_detected = True
                silence_chunks = 0
            else:
                if speech_detected:
                    silence_chunks += 1
                    if silence_chunks >= chunks_for_silence:
                        break

            # Hand off the batch to the consumer thread — non-blocking.
            if len(feed_buffer) >= chunks_per_feed:
                enqueue_feed()

        # Send any remaining buffered audio.
        enqueue_feed()

    finally:
        if pa_stream is not None:
            pa_stream.stop_stream()
            pa_stream.close()
        audio_handle.terminate()
        # Signal consumer to drain and exit, then wait for it.
        feed_queue.put(None)
        consumer_thread.join(timeout=3.0)
        if consumer_error:
            raise consumer_error[0]

    return None
