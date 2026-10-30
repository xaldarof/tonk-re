#!/bin/sh
# Update apktool to a newer version (default 3.0.3), installed where the `apktool`
# command already looks. Verifies the download before replacing anything.
# Usage:  ./update-apktool.sh [version]
set -e
VER="${1:-3.0.3}"
URL="https://github.com/iBotPeaches/Apktool/releases/download/v${VER}/apktool_${VER}.jar"
TMP="$(mktemp -t apktool).jar"
trap 'rm -f "$TMP"' EXIT

echo "[*] downloading apktool $VER ..."
if ! curl -fL --progress-bar -o "$TMP" "$URL"; then
  echo "[-] download failed (check your connection or the version number). Old apktool left untouched."
  exit 1
fi

# verify it is a real, runnable apktool jar before touching anything (the most reliable check:
# run it and read the version — internal jar layout differs between apktool 2.x and 3.x)
if ! unzip -l "$TMP" >/dev/null 2>&1; then
  echo "[-] downloaded file is not a valid jar/zip (got $(wc -c < "$TMP") bytes). Aborting; nothing changed."
  exit 1
fi
GOT="$(java -jar "$TMP" --version 2>/dev/null | tr -d '\r' | grep -Eo '[0-9]+\.[0-9]+(\.[0-9]+)?' | tail -1)"
if [ -z "$GOT" ]; then
  echo "[-] downloaded jar did not run (java -jar ... --version produced no version). Aborting; nothing changed."
  exit 1
fi
echo "[+] verified: downloaded apktool reports version $GOT"

WRAP="$(command -v apktool || true)"
DST=""
if [ -n "$WRAP" ]; then
  REAL="$(python3 -c 'import os,sys;print(os.path.realpath(sys.argv[1]))' "$WRAP" 2>/dev/null || echo "$WRAP")"
  DIR="$(dirname "$REAL")"
  if [ -f "$DIR/apktool.jar" ]; then DST="$DIR/apktool.jar"
  else HI="$(ls "$DIR"/apktool_*.jar 2>/dev/null | sort -V | tail -1)"; [ -n "$HI" ] && DST="$DIR/apktool.jar"; fi
fi

if [ -n "$DST" ]; then
  if [ -w "$DST" ] || [ -w "$(dirname "$DST")" ]; then
    cp "$TMP" "$DST"; echo "[+] installed -> $DST"
  else
    echo "[*] $DST is not writable; using sudo ..."
    sudo cp "$TMP" "$DST" && echo "[+] installed -> $DST"
  fi
else
  # no system apktool found: install a private copy and a wrapper under ~/.tonkre/bin
  mkdir -p "$HOME/.tonkre/bin"
  cp "$TMP" "$HOME/.tonkre/bin/apktool.jar"
  printf '#!/bin/sh\nexec java -jar "%s/.tonkre/bin/apktool.jar" "$@"\n' "$HOME" > "$HOME/.tonkre/bin/apktool"
  chmod +x "$HOME/.tonkre/bin/apktool"
  echo "[+] installed -> ~/.tonkre/bin/apktool"
  echo "[!] add ~/.tonkre/bin to the FRONT of your PATH so it wins over the old apktool:"
  echo "    echo 'export PATH=\"\$HOME/.tonkre/bin:\$PATH\"' >> ~/.zprofile && source ~/.zprofile"
fi

echo "[*] now reports: $(apktool --version 2>/dev/null || echo '??')"
echo "[*] next: in TONK-RE re-decompile this app with FORCE checked, then BUILD (full resource rebuild should work)."
