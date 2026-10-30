# tonk-re installer for Windows (PowerShell):  powershell -ExecutionPolicy Bypass -File install.ps1
# Sets up launchers, the Claude Code skill + MCP server and a desktop shortcut. The toolchain (JDK, jadx,
# apktool, Android build/platform-tools, frida) is installed from the app's SETUP panel or `tonkre setup`.
# New users: just double-click Setup-TONK-RE.cmd, which installs uv, runs this, and opens the app.
$ErrorActionPreference = "Stop"
$Dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Bin = Join-Path $env:USERPROFILE ".local\bin"

function Need($n) { [bool](Get-Command $n -ErrorAction SilentlyContinue) }
Write-Host "== tonk-re installer (Windows)"
if (-not (Need uv)) {
  Write-Host "[-] uv missing:  powershell -c `"irm https://astral.sh/uv/install.ps1 | iex`"   (or run Setup-TONK-RE.cmd)"
  exit 1
}

New-Item -ItemType Directory -Force -Path $Bin | Out-Null
"@uv run --quiet --script `"$Dir\gui.py`" %*"       | Set-Content -Encoding ASCII (Join-Path $Bin "tonkre-gui.cmd")
"@uv run --quiet --script `"$Dir\server.py`" cli %*" | Set-Content -Encoding ASCII (Join-Path $Bin "tonkre.cmd")
Write-Host "[+] launchers: $Bin\tonkre-gui.cmd, $Bin\tonkre.cmd"

$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($userPath -notlike "*$Bin*") {
  [Environment]::SetEnvironmentVariable("Path", "$userPath;$Bin", "User")
  Write-Host "[+] added $Bin to your PATH (open a new terminal)"
}

$Skill = Join-Path $env:USERPROFILE ".claude\skills\tonk-re"
New-Item -ItemType Directory -Force -Path $Skill | Out-Null
Copy-Item (Join-Path $Dir "skill\SKILL.md") $Skill -Force

if (Need claude) {
  # PS 5.1 + EAP=Stop turns native stderr into a terminating error; "not found" on first install is expected
  try { claude mcp remove --scope user tonk-re 2>$null | Out-Null } catch {}
  claude mcp add --scope user tonk-re -- uv run --quiet --script "$Dir\server.py"
  Write-Host "[+] MCP server registered with Claude Code"
} else { Write-Host "[!] claude CLI not found; skipped MCP registration" }

# Desktop shortcut: uvw + --gui-script runs TONK-RE without a console window (the server stops when its window
# closes; log in ~/.tonkre/gui.log). Falls back to the console launcher if uvw isn't available.
$lnk = (New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path ([Environment]::GetFolderPath("Desktop")) "TONK-RE.lnk"))
$uvw = (Get-Command uvw -ErrorAction SilentlyContinue).Source
if ($uvw) {
  $lnk.TargetPath = $uvw; $lnk.Arguments = "run --quiet --gui-script `"$Dir\gui.py`""; $lnk.WorkingDirectory = $Dir
} else {
  $lnk.TargetPath = Join-Path $Bin "tonkre-gui.cmd"; $lnk.WindowStyle = 7
}
$lnk.Save()
Write-Host "[+] desktop shortcut: TONK-RE"

Write-Host "`n== toolchain"
uv run --quiet --script "$Dir\server.py" cli setup status
Write-Host "`n[+] done. run: tonkre-gui   (missing tools: SETUP > INSTALL ALL in the app, or: tonkre setup all)"
