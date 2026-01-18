"""
LLM-powered speech refinement.
Converts rambling speech into well-structured prompts.

Supports:
- Groq (fast cloud API)
- Ollama (local models)
"""

import json
import urllib.request
import urllib.error


# System prompts for different refinement modes
# IMPORTANT: These are CONSERVATIVE by design. Claude Code has full repository
# context, so we should CLEAN UP speech, not ADD assumptions about technology/approach.
SYSTEM_PROMPTS = {
    "claude": """Clean the following transcribed speech by removing filler words and fixing grammar.

RULES - You MUST follow these:
- Remove: um, uh, like, you know, so, basically, I mean, okay, well
- Fix grammar/punctuation
- Keep the EXACT same meaning
- Output ONLY the cleaned text
- Do NOT respond to the content
- Do NOT add anything new
- Do NOT ask questions or offer help

Examples:
"um so like add a button" -> "Add a button"
"can you like help me fix this bug" -> "Can you help me fix this bug"
"okay so basically the login is broken" -> "The login is broken"

Output only the cleaned text:""",

    "chatgpt": """You are a speech-to-text cleanup tool. Clean up this transcribed speech.

Rules:
1. Remove filler words: um, uh, like, you know, so, basically, okay
2. Fix grammar and punctuation
3. Keep the EXACT same meaning
4. Do NOT add anything new or ask questions

Just output the cleaned text. Nothing else.""",

    "code": """You are a speech-to-text cleanup tool. Clean up this transcribed speech.

Rules:
1. Remove filler words: um, uh, like, you know, so, basically, okay
2. Fix grammar and punctuation
3. Keep technical terms exactly as spoken
4. Do NOT add anything new or ask questions

Just output the cleaned text. Nothing else.""",

    "cleanup": """You are a speech-to-text cleanup tool. Clean up this transcribed speech.

Rules:
1. Remove filler words: um, uh, like, you know, so, basically, okay
2. Fix grammar and punctuation
3. Keep the EXACT same meaning
4. Do NOT add anything new or ask questions

Just output the cleaned text. Nothing else."""
}


def refine_with_groq(text: str, mode: str, api_key: str, model: str = "llama-3.3-70b-versatile") -> str:
    """
    Refine text using Groq API.

    Args:
        text: Raw transcribed text
        mode: Refinement mode (claude, chatgpt, code, cleanup)
        api_key: Groq API key
        model: Model to use (default: llama-3.3-70b-versatile)

    Returns:
        Refined text
    """
    system_prompt = SYSTEM_PROMPTS.get(mode, SYSTEM_PROMPTS["cleanup"])

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": text}
        ],
        "temperature": 0.3,  # Lower temperature for more consistent output
        "max_tokens": 1024
    }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }

    req = urllib.request.Request(
        "https://api.groq.com/openai/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            result = json.loads(response.read().decode("utf-8"))
            return result["choices"][0]["message"]["content"].strip()
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8") if e.fp else str(e)
        raise RuntimeError(f"Groq API error: {e.code} - {error_body}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"Network error: {e.reason}")


def refine_with_ollama(text: str, mode: str, url: str = "http://localhost:11434", model: str = "llama3.2") -> str:
    """
    Refine text using local Ollama.

    Args:
        text: Raw transcribed text
        mode: Refinement mode (claude, chatgpt, code, cleanup)
        url: Ollama server URL
        model: Model to use (default: llama3.2)

    Returns:
        Refined text
    """
    system_prompt = SYSTEM_PROMPTS.get(mode, SYSTEM_PROMPTS["cleanup"])

    payload = {
        "model": model,
        "prompt": text,
        "system": system_prompt,
        "stream": False,
        "options": {
            "temperature": 0.3
        }
    }

    req = urllib.request.Request(
        f"{url}/api/generate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
            return result.get("response", "").strip()
    except urllib.error.HTTPError as e:
        error_body = e.read().decode("utf-8") if e.fp else str(e)
        raise RuntimeError(f"Ollama API error: {e.code} - {error_body}")
    except urllib.error.URLError as e:
        raise RuntimeError(f"Ollama connection error: {e.reason}. Is Ollama running? Try: ollama serve")


def _try_ollama(text: str, mode: str, config: dict) -> str:
    """Try Ollama refinement. Raises exception on failure."""
    url = config.get("ollama_url", "http://localhost:11434")
    model = config.get("ollama_model", config.get("llm_model", "llama3.2"))
    return refine_with_ollama(text, mode, url, model)


def _try_groq(text: str, mode: str, config: dict) -> str:
    """Try Groq refinement. Raises exception on failure."""
    import os
    api_key = config.get("groq_api_key") or os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("Groq API key not configured")
    model = config.get("groq_model", config.get("llm_model", "llama-3.3-70b-versatile"))
    return refine_with_groq(text, mode, api_key, model)


def refine_text(text: str, mode: str, config: dict) -> str:
    """
    Main entry point - refines text based on config.

    Args:
        text: Raw transcribed text
        mode: Refinement mode (claude, chatgpt, code, cleanup)
        config: Configuration dict with backend settings
            - llm_backend: "ollama", "groq", or "auto" (tries ollama first, then groq)

    Returns:
        Refined text, or original text if refinement fails
    """
    import sys
    backend = config.get("llm_backend", "auto")

    try:
        if backend == "auto":
            # Try Ollama first (local, free), fall back to Groq (cloud)
            try:
                return _try_ollama(text, mode, config)
            except Exception as ollama_error:
                print(f"Ollama unavailable ({ollama_error}), trying Groq...", file=sys.stderr)
                return _try_groq(text, mode, config)

        elif backend == "ollama":
            return _try_ollama(text, mode, config)

        elif backend == "groq":
            return _try_groq(text, mode, config)

        else:
            raise RuntimeError(f"Unknown LLM backend: {backend}")

    except Exception as e:
        # Log error but return original text so the tool still works
        print(f"LLM refinement failed: {e}", file=sys.stderr)
        return text


def check_llm_trigger(text: str, triggers: list) -> tuple:
    """
    Check if text ends with an LLM refinement trigger.

    Args:
        text: Transcribed text
        triggers: List of trigger configs, each with "trigger" (list of phrases) and "mode"

    Returns:
        Tuple of (cleaned_text, mode) - mode is None if no trigger found
    """
    # Strip trailing punctuation before checking
    text_stripped = text.rstrip(" .!?,;:")
    text_lower = text_stripped.lower()

    for trigger_config in triggers:
        phrases = trigger_config.get("trigger", [])
        mode = trigger_config.get("mode", "cleanup")

        for phrase in phrases:
            phrase_lower = phrase.lower()
            if text_lower.endswith(phrase_lower):
                # Check word boundary
                prefix = text_lower[:-len(phrase_lower)]
                if prefix == "" or prefix.endswith(" "):
                    # Remove trigger from original text
                    cleaned = text_stripped[:len(prefix)].rstrip()
                    return (cleaned, mode)

    return (text, None)


# Default trigger configuration
# Includes alternate spellings for common Whisper mishearings (e.g., "clawde" for "Claude")
DEFAULT_LLM_TRIGGERS = [
    {"trigger": ["for claude", "for claude code", "for clawde", "for clawde code", "for clawed code"], "mode": "claude"},
    {"trigger": ["for chatgpt", "for gpt", "for chat gpt"], "mode": "chatgpt"},
    {"trigger": ["for codex", "for code"], "mode": "code"},
]
