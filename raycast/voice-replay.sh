#!/bin/bash

# Required parameters:
# @raycast.schemaVersion 1
# @raycast.title Voice Replay
# @raycast.mode silent
# @raycast.packageName Voice CLI

# Optional parameters:
# @raycast.icon 🔁
# @raycast.description Re-paste the most recent voice transcript. Useful when Cmd+V silently failed.

VENV_PYTHON="/Users/avini/.voice-cli-venv/bin/python"
CLIENT="/Users/avini/Documents/GitHub/voice-cli/bin/voice-cli-client"

"$VENV_PYTHON" "$CLIENT" --replay 2>>"$HOME/.voice-cli/raycast.log"
