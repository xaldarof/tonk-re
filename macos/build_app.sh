#!/bin/sh
# Build TONK-RE.app (macOS) into ~/Applications and optionally pin it to the Dock: ./build_app.sh [--dock]
set -e
HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$HERE")"
APP="$HOME/Applications/TONK-RE.app"
TMP="$(mktemp -d)"

echo "[*] rendering icon"
uv run --quiet --script "$HERE/make_icon.py" "$TMP/icon.png"
mkdir "$TMP/AppIcon.iconset"
for s in 16 32 128 256 512; do
  sips -z $s $s "$TMP/icon.png" --out "$TMP/AppIcon.iconset/icon_${s}x${s}.png" >/dev/null
  d=$((s * 2)); sips -z $d $d "$TMP/icon.png" --out "$TMP/AppIcon.iconset/icon_${s}x${s}@2x.png" >/dev/null
done

echo "[*] preparing python environment (first run downloads deps)"
uv sync --quiet --python-preference only-managed --script "$ROOT/gui.py"

echo "[*] assembling $APP"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
iconutil -c icns "$TMP/AppIcon.iconset" -o "$APP/Contents/Resources/AppIcon.icns"
cp "$TMP/icon.png" "$APP/Contents/Resources/AppIcon.png"

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>CFBundleName</key><string>TONK-RE</string>
  <key>CFBundleDisplayName</key><string>TONK-RE</string>
  <key>CFBundleIdentifier</key><string>local.tonkre.app</string>
  <key>CFBundleVersion</key><string>1.0</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleExecutable</key><string>TONK-RE</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>LSMinimumSystemVersion</key><string>11.0</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>LSApplicationCategoryType</key><string>public.app-category.developer-tools</string>
</dict></plist>
PLIST

cat > "$APP/Contents/MacOS/TONK-RE" <<LAUNCH
#!/bin/zsh
# Apps launched from the Dock get a bare PATH; pull in the user's shell PATH (jadx, apktool, uv, claude, SDK)
LP=\$(/bin/zsh -ilc 'print -r -- \$PATH' </dev/null 2>/dev/null | tail -1)
export PATH="\$HOME/.local/bin:/opt/homebrew/bin:/usr/local/bin:\$LP:\$PATH"
export TONKRE_ICON="\$(dirname "\$0")/../Resources/AppIcon.png"
mkdir -p "\$HOME/.tonkre"
exec >"\$HOME/.tonkre/app.log" 2>&1
cd "$ROOT"
PY=\$(uv python find --python-preference only-managed --script gui.py 2>/dev/null)
if [ ! -x "\$PY" ]; then uv sync --quiet --python-preference only-managed --script gui.py; PY=\$(uv python find --python-preference only-managed --script gui.py); fi
# exec keeps this PID, so the Dock shows TONK-RE's icon rather than Python's
exec "\$PY" gui.py --native
LAUNCH
chmod +x "$APP/Contents/MacOS/TONK-RE"
rm -rf "$TMP"
touch "$APP"
/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister -f "$APP" 2>/dev/null || true
echo "[+] built $APP"

if [ "$1" = "--dock" ]; then
  if defaults read com.apple.dock persistent-apps 2>/dev/null | grep -q "TONK-RE.app"; then
    echo "[=] already in Dock"
  else
    defaults write com.apple.dock persistent-apps -array-add \
      "<dict><key>tile-data</key><dict><key>file-data</key><dict><key>_CFURLString</key><string>file://$APP/</string><key>_CFURLStringType</key><integer>15</integer></dict></dict></dict>"
    killall Dock
    echo "[+] pinned to Dock"
  fi
fi
