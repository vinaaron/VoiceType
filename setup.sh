#!/bin/bash
# Voice CLI Setup Script
# One-command installation for voice-to-text CLI tool

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$HOME/.voice-cli-venv"
CONFIG_DIR="$HOME/.voice-cli"
RAYCAST_DIR="$HOME/Library/Scripts/Raycast"

echo "=== Voice CLI Setup ==="
echo ""

# Check for Homebrew
if ! command -v brew &> /dev/null; then
    echo "Error: Homebrew is required. Install from https://brew.sh"
    exit 1
fi

# Find a compatible Python version (3.11 or 3.12 recommended, 3.14 has issues)
find_python() {
    for py in python3.12 python3.11 python3.13; do
        if command -v "$py" &> /dev/null; then
            version=$("$py" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null)
            major=$(echo "$version" | cut -d. -f1)
            minor=$(echo "$version" | cut -d. -f2)
            # Use Python 3.11-3.13 (avoid 3.14 which has av compilation issues)
            if [ "$major" = "3" ] && [ "$minor" -ge 11 ] 2>/dev/null && [ "$minor" -le 13 ] 2>/dev/null; then
                echo "$py"
                return 0
            fi
        fi
    done
    echo ""
    return 1
}

PYTHON=$(find_python)
if [ -z "$PYTHON" ]; then
    echo "Error: Python 3.11, 3.12, or 3.13 is required."
    echo "Python 3.14 has compatibility issues with faster-whisper dependencies."
    echo "Install with: pyenv install 3.12 && pyenv global 3.12"
    exit 1
fi
echo "Using Python: $PYTHON ($($PYTHON --version))"

# Install sox if not present
echo "[1/7] Checking sox..."
if ! command -v sox &> /dev/null; then
    echo "Installing sox..."
    brew install sox
else
    echo "sox already installed"
fi

# Install portaudio (required for PyAudio)
echo "[2/7] Checking portaudio..."
if ! brew list portaudio &>/dev/null; then
    echo "Installing portaudio..."
    brew install portaudio
else
    echo "portaudio already installed"
fi

# Create virtual environment
echo "[3/7] Setting up Python virtual environment..."
if [ -d "$VENV_DIR" ]; then
    echo "Removing existing venv (may have incompatible Python version)..."
    rm -rf "$VENV_DIR"
fi
"$PYTHON" -m venv "$VENV_DIR"

# Upgrade pip and install dependencies
echo "[4/7] Installing Python dependencies..."
"$VENV_DIR/bin/pip" install --upgrade pip --quiet
"$VENV_DIR/bin/pip" install -r "$SCRIPT_DIR/requirements.txt" --quiet
"$VENV_DIR/bin/pip" install rumps --quiet
"$VENV_DIR/bin/pip" install moonshine-voice --quiet

# Download faster-whisper model and Silero VAD
echo "[5/7] Downloading models (Whisper + Silero VAD)..."
"$VENV_DIR/bin/python" -c "
from faster_whisper import WhisperModel
from silero_vad import load_silero_vad
print('Downloading Whisper base.en model...')
model = WhisperModel('base.en', device='cpu', compute_type='int8')
print('Whisper model ready!')
print('Loading Silero VAD model...')
vad = load_silero_vad()
print('Silero VAD ready!')
print('All models downloaded successfully!')
"

# Create config directory
echo "[6/7] Creating config directory..."
mkdir -p "$CONFIG_DIR"

# Create default config if it doesn't exist (prefer YAML for comments)
if [ ! -f "$CONFIG_DIR/config.yaml" ] && [ ! -f "$CONFIG_DIR/config.json" ]; then
    cat > "$CONFIG_DIR/config.yaml" << 'EOF'
# Voice CLI Configuration
# Edit these settings to customize behavior

# Whisper model to use (speed vs accuracy tradeoff)
# Options: tiny.en (fastest), base.en (default), small.en, medium.en, large-v3 (most accurate)
model: base.en

# How long to wait for silence before stopping recording (seconds)
silence_duration: 2.0

# Silence detection threshold (lower = more sensitive)
silence_threshold: "3%"

# Play Ping/Pop sounds for audio feedback
sound_feedback: true

# Convert spoken numbers to digits (e.g., "one" -> "1")
convert_numbers: true
EOF
    echo "Created default config at $CONFIG_DIR/config.yaml"
fi

# Setup Raycast script
echo "[7/7] Setting up Raycast integration..."
mkdir -p "$RAYCAST_DIR"
cp "$SCRIPT_DIR/raycast/voice-toggle.sh" "$RAYCAST_DIR/"
chmod +x "$RAYCAST_DIR/voice-toggle.sh"

# Make bin executable
chmod +x "$SCRIPT_DIR/bin/voice-cli"

echo ""
echo "=== Setup Complete! ==="
echo ""
echo "Next steps:"
echo "1. Open Raycast Settings (Cmd+,)"
echo "2. Go to Extensions > Script Commands"
echo "3. Click 'Add Directories' and add: $RAYCAST_DIR"
echo "4. Search for 'Reload Script Directories' in Raycast and run it"
echo "5. Find 'Voice Toggle' in Extensions and assign hotkey: Control+Option+V"
echo ""
echo "Required Permissions:"
echo "- Microphone: System Settings > Privacy & Security > Microphone > Enable for your terminal"
echo "- Accessibility: System Settings > Privacy & Security > Accessibility > Enable for your terminal"
echo ""
echo "Test by running: $SCRIPT_DIR/bin/voice-cli"
