#!/bin/sh
# Build the native Taskrivet.app from the Swift package in macos/.
#
# Produces an unsigned, ad-hoc-signed developer build (same posture as the
# Electron alpha): no signing identity is acquired and no notarization is
# attempted. The app still needs a Python 3.11+ with the taskrivet package
# importable; it probes TASKRIVET_PYTHON, stock interpreter paths, and PATH.
#
# Usage: macos/scripts/build_app.sh [output-directory]
# Default output: macos/build/Taskrivet.app
set -eu

cd "$(dirname "$0")/.."
OUT_DIR="${1:-build}"
APP="$OUT_DIR/Taskrivet.app"

# SwiftUI's property wrappers ship as macro plugins in recent SDKs; the
# Command Line Tools lack them, so prefer a full Xcode install when present.
if [ -d /Applications/Xcode.app/Contents/Developer ]; then
    export DEVELOPER_DIR=/Applications/Xcode.app/Contents/Developer
fi
BINARY=".build/release/TaskrivetMac"

swift build -c release

if [ ! -f "$BINARY" ]; then
    echo "build_app: expected binary at $BINARY" >&2
    exit 1
fi

VERSION="$(git -C .. describe --tags --always --dirty 2>/dev/null || echo 'dev')"

rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$BINARY" "$APP/Contents/MacOS/Taskrivet"
chmod +x "$APP/Contents/MacOS/Taskrivet"
# SwiftPM release binaries retain debug symbols with absolute build paths.
# Strip the packaged copy before signing; failure must stop packaging.
/usr/bin/strip -S "$APP/Contents/MacOS/Taskrivet"

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key><string>Taskrivet</string>
    <key>CFBundleDisplayName</key><string>Taskrivet</string>
    <key>CFBundleExecutable</key><string>Taskrivet</string>
    <key>CFBundleIdentifier</key><string>org.taskrivet.native</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>CFBundleShortVersionString</key><string>${VERSION}</string>
    <key>CFBundleVersion</key><string>${VERSION}</string>
    <key>LSMinimumSystemVersion</key><string>14.0</string>
    <key>LSApplicationCategoryType</key><string>public.app-category.developer-tools</string>
    <key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
PLIST

# Ad-hoc signature so the bundle is stable across launches on this machine.
codesign --force --sign - "$APP" >/dev/null 2>&1 || true

echo "Built $APP (version $VERSION)"
echo "It is an unsigned developer build; it replaces nothing by itself."
