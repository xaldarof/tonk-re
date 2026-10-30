#!/bin/sh
# tonk-re installer for macOS and Linux
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
BIN="$HOME/.local/bin"
OS="$(uname -s)"

need() { command -v "$1" >/dev/null 2>&1; }
hint() {
  case "$OS" in
    Darwin) echo "    brew install $2" ;;
    Linux)  echo "    $3" ;;
  esac
}

echo "== tonk-re installer ($OS)"
missing=0
need uv      || { echo "[-] uv missing";      echo "    curl -LsSf https://astral.sh/uv/install.sh | sh"; missing=1; }
need java    || { echo "[-] java missing";    hint java openjdk "sudo apt install default-jdk   (or dnf install java-17-openjdk)"; missing=1; }
need jadx    || { echo "[-] jadx missing";    hint jadx jadx "download from https://github.com/skylot/jadx/releases and add bin/ to PATH"; missing=1; }
need apktool || { echo "[-] apktool missing"; hint apktool apktool "sudo apt install apktool   (or see https://apktool.org/docs/install)"; missing=1; }
need adb     || echo "[!] adb not on PATH (optional, for INSTALL). Android SDK platform-tools will be auto-detected."
[ "$OS" = Linux ] && ! need zenity && ! need kdialog && echo "[!] install zenity or kdialog for the BROWSE file dialog (drag & drop works without it)"

mkdir -p "$BIN"
printf '#!/bin/sh\nexec uv run --quiet --script "%s/gui.py" "$@"\n' "$DIR" > "$BIN/tonkre-gui"
printf '#!/bin/sh\nexec uv run --quiet --script "%s/server.py" cli "$@"\n' "$DIR" > "$BIN/tonkre"
chmod +x "$BIN/tonkre-gui" "$BIN/tonkre" "$DIR/gui.py" "$DIR/server.py"
echo "[+] launchers: $BIN/tonkre-gui, $BIN/tonkre"

mkdir -p "$HOME/.claude/skills/tonk-re" && cp "$DIR/skill/SKILL.md" "$HOME/.claude/skills/tonk-re/SKILL.md"
if need claude; then
  claude mcp remove --scope user tonk-re >/dev/null 2>&1 || true
  claude mcp add --scope user tonk-re -- uv run --quiet --script "$DIR/server.py" && echo "[+] MCP server registered with Claude Code"
else
  echo "[!] claude CLI not found; skipped MCP registration"
fi

case ":$PATH:" in *":$BIN:"*) ;; *) echo "[!] add $BIN to PATH:  echo 'export PATH=\"\$HOME/.local/bin:\$PATH\"' >> ~/.profile";; esac
[ $missing = 1 ] && echo "[!] install the missing tools above, then run: tonkre-gui" || echo "[+] done. run: tonkre-gui"
