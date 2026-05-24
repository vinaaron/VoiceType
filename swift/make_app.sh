#!/bin/bash
# Bundle the swift build artefact into a proper VoiceCLIVisual.app and
# install it under ~/Applications/. macOS TCC (Accessibility, Microphone)
# remembers permissions by bundle ID, so we need a .app structure for
# the grant to persist across rebuilds.
#
# Usage:  ./make_app.sh           # build + install + open
#         ./make_app.sh build     # just rebuild + repack (skip open)
#         ./make_app.sh open      # open the already-installed app

set -e

SWIFT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_NAME="VoiceCLIVisual"
APP_DEST="$HOME/Applications/$APP_NAME.app"
INFO_PLIST="$SWIFT_DIR/Resources/Info.plist"
ACTION="${1:-all}"

cd "$SWIFT_DIR"

if [ "$ACTION" != "open" ]; then
    echo "==> Building release binary..."
    swift build -c release

    BIN="$SWIFT_DIR/.build/release/$APP_NAME"
    if [ ! -f "$BIN" ]; then
        echo "ERROR: expected binary at $BIN, build must have failed."
        exit 1
    fi

    echo "==> Packaging into $APP_DEST"
    rm -rf "$APP_DEST"
    mkdir -p "$APP_DEST/Contents/MacOS"
    mkdir -p "$APP_DEST/Contents/Resources"
    cp "$BIN"        "$APP_DEST/Contents/MacOS/$APP_NAME"
    cp "$INFO_PLIST" "$APP_DEST/Contents/Info.plist"
    chmod +x "$APP_DEST/Contents/MacOS/$APP_NAME"

    # Ad-hoc sign so macOS trusts the bundle's identity (TCC needs a
    # stable identity for permission grants; without signing, every
    # rebuild looks like a new app and re-prompts for permission).
    echo "==> Ad-hoc codesigning"
    codesign --force --deep --sign - "$APP_DEST"
fi

if [ "$ACTION" = "all" ] || [ "$ACTION" = "open" ]; then
    echo ""
    echo "==> Killing any old instance"
    pkill -if "$APP_NAME" 2>/dev/null || true
    sleep 0.5

    echo "==> Opening $APP_DEST"
    open "$APP_DEST"

    echo ""
    cat <<'EOF'
✅ VoiceCLIVisual is now running in the background (no Dock icon).

Look for the 🎤 icon in your menu bar. The first time you press
⌃⌥V (Control+Option+V), macOS will prompt you to grant:

  1. Microphone access  — for VoiceCLI to listen to your voice
  2. Accessibility      — for it to paste the transcribed text

Grant both when prompted; the prompts only happen once.

To enable auto-start at login, click the 🎤 menu bar icon →
"Open at Login". Or open System Settings → General → Login Items.
EOF
fi
