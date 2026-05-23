#!/bin/bash

# Required parameters:
# @raycast.schemaVersion 1
# @raycast.title Voice Revert
# @raycast.mode silent
# @raycast.packageName Voice CLI

# Optional parameters:
# @raycast.icon ↩️
# @raycast.description Delete the last LLM-cleaned transcript and paste the raw version (pre-cleanup).

VENV_PYTHON="/Users/avini/.voice-cli-venv/bin/python"
CLIENT="/Users/avini/Documents/GitHub/voice-cli/bin/voice-cli-client"

"$VENV_PYTHON" "$CLIENT" --revert 2>>"$HOME/.voice-cli/raycast.log"
