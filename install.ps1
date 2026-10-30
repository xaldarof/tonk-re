# tonk-re installer for Windows (PowerShell):  powershell -ExecutionPolicy Bypass -File install.ps1
$ErrorActionPreference = "Stop"
$Dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Bin = Join-Path $env:USERPROFILE ".local\bin"

function Need($n) { [bool](Get-Command $n -ErrorAction SilentlyContinue) }
Write-Host "== tonk-re installer (Windows)"
$missing = $false
if (-not (Need uv))      { Write-Host "[-] uv missing:      powershell -c `"irm https://astral.sh/uv/install.ps1 | iex`""; $missing = $true }
if (-not (Need java))    { Write-Host "[-] java missing:    winget install Microsoft.OpenJDK.21"; $missing = $true }
if (-not (Need jadx))    { Write-Host "[-] jadx missing:    scoop install jadx   (or GitHub releases: skylot/jadx)"; $missing = $true }
if (-not (Need apktool)) { Write-Host "[-] apktool missing: scoop install apktool   (or https://apktool.org/docs/install)"; $missing = $true }
if (-not (Need adb))     { Write-Host "[!] adb not on PATH (optional). %LOCALAPPDATA%\Android\Sdk is auto-detected." }

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
  claude mcp remove --scope user tonk-re 2>$null | Out-Null
  claude mcp add --scope user tonk-re -- uv run --quiet --script "$Dir\server.py"
  Write-Host "[+] MCP server registered with Claude Code"
} else { Write-Host "[!] claude CLI not found; skipped MCP registration" }

# Desktop shortcut
$lnk = (New-Object -ComObject WScript.Shell).CreateShortcut((Join-Path ([Environment]::GetFolderPath("Desktop")) "TONK-RE.lnk"))
$lnk.TargetPath = Join-Path $Bin "tonkre-gui.cmd"; $lnk.WindowStyle = 7; $lnk.Save()
Write-Host "[+] desktop shortcut: TONK-RE"

if ($missing) { Write-Host "[!] install the missing tools above, then run: tonkre-gui" } else { Write-Host "[+] done. run: tonkre-gui" }
