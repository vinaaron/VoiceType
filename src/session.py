"""
Voice recording session pipeline.

A single recording → transcribe → refine → paste run. Used both by
bin/voice-cli (one-shot mode) and src/daemon.py (long-lived background
process). The caller owns the stop_event and the SIGUSR1 / socket plumbing
that flips it; this module just runs the pipeline.
"""

import os
import threading
import time

from output import (
    type_text_via_clipboard, play_sound, notify,
    get_frontmost_app, press_enter,
)
from recording_indicator import show_recording_indicator, hide_recording_indicator
from logger import log_stage, log_info, log_error


_DICTIONARY_PATH = os.path.expanduser("~/.voice-cli/dictionary.txt")


def load_personal_dictionary() -> str | None:
    """Read ~/.voice-cli/dictionary.txt and turn it into a single
    Whisper initial_prompt string. Lines starting with # are skipped.
    Returns None if no dictionary or empty."""
    if not os.path.exists(_DICTIONARY_PATH):
        return None
    try:
        with open(_DICTIONARY_PATH) as f:
            terms = [
                line.strip() for line in f
                if line.strip() and not line.lstrip().startswith("#")
            ]
    except OSError:
        return None
    if not terms:
        return None
    # Whisper prompts work best as natural-sounding context, not bare lists.
    return "Terms that may appear: " + ", ".join(terms) + "."


def check_enter_trigger(text: str, triggers: list) -> tuple:
    text_stripped = text.rstrip(" .!?,;:")
    text_lower = text_stripped.lower()
    for trigger in triggers:
        if text_lower.endswith(trigger):
            prefix = text_lower[:-len(trigger)]
            if prefix == "" or prefix.endswith(" "):
                cleaned = text_stripped[:len(prefix)].rstrip()
                return (cleaned, True)
    return (text, False)


def run_voice_session(
    config: dict,
    stop_event: threading.Event,
    debug: bool = False,
    models_preloaded: bool = False,
) -> dict:
    """
    Run a single recording session end-to-end.

    Args:
        config: Loaded config dict (see bin/voice-cli load_config).
        stop_event: threading.Event. The VAD loop checks this each chunk
                    and breaks early when set — the partial audio still
                    gets transcribed and pasted.
        debug: When True, prints to stdout instead of typing.
        models_preloaded: When True, the caller (daemon) has already
                          loaded VAD/MLX and we can skip the pre-load step.

    Returns:
        {"ok": True, "text": "..."} on success
        {"ok": False, "reason": "..."} on early exit (no speech, etc.)
    """
    model = config["model"]
    transcription_mode = config.get("transcription_mode", "mlx")
    groq_api_key = config.get("groq_api_key") or os.environ.get("GROQ_API_KEY")
    duration = config.get("duration", 5.0)
    silence_duration = config["silence_duration"]
    use_sound = config["sound_feedback"]
    convert_nums = config["convert_numbers"]
    show_notify = config.get("show_notifications", True)
    show_indicator = config.get("show_recording_indicator", True)
    use_vad = config.get("vad_mode", True)
    vad_threshold = config.get("vad_threshold", 0.5)
    max_duration = config.get("max_duration", 30)
    auto_enter = config.get("auto_enter", True)
    enter_triggers = config.get("enter_triggers", ["enter", "send", "submit", "return"])
    use_llm = config.get("llm_refinement", True)

    # Save frontmost app BEFORE anything else — Raycast may become
    # frontmost when triggered.
    original_app = get_frontmost_app()
    log_info(f"frontmost_app={original_app}")

    if use_vad and not models_preloaded:
        from vad_record import get_vad_model
        get_vad_model()
    log_stage("vad_ready")

    if show_notify:
        if use_vad:
            notify("Voice CLI", "Recording... (auto-stops when you pause)")
        else:
            notify("Voice CLI", f"Recording for {duration}s... Speak now!")

    if use_sound:
        play_sound("Ping")

    indicator = None
    if show_indicator:
        indicator = show_recording_indicator()

    def on_audio_level(level):
        if indicator:
            indicator.update_level(level)

    try:
        if use_vad:
            from vad_record import record_with_vad
            try:
                audio_path = record_with_vad(
                    silence_duration=silence_duration,
                    max_duration=max_duration,
                    speech_threshold=vad_threshold,
                    on_audio_level=on_audio_level if show_indicator else None,
                    stop_event=stop_event,
                )
            except Exception as e:
                log_error(f"VAD failed, using fixed duration: {e}")
                from record import record_fixed_duration
                audio_path = record_fixed_duration(duration=duration)
        else:
            from record import record_fixed_duration
            audio_path = record_fixed_duration(duration=duration)
    finally:
        if indicator:
            hide_recording_indicator(indicator)

    log_stage("record_end")

    if use_sound:
        play_sound("Pop")

    if not os.path.exists(audio_path):
        if show_notify:
            notify("Voice CLI", "No audio file created")
        log_error("no audio file created")
        return {"ok": False, "reason": "no_audio_file"}

    file_size = os.path.getsize(audio_path)
    if file_size < 1000:
        if show_notify:
            notify("Voice CLI", f"No speech detected ({file_size} bytes)")
        log_info(f"no speech detected file_size={file_size}")
        os.remove(audio_path)
        return {"ok": False, "reason": "no_speech"}

    if show_notify:
        mode_name = {"mlx": "MLX", "groq": "Groq", "local": "Local"}
        notify("Voice CLI", f"Transcribing ({mode_name.get(transcription_mode, transcription_mode)})...")

    log_info(f"transcribing mode={transcription_mode}")

    initial_prompt = load_personal_dictionary()
    if initial_prompt:
        log_info(f"using personal dictionary ({initial_prompt.count(',') + 1} terms)")

    if transcription_mode == "parakeet":
        parakeet_model = config.get("parakeet_model", "mlx-community/parakeet-tdt-0.6b-v3")
        try:
            from parakeet_transcribe import transcribe_with_parakeet
            text = transcribe_with_parakeet(audio_path, model_name=parakeet_model)
        except ImportError as e:
            log_error(f"parakeet-mlx not installed ({e}), falling back to MLX Whisper")
            from mlx_transcribe import transcribe_with_mlx
            text = transcribe_with_mlx(audio_path, model_name=model, initial_prompt=initial_prompt)
        except Exception as e:
            log_error(f"Parakeet failed: {e}, falling back to MLX Whisper")
            from mlx_transcribe import transcribe_with_mlx
            text = transcribe_with_mlx(audio_path, model_name=model, initial_prompt=initial_prompt)

    elif transcription_mode == "mlx":
        try:
            from mlx_transcribe import transcribe_with_mlx
            text = transcribe_with_mlx(audio_path, model_name=model, initial_prompt=initial_prompt)
        except ImportError:
            log_info("MLX not available, falling back to local")
            from transcribe import Transcriber
            text = Transcriber.transcribe(audio_path, model_name=model)
        except Exception as e:
            log_error(f"MLX failed: {e}, falling back to local")
            from transcribe import Transcriber
            text = Transcriber.transcribe(audio_path, model_name=model)

    elif transcription_mode == "groq":
        if not groq_api_key:
            if show_notify:
                notify("Voice CLI Error", "Groq API key required. Set GROQ_API_KEY or use --mode mlx")
            log_error("Groq API key not set")
            os.remove(audio_path)
            return {"ok": False, "reason": "no_groq_key"}
        try:
            from groq_transcribe import transcribe_with_groq
            text = transcribe_with_groq(audio_path, api_key=groq_api_key)
        except Exception as e:
            log_error(f"Groq failed: {e}, falling back to local")
            from transcribe import Transcriber
            text = Transcriber.transcribe(audio_path, model_name=model)

    else:
        from transcribe import Transcriber
        text = Transcriber.transcribe(audio_path, model_name=model)

    log_stage("transcribe_end")

    if not text:
        if show_notify:
            notify("Voice CLI", "No text transcribed")
        log_info("no text transcribed")
        os.remove(audio_path)
        return {"ok": False, "reason": "empty_transcript"}

    if convert_nums:
        from number_words import convert_number_words
        text = convert_number_words(text)

    llm_mode = None
    if use_llm:
        from llm_refine import refine_text, check_llm_trigger, DEFAULT_LLM_TRIGGERS
        llm_triggers = config.get("llm_triggers") or DEFAULT_LLM_TRIGGERS
        text, llm_mode = check_llm_trigger(text, llm_triggers)
        # Snapshot the pre-LLM-refine transcript (trigger phrase already
        # stripped). This is what "Voice Revert" restores if the LLM
        # over-edited.
        raw_text = text
        if llm_mode:
            log_info(f"llm trigger detected mode={llm_mode}")
            if show_notify:
                notify("Voice CLI", f"Refining for {llm_mode}...")
            text = refine_text(text, llm_mode, config)
    else:
        raw_text = text

    log_stage("llm_end")

    should_enter = False
    if auto_enter:
        text, should_enter = check_enter_trigger(text, enter_triggers)

    log_info(f"transcript={text!r} should_enter={should_enter} target_app={original_app}")

    if debug:
        print(f"Transcribed: {text}")
        print(f"Mode: {transcription_mode}")
        print(f"Model: {model}")
        print(f"Audio size: {file_size} bytes")
        print(f"Target app: {original_app}")
        print(f"Should enter: {should_enter}")
        if show_notify:
            notify("Voice CLI", f"Done: {text[:50]}...")
    else:
        if text:
            type_text_via_clipboard(text, target_app=original_app)
        if should_enter:
            time.sleep(0.05)
            press_enter()
        if show_notify:
            action = "Sent" if should_enter else "Typed"
            notify("Voice CLI", f"{action}: {text[:50]}...")

    log_stage("paste_done")

    try:
        os.remove(audio_path)
    except OSError:
        pass

    return {
        "ok": True,
        "text": text,        # the version that was actually pasted
        "raw": raw_text,     # pre-LLM-cleanup, for "Voice Revert"
        "llm_mode": llm_mode,
        "target_app": original_app,
    }
