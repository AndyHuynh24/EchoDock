#!/bin/bash
# Builds OneDock.app in the Dock folder: a small menu-bar app that starts Dock.
# Safe to run again. (macOS remembers permissions for the app between builds
# as long as the launcher program itself doesn't change.)
set -e
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
APP="$ROOT/OneDock.app"

mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp app/Info.plist "$APP/Contents/Info.plist"
echo "$ROOT" > "$APP/Contents/Resources/root"

# The program: rebuilt only when launcher.c changed, so permissions stay.
if [ ! -f "$APP/Contents/MacOS/OneDock" ] || [ app/launcher.c -nt "$APP/Contents/MacOS/OneDock" ]; then
  clang -O2 -o "$APP/Contents/MacOS/OneDock" app/launcher.c
fi

# The icon, made from the face icon of the phone app.
if [ ! -f "$APP/Contents/Resources/AppIcon.icns" ]; then
  ICONSET="$(mktemp -d)/AppIcon.iconset"
  mkdir -p "$ICONSET"
  for size in 16 32 128 256 512; do
    sips -z $size $size server/static/icon-512.png --out "$ICONSET/icon_${size}x${size}.png" >/dev/null
    sips -z $((size * 2)) $((size * 2)) server/static/icon-512.png --out "$ICONSET/icon_${size}x${size}@2x.png" >/dev/null
  done
  iconutil -c icns "$ICONSET" -o "$APP/Contents/Resources/AppIcon.icns"
fi

codesign --force --sign - "$APP" >/dev/null 2>&1 || true
echo "Built $APP"
