#!/bin/sh
# tonk-re installer for macOS and Linux: launchers, Claude Code skill + MCP server.
# The toolchain (JDK, jadx, apktool, Android build/platform-tools, frida) is installed from the app's
# SETUP panel or `tonkre setup`. New users: run ./setup.sh (or double-click Setup-TONK-RE.command on macOS).
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
BIN="$HOME/.local/bin"
OS="$(uname -s)"

need() { command -v "$1" >/dev/null 2>&1; }

echo "== tonk-re installer ($OS)"
need uv || { echo "[-] uv missing:  curl -LsSf https://astral.sh/uv/install.sh | sh   (or run ./setup.sh)"; exit 1; }
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

printf '\n== toolchain\n'
uv run --quiet --script "$DIR/server.py" cli setup status || true
printf '\n[+] done. run: tonkre-gui   (missing tools: SETUP > INSTALL ALL in the app, or: tonkre setup all)\n'
