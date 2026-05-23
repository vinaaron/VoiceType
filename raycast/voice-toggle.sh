#!/bin/bash

# Required parameters:
# @raycast.schemaVersion 1
# @raycast.title Voice Toggle
# @raycast.mode silent
# @raycast.packageName Voice CLI

# Optional parameters:
# @raycast.icon 🎤
# @raycast.description Voice-to-text for terminal sessions. Speak and text appears in your terminal.

# Documentation:
# @raycast.author avini
# @raycast.authorURL https://github.com/avini

# Use absolute paths (~ might not expand correctly in all contexts)
VENV_PYTHON="/Users/avini/.voice-cli-venv/bin/python"
CLIENT="/Users/avini/Documents/GitHub/voice-cli/bin/voice-cli-client"

# Fast path: client talks to the daemon over a Unix socket. If the daemon
# isn't up, the client transparently spawns it in the background and falls
# back to direct invocation for this press. Subsequent presses are fast.
"$VENV_PYTHON" "$CLIENT" 2>>"$HOME/.voice-cli/raycast.log"
