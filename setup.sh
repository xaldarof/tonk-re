#!/bin/sh
# TONK-RE one-click setup for macOS / Linux.
# Installs uv (per-user, no sudo) if needed, runs install.sh, then opens TONK-RE, whose
# SETUP panel installs the toolchain (JDK, jadx, apktool, Android tools, frida) with one button.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
export PATH="$HOME/.local/bin:$PATH"
echo "== TONK-RE setup"
if ! command -v uv >/dev/null 2>&1; then
  echo "[*] installing uv (Python runner, per-user) ..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi
sh "$DIR/install.sh"
echo
echo "[*] opening TONK-RE: click SETUP / INSTALL ALL to install the toolchain"
nohup "$HOME/.local/bin/tonkre-gui" >/dev/null 2>&1 &
sleep 3
