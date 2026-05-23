# Roadmap — deferred wins from the 2026-05-23 research

These are concrete improvements found while studying Wispr Flow, SuperWhisper, MacWhisper, VoiceInk, Talon, Moonshine, Parakeet, and a handful of OSS dictation tools. Items here were intentionally **not** shipped in the daemon batch because they were too big, too niche, or pending real-world use to validate they're worth it.

Order is rough effort × value, top = highest ROI.

## Medium projects

### Streaming partial transcripts via Moonshine v2

**Why.** Currently we batch-transcribe after silence. With a streaming model you'd see partial text appear in the menubar pill *while* you talk, plus a much lower end-of-utterance latency (~50ms vs Whisper's silence-padded batch).

**How.** Swap MLX Whisper for [Moonshine v2 Tiny](https://github.com/usefulsensors/moonshine) (~100MB, optimized for streaming). Refactor `vad_record.py` to push audio frames into the model continuously rather than collecting them into a WAV. Update `menu_bar_indicator` to render incoming partial text. The transcription contract becomes "callback per partial" instead of "string per WAV."

**Cost.** ~6-8 hours. Two non-trivial pieces: (1) replacing the WAV-then-transcribe pipeline with a streaming one across `session.py` / `daemon.py`, (2) UI plumbing to show partial text in the menubar without flicker.

### Floating "Dynamic Island"-style recording pill near the cursor

**Why.** The menubar VU is fine but lives in the wrong place — your eyes are at the cursor. SuperWhisper and VoiceInk float a tiny pill near the active text field; once you have one, the menubar feels old.

**How.** Swift helper app (NSPanel, ignores mouse events, follows the AX-focused field). Spawned by the daemon at recording start. Same stdin protocol as the menubar indicator for live audio levels.

**Cost.** ~4-6 hours mostly because of Swift project setup. Once it exists, future features (partial-text rendering, mode badge) drop in cheaply.

## Small but contextual

### Per-app modes

Auto-pick the LLM cleanup mode (or skip it entirely) based on the frontmost app:
- Terminal / iTerm / WezTerm → no LLM cleanup, raw paste
- Claude Code (Electron) / claude.ai → apply "for claude" cleanup automatically
- Slack → casual cleanup, preserve emoji shortcuts
- VS Code / Cursor with a `.py` file → preserve technical terms

Detect via `osascript`'s `name of first application process whose frontmost is true` plus AX accessibility for the focused doc URL. Config-driven in `~/.voice-cli/config.yaml`.

VoiceInk and SuperWhisper both call this "Power Mode." Pattern is well-validated.

### Inline editing commands

Talon's killer feature: dictation-embedded commands.

- "scratch that" → delete the previous sentence
- "new line" → `\n`
- "open paren" / "close paren" → `(` / `)`
- "cap that" → capitalize the previous word
- "all caps that" → uppercase

Implement as a regex pass *before* the LLM cleanup so the LLM doesn't see the command tokens. Configurable map in `~/.voice-cli/commands.yaml`.

### Semantic endpointing instead of fixed-time silence

We currently end recording after `silence_duration` (1.2s) of silence. But if the partial transcript ends mid-clause ("...and so I", then pause to think), VAD cuts you off. Soniox and AssemblyAI Universal Streaming use a small LM that detects "this sounds like a finished sentence."

Cheap heuristic version: if the trailing word is a connective (`and`, `so`, `but`, `because`, `or`, `with`), extend silence threshold by 1s. ~20 lines in `vad_record.py`.

### Mic permission deep-link in failure notifications

When the daemon fails to open the audio stream because Raycast/Python lost Microphone permission, surface a clickable notification that deep-links to `x-apple.systempreferences:com.apple.preference.security?Privacy_Microphone`. Saves the user a Settings navigation.

Currently the failure just logs to the file and shows a generic error toast.

## Bigger projects worth considering

### Push-to-talk on hold + toggle on tap (same hotkey)

Hold the hotkey = record until release. Tap = toggle (current behavior). Requires hooking key-down/key-up events outside Raycast, which doesn't expose them — would need a small Karabiner-Elements rule or a native helper.

Worth doing once you find yourself getting cut off mid-thought by VAD. We left this off the priority list because the current VAD + 1.2s silence covers 95% of normal dictation.

### Vocabulary feedback loop

Track which words the LLM cleanup most often "fixes" from Whisper output (e.g. "clawde" → "Claude"). Auto-append the most common ones to `~/.voice-cli/dictionary.txt` so future raw transcripts get them right. Like a self-tuning dictionary.

## Explicitly **not** worth doing

- **Aqua-style natural-language editing** ("change foo to bar") — large LLM call, marginal benefit over just re-dictating.
- **Full cloud rewrite of every transcript** — privacy + latency cost not worth it. Our trigger-based selective cleanup is better.
- **Custom wake word** ("hey computer") — wake-word models add idle CPU; a hotkey is faster and more reliable.

## Sources from the research

[Wispr Flow paste & fallback](https://docs.wisprflow.ai/articles/7971211038-fix-text-not-pasting-after-dictation) · [Wispr Flow Command Mode](https://docs.wisprflow.ai/articles/4816967992-how-to-use-command-mode) · [SuperWhisper Super Mode](https://superwhisper.com/docs/modes/super) · [VoiceInk features](https://tryvoiceink.com/features/) · [Talon community commands](https://github.com/talonhub/community) · [Moonshine repo](https://github.com/usefulsensors/moonshine) · [Soniox endpoint detection](https://soniox.com/docs/stt/rt/endpoint-detection) · [OpenAI Whisper prompting guide](https://developers.openai.com/cookbook/examples/whisper_prompting_guide) · [parakeet-mlx](https://github.com/senstella/parakeet-mlx)
