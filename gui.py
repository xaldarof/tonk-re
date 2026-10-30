#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.10"
# dependencies = ["mcp>=1.2,<2", "defusedxml>=0.7", "pywebview>=5.3; sys_platform == 'darwin'"]
# ///
"""tonk-re GUI: local retro-terminal web app for APK decompile / edit / rebuild / sign.

Run:  uv run --script gui.py            (opens a Chromium/Edge app window)
      uv run --script gui.py --browser  (opens default browser tab)
Works on macOS, Windows and Linux. Binds to 127.0.0.1 only; every API call needs the per-launch token.
"""
from __future__ import annotations

import glob
import json
import os
import secrets
import shutil
import subprocess
import sys
import threading
import webbrowser
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).parent))
import server as core  # noqa: E402

IS_WIN, IS_MAC = sys.platform == "win32", sys.platform == "darwin"
HERE = Path(__file__).parent
HOME = Path(os.environ.get("TONKRE_HOME", Path.home() / ".tonkre"))
UPLOADS = HOME / "uploads"
KEYSTORE = HOME / "debug.keystore"
KS_PASS, KS_ALIAS = "android", "tonkre"
TOKEN = secrets.token_urlsafe(24)
PORT = int(os.environ.get("TONKRE_PORT", "7777"))


def _default_sdk() -> Path:
    for var in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        if os.environ.get(var):
            return Path(os.environ[var])
    if IS_WIN:
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "Android" / "Sdk"
    if IS_MAC:
        return Path.home() / "Library" / "Android" / "sdk"
    return Path.home() / "Android" / "Sdk"


SDK = _default_sdk()
# Windows ships SDK tools as .bat/.exe wrappers
EXTS = [".bat", ".exe", ".cmd", ""] if IS_WIN else [""]


def _which_in(dirs: list[Path], name: str) -> str | None:
    for d in dirs:
        for ext in EXTS:
            if (d / (name + ext)).is_file():
                return str(d / (name + ext))
    return None


def build_tool(name: str) -> str | None:
    """Find a build-tools binary (apksigner, zipalign) in PATH or the newest SDK build-tools."""
    if shutil.which(name):
        return shutil.which(name)
    dirs = sorted((Path(p) for p in glob.glob(str(SDK / "build-tools" / "*"))),
                  key=lambda p: [int(x) if x.isdigit() else 0 for x in p.name.split(".")], reverse=True)
    return _which_in(dirs, name)


def tool(name: str) -> str | None:
    if name == "adb":
        return shutil.which("adb") or _which_in([SDK / "platform-tools"], "adb")
    if name == "claude":
        return shutil.which("claude") or _which_in([Path.home() / ".local" / "bin"], "claude")
    if name in ("jadx", "apktool", "keytool", "jarsigner"):
        return shutil.which(name)
    return build_tool(name)


# ---------- tool availability / install hints ----------

_OSKEY = "win32" if IS_WIN else "darwin" if IS_MAC else "linux"
INSTALL_HINTS = {
    "jadx": {"darwin": "brew install jadx", "win32": "scoop install jadx",
             "linux": "download from github.com/skylot/jadx/releases and add bin/ to PATH"},
    "apktool": {"darwin": "brew install apktool", "win32": "scoop install apktool",
                "linux": "sudo apt install apktool  (or see apktool.org/docs/install)"},
    "apksigner": {"darwin": "install Android SDK build-tools (Android Studio ▸ SDK Manager)",
                  "win32": "install Android SDK build-tools (Android Studio ▸ SDK Manager)",
                  "linux": "install Android SDK build-tools (Android Studio ▸ SDK Manager)"},
    "zipalign": {k: "install Android SDK build-tools (Android Studio ▸ SDK Manager)"
                 for k in ("darwin", "win32", "linux")},
    "adb": {"darwin": "brew install android-platform-tools  (or Android SDK platform-tools)",
            "win32": "install Android SDK platform-tools", "linux": "sudo apt install adb"},
    "keytool": {k: "install a JDK (comes with Java)" for k in ("darwin", "win32", "linux")},
    "frida": {k: "pipx install frida-tools  (only needed to RUN hooks)" for k in ("darwin", "win32", "linux")},
    "claude": {k: "see claude.com/claude-code  (optional: the AI assistant)" for k in ("darwin", "win32", "linux")},
}


def hint(name: str) -> str:
    return INSTALL_HINTS.get(name, {}).get(_OSKEY, "see the README")


_APKTOOL_VER = None  # cached across requests


def apktool_version() -> str | None:
    """apktool's reported version string, e.g. '2.9.3' (cached)."""
    global _APKTOOL_VER
    if _APKTOOL_VER is None:
        at = tool("apktool")
        if not at:
            return None
        try:
            r = subprocess.run([at, "--version"], capture_output=True, text=True, timeout=30)
            _APKTOOL_VER = (r.stdout + r.stderr).strip().splitlines()[-1].strip() if r.returncode == 0 else ""
        except Exception:
            _APKTOOL_VER = ""
    return _APKTOOL_VER or None


def require(out, names: list[str]) -> bool:
    """Stream a clear, OS-specific message for any missing tool. Returns True only if all present."""
    missing = [n for n in names if not tool(n)]
    if not missing:
        return True
    out(f"[-] missing required tool(s): {', '.join(missing)}\n")
    for n in missing:
        out(f"    install {n}:  {hint(n)}\n")
    out("    then restart TONK-RE (or re-run ./install.sh to re-check).\n")
    return False


# ---------- OS integration ----------

def pick_file() -> str:
    """Native file dialog. Returns '' if cancelled or no dialog is available."""
    try:
        if IS_MAC:
            cmd = ["osascript", "-e", 'POSIX path of (choose file with prompt "Select APK")']
        elif IS_WIN:
            ps = ("Add-Type -AssemblyName System.Windows.Forms;"
                  "$f=New-Object System.Windows.Forms.OpenFileDialog;"
                  "$f.Filter='Android packages|*.apk;*.xapk;*.apks;*.apkm|All files|*.*';"
                  "if($f.ShowDialog() -eq 'OK'){$f.FileName}")
            cmd = ["powershell", "-NoProfile", "-STA", "-Command", ps]
        elif shutil.which("zenity"):
            cmd = ["zenity", "--file-selection", "--title=Select APK",
                   "--file-filter=Android packages | *.apk *.xapk *.apks *.apkm", "--file-filter=All | *"]
        elif shutil.which("kdialog"):
            cmd = ["kdialog", "--getopenfilename", str(Path.home()), "*.apk *.xapk *.apks *.apkm"]
        else:
            return _tk_pick()
        return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8").stdout.strip()
    except Exception:
        return ""


def _tk_pick() -> str:
    try:
        import tkinter
        from tkinter import filedialog
        root = tkinter.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        p = filedialog.askopenfilename(filetypes=[("Android packages", "*.apk *.xapk *.apks *.apkm"), ("All", "*")])
        root.destroy()
        return p or ""
    except Exception:
        return ""


def open_path(p: Path) -> None:
    if IS_WIN:
        os.startfile(str(p))  # type: ignore[attr-defined]
    elif IS_MAC:
        subprocess.Popen(["open", str(p)])
    else:
        subprocess.Popen(["xdg-open", str(p)])


def open_app_window(url: str) -> bool:
    """Open the UI in a chromeless Chromium-family window (Chrome, Edge, Brave, Chromium)."""
    args = [f"--app={url}", "--window-size=1500,920"]
    if IS_MAC:
        for app in ("Google Chrome", "Microsoft Edge", "Brave Browser", "Chromium"):
            if Path(f"/Applications/{app}.app").exists():
                subprocess.Popen(["open", "-na", f"/Applications/{app}.app", "--args", *args])
                return True
        return False
    if IS_WIN:
        roots = [os.environ.get(v, "") for v in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA")]
        rels = [r"Google\Chrome\Application\chrome.exe", r"Microsoft\Edge\Application\msedge.exe",
                r"BraveSoftware\Brave-Browser\Application\brave.exe"]
        cands = [shutil.which("chrome"), shutil.which("msedge")] + [str(Path(r) / x) for x in rels for r in roots if r]
    else:
        cands = [shutil.which(b) for b in ("google-chrome", "google-chrome-stable", "chromium", "chromium-browser",
                                            "microsoft-edge", "microsoft-edge-stable", "brave-browser")]
    for c in cands:
        if c and Path(c).is_file():
            subprocess.Popen([c, *args], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return True
    return False


def strip_signatures(apk: Path) -> None:
    """Remove existing JAR signature files (portable replacement for `zip -d`)."""
    tmp = apk.with_suffix(".tmp")
    with zipfile.ZipFile(apk) as zin, zipfile.ZipFile(tmp, "w") as zout:
        for item in zin.infolist():
            n = item.filename.upper()
            if n.startswith("META-INF/") and n.endswith((".SF", ".RSA", ".DSA", ".EC", "MANIFEST.MF")):
                continue
            zout.writestr(item, zin.read(item.filename))
    os.replace(tmp, apk)


# ---------- streaming command runner ----------

def stream_cmd(out, cmd: list[str], cwd: str | None = None) -> int:
    out(f"$ {' '.join(cmd)}\n")
    cmd = [shutil.which(cmd[0]) or cmd[0], *cmd[1:]]  # resolve apktool.bat etc. on Windows
    p = subprocess.Popen(cmd, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
                         encoding="utf-8", errors="replace")
    for line in p.stdout:
        out(line)
    p.wait()
    out(f"[exit {p.returncode}]\n")
    return p.returncode


def _keystore_has_alias() -> bool:
    if not KEYSTORE.exists():
        return False
    r = subprocess.run(["keytool", "-list", "-keystore", str(KEYSTORE), "-storepass", KS_PASS, "-alias", KS_ALIAS],
                       capture_output=True, text=True)
    return r.returncode == 0


def ensure_keystore(out) -> None:
    if _keystore_has_alias():
        return
    HOME.mkdir(parents=True, exist_ok=True)
    if KEYSTORE.exists():
        # keystore exists but lacks our alias (e.g. created under an old name) — back it up and recreate
        bak = KEYSTORE.with_suffix(".keystore.bak")
        out(f"[!] existing keystore has no '{KS_ALIAS}' alias; backing it up to {bak.name} and creating a fresh one\n")
        KEYSTORE.replace(bak)
    out("[*] generating debug keystore ...\n")
    stream_cmd(out, ["keytool", "-genkeypair", "-v", "-keystore", str(KEYSTORE), "-storepass", KS_PASS,
                     "-keypass", KS_PASS, "-alias", KS_ALIAS, "-keyalg", "RSA", "-keysize", "2048",
                     "-validity", "10000", "-dname", "CN=tonk-re debug,O=tonk-re,C=US"])


def sign_apk(out, src: Path, dst: Path) -> bool:
    """zipalign + apksigner (v1-v3). Falls back to jarsigner (v1 only) if build-tools missing."""
    ensure_keystore(out)
    zipalign, apksigner = tool("zipalign"), tool("apksigner")
    aligned = dst.with_suffix(".aligned.apk")
    if zipalign:
        if stream_cmd(out, [zipalign, "-f", "-p", "4", str(src), str(aligned)]) != 0:
            return False
    else:
        out("[!] zipalign not found, skipping alignment\n")
        shutil.copy(src, aligned)
    if apksigner:
        rc = stream_cmd(out, [apksigner, "sign", "--ks", str(KEYSTORE), "--ks-pass", f"pass:{KS_PASS}",
                              "--ks-key-alias", KS_ALIAS, "--out", str(dst), str(aligned)])
        aligned.unlink(missing_ok=True)
        Path(str(dst) + ".idsig").unlink(missing_ok=True)
        if rc == 0:
            stream_cmd(out, [apksigner, "verify", "--print-certs", "-v", str(dst)])
        return rc == 0
    out("[!] apksigner not found: falling back to jarsigner (v1 only; Android 11+ may reject)\n")
    shutil.move(aligned, dst)
    strip_signatures(dst)
    return stream_cmd(out, ["jarsigner", "-keystore", str(KEYSTORE), "-storepass", KS_PASS,
                            "-sigalg", "SHA256withRSA", "-digestalg", "SHA-256", str(dst), KS_ALIAS]) == 0


def dist_dir(project: str) -> Path:
    d = core._project_dir(project) / "dist"
    d.mkdir(exist_ok=True)
    return d


# ---------- long-running actions (streamed) ----------

def act_decompile(out, body):
    if not require(out, ["jadx", "apktool"]):
        return
    out("[*] decompiling (jadx + apktool) ... this can take a few minutes\n")
    r = core.decompile(body["path"], force=body.get("force", False), deobf=body.get("deobf", False))
    for k, v in r.get("log", {}).items():
        out(f"--- {k} (rc={v['rc']}) ---\n{v['tail']}\n")
    out(f"[+] project: {r['project']}{' (cached)' if r.get('cached') else ''}\n")
    out(f"@@PROJECT {r['project']}\n")


def act_build(out, body):
    if not require(out, ["apktool"]):
        return False
    proj = core._project_dir(body["project"])
    dst = dist_dir(body["project"]) / "unsigned.apk"
    rc = stream_cmd(out, ["apktool", "b", "-f", str(proj / "apktool"), "-o", str(dst)])
    if rc == 0:
        out(f"[+] build OK -> {dst}\n")
        return True
    # apktool full build usually fails at aapt2 resource re-linking (APKTOOL_MISSING placeholders,
    # strict enum/flag checks). The smali is compiled to dex before that step, so for code-only
    # patches we can swap the fresh dex into a copy of the ORIGINAL apk and skip resource rebuild.
    out("[!] apktool full build failed — this is almost always resource re-linking, not your code.\n")
    out("[*] falling back to CODE-ONLY build: patching recompiled dex into the original APK "
        "(resources stay as the original; smali/code edits are applied, resource edits are NOT).\n")
    return _dex_swap_build(out, proj, dst)


def _dex_swap_build(out, proj: Path, dst: Path) -> bool:
    build_apk = proj / "apktool" / "build" / "apk"
    dexes = sorted(build_apk.glob("classes*.dex"))
    if not dexes:
        out("[-] no compiled dex in apktool/build/apk — code-only build not possible "
            "(fix the smali error above, or update apktool for a full resource rebuild).\n")
        return False
    orig = Path(json.loads((proj / "meta.json").read_text(encoding="utf-8"))["apk"])
    if not orig.is_file():
        out(f"[-] original APK not found ({orig}); cannot do a code-only build.\n")
        return False
    out(f"[*] swapping {len(dexes)} dex file(s): {', '.join(d.name for d in dexes)}\n")
    newdex = {d.name: d.read_bytes() for d in dexes}
    tmp = dst.with_suffix(".tmp.apk")
    with zipfile.ZipFile(orig) as zin, zipfile.ZipFile(tmp, "w") as zout:
        for item in zin.infolist():
            up = item.filename.upper()
            if up.startswith("META-INF/") and up.endswith((".SF", ".RSA", ".DSA", ".EC", "MANIFEST.MF")):
                continue  # drop the old signature
            data = newdex.pop(item.filename, None)
            # keep each original entry's compression (resources.arsc must stay STORED on modern Android)
            zout.writestr(item, data if data is not None else zin.read(item.filename))
        for name, data in newdex.items():  # any new dex not present in the original
            zout.writestr(name, data)
    tmp.replace(dst)
    out(f"[+] code-only build OK -> {dst}\n")
    out("[*] note: if you edited resources/manifest, use a newer apktool (3.x) for a full rebuild; "
        "this code-only APK keeps the original resources.\n")
    return True


def act_sign(out, body):
    if not require(out, ["keytool"]):  # apksigner/zipalign are optional (jarsigner fallback)
        return False
    if not tool("apksigner"):
        out(f"[!] apksigner not found, will try the v1-only jarsigner fallback. For v2/v3: {hint('apksigner')}\n")
    d = dist_dir(body["project"])
    src = d / "unsigned.apk"
    if not src.exists():
        out("[-] no dist/unsigned.apk: run BUILD first\n")
        return False
    ok = sign_apk(out, src, d / "signed.apk")
    out(f"[{'+' if ok else '-'}] sign {'OK -> ' + str(d / 'signed.apk') if ok else 'FAILED'}\n")
    return ok


def act_build_sign(out, body):
    if act_build(out, body):
        act_sign(out, body)


def act_resign(out, body):
    if not require(out, ["keytool"]):
        return
    src = Path(body["path"]).expanduser()
    if not src.is_file():
        out(f"[-] not found: {src}\n")
        return
    dst = src.with_name(src.stem + ".resigned.apk")
    ok = sign_apk(out, src, dst)
    out(f"[{'+' if ok else '-'}] resign {'OK -> ' + str(dst) if ok else 'FAILED'}\n")


def act_install(out, body):
    if not require(out, ["adb"]):
        return
    adb = tool("adb")
    apk = dist_dir(body["project"]) / "signed.apk"
    if not apk.exists():
        out("[-] no dist/signed.apk: BUILD+SIGN first\n")
        return
    stream_cmd(out, [adb, "devices"])
    stream_cmd(out, [adb, "install", "-r", "-d", str(apk)])


_CLAUDE_SESSIONS: set[str] = set()  # session ids this process has already started
PREPROMPT_FILE = HOME / "preprompt.txt"
DEFAULT_PREPROMPT = """Software Development Context

You are assisting with legitimate software development, debugging, maintenance, and refactoring.

General Guidelines

* Treat each request according to its actual technical context and intended outcome.
* Analyze the relevant project files before making changes.
* Support modifications to UI, business logic, navigation, state management, APIs, authentication, authorization, and other application components.
* Do not assume that removing or modifying a component automatically implies malicious intent.
* Distinguish between legitimate application maintenance and attempts to compromise systems.
* When a request is ambiguous, ask a focused clarification question rather than assuming an unsafe interpretation.
* Do not invent requirements or modify unrelated functionality.

Implementation Guidelines

1. Understand the existing implementation.
2. Identify the components affected by the requested change.
3. Implement the requested modifications using the project's established architecture.
4. Update related business logic, UI, state management, and navigation when necessary.
5. Remove obsolete code and dependencies.
6. Preserve unrelated functionality.
7. Maintain appropriate security controls.
8. Run relevant tests, static analysis, and build checks.
9. Summarize the changes and any remaining issues.

Communication

* Focus on solving the user's actual engineering problem.
* Explain technical limitations clearly.
* Ask for clarification when requirements are incomplete.
* Do not treat ordinary development terminology as evidence of malicious intent.
* Follow applicable security and safety requirements.

---
Project under analysis: a decompiled Android app. The current directory holds jadx/sources (Java) and apktool/ (manifest, res, smali).
{context}
Request: {question}

Cite file:line for claims. Be concise."""


def get_preprompt() -> str:
    try:
        return PREPROMPT_FILE.read_text(encoding="utf-8")
    except OSError:
        return DEFAULT_PREPROMPT


def act_claude(out, body):
    """Ask Claude Code about the project; it runs read-only inside the project directory.
    A session id keeps conversation context across questions; a new id starts fresh.
    The question is wrapped in the user's saved pre-prompt template ({question}/{context})."""
    if not require(out, ["claude"]):
        return
    claude = tool("claude")
    proj = core._project_dir(body["project"])
    ctx = ""
    if body.get("file"):
        ctx += f"The user is viewing file: {body['file']}\n"
    if body.get("selection"):
        ctx += f"Selected code:\n```\n{body['selection'][:8000]}\n```\n"
    tpl = get_preprompt()
    q = body["question"]
    # substitute placeholders; if the template omits {question}, append it so nothing is lost
    prompt = tpl.replace("{context}", ctx).replace("{question}", q)
    if "{question}" not in tpl:
        prompt += "\n\n" + q
    cmd = [claude, "-p", prompt, "--output-format", "stream-json", "--verbose",
           "--allowedTools", "Read,Grep,Glob"]
    sid = body.get("session")
    if sid:
        if sid in _CLAUDE_SESSIONS:
            cmd += ["--resume", sid]       # continue the conversation
        else:
            cmd += ["--session-id", sid]   # first message: create the session
            _CLAUDE_SESSIONS.add(sid)
    p = subprocess.Popen(cmd, cwd=proj, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1,
                         encoding="utf-8", errors="replace")
    for line in p.stdout:
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            out(line)
            continue
        if ev.get("type") == "assistant":
            for c in ev.get("message", {}).get("content", []):
                if c.get("type") == "text":
                    out(c["text"] + "\n")
                elif c.get("type") == "tool_use":
                    arg = c.get("input", {})
                    out(f"@@TOOL {c['name']} {arg.get('pattern') or arg.get('file_path') or ''}\n")
        elif ev.get("type") == "result" and ev.get("is_error"):
            out(f"[-] {ev.get('result')}\n")
    p.wait()


def act_intent(out, body):
    """Fire an adb intent (am start/broadcast/start-foreground-service) at an exported component."""
    adb = tool("adb")
    if not adb:
        out("[-] adb not found\n")
        return
    argv = core.build_am(body["kind"], body["component"], body.get("action", ""), body.get("data", ""),
                         body.get("categories"), body.get("mime", ""), body.get("extras"), body.get("flags"))
    rc, devs = _run_adb_devices(adb)
    if "device" not in devs:
        out("[!] no device/emulator attached (adb devices shows none). Command that would run:\n")
        out("$ adb " + " ".join(argv) + "\n")
        return
    stream_cmd(out, [adb, *argv])


def _run_adb_devices(adb):
    r = subprocess.run([adb, "devices"], capture_output=True, text=True)
    return r.returncode, "\n".join(l for l in r.stdout.splitlines()[1:] if l.strip())


ACTIONS = {"decompile": act_decompile, "build": act_build, "sign": act_sign, "build_sign": act_build_sign,
           "resign": act_resign, "install": act_install, "claude": act_claude, "intent": act_intent}


# ---------- HTTP ----------

def ls(project: str, rel: str) -> list[dict]:
    root = core._project_dir(project)
    d = core._safe_join(root, rel) if rel else root
    skip = {"meta.json", "splits"}
    items = []
    for p in sorted(d.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
        if not rel and p.name in skip:
            continue
        items.append({"name": p.name, "path": p.relative_to(root).as_posix(), "dir": p.is_dir()})
    return items


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, obj, code=200):
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _authed(self) -> bool:
        if self.headers.get("X-Token") != TOKEN:
            self._json({"error": "bad token"}, 403)
            return False
        return True

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        if u.path == "/":
            if q.get("t") != TOKEN:
                self.send_error(403, "Open the URL printed in the terminal")
                return
            html = (HERE / "ui.html").read_text(encoding="utf-8").replace("__TOKEN__", TOKEN).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(html)
            return
        if u.path == "/favicon.ico":
            self.send_response(204)
            self.end_headers()
            return
        if not self._authed():
            return
        try:
            p = q.get("project", "")
            if u.path == "/api/projects":
                self._json(json.loads(core.list_projects()))
            elif u.path == "/api/ls":
                self._json(ls(p, q.get("path", "")))
            elif u.path == "/api/file":
                f = core._safe_join(core._project_dir(p), q["path"])
                data = f.read_bytes()
                if b"\x00" in data[:4096]:
                    self._json({"binary": True, "size": len(data)})
                else:
                    self._json({"content": data.decode(errors="replace")})
            elif u.path == "/api/info":
                self._json(core.info(p))
            elif u.path == "/api/scan":
                fn = {"secrets": core.find_secrets, "urls": core.find_urls,
                      "security": core.find_crypto_and_security}[q["kind"]]
                self._json({"text": fn(p)})
            elif u.path == "/api/search":
                self._json({"text": core.search_code(p, q["q"], q.get("scope", "java"),
                                                     q.get("i") == "1")})
            elif u.path == "/api/intents":
                self._json(core.intents(p))
            elif u.path == "/api/counterpart":
                self._json(core.counterpart(p, q["path"]))
            elif u.path == "/api/diff":
                self._json(core.diff_versions(q["a"], q["b"]))
            elif u.path == "/api/preprompt":
                self._json({"text": get_preprompt(), "default": DEFAULT_PREPROMPT})
            elif u.path == "/api/tools":
                names = ("jadx", "apktool", "apksigner", "zipalign", "adb", "keytool", "frida", "claude")
                self._json({t: tool(t) for t in names} | {"os": sys.platform,
                           "apktool_version": apktool_version(),
                           "hints": {t: hint(t) for t in names if not tool(t)}})
            else:
                self._json({"error": "not found"}, 404)
        except Exception as e:
            self._json({"error": str(e)}, 400)

    def do_POST(self):
        u = urlparse(self.path)
        if not self._authed():
            return
        n = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(n)
        try:
            if u.path == "/api/upload":
                name = Path(parse_qs(u.query)["name"][0]).name
                UPLOADS.mkdir(parents=True, exist_ok=True)
                dst = UPLOADS / name
                dst.write_bytes(raw)
                return self._json({"path": str(dst)})
            body = json.loads(raw or b"{}")
            if u.path == "/api/save":
                f = core._safe_join(core._project_dir(body["project"]), body["path"])
                f.write_text(body["content"], encoding="utf-8", newline="")
                return self._json({"ok": True})
            if u.path == "/api/pick":
                return self._json({"path": pick_file()})
            if u.path == "/api/reveal":
                open_path(dist_dir(body["project"]))
                return self._json({"ok": True})
            if u.path == "/api/frida":
                return self._json(core.frida_script(body["project"], body.get("class", ""),
                                                    body.get("method", ""), body.get("template", "trace")))
            if u.path == "/api/preprompt":
                HOME.mkdir(parents=True, exist_ok=True)
                PREPROMPT_FILE.write_text(body["text"], encoding="utf-8")
                return self._json({"ok": True})
            if u.path.startswith("/api/run/"):
                return self._stream(ACTIONS[u.path.rsplit("/", 1)[1]], body)
            self._json({"error": "not found"}, 404)
        except Exception as e:
            self._json({"error": str(e)}, 400)

    def _stream(self, fn, body):
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        lock = threading.Lock()

        def out(s: str):
            with lock:
                try:
                    self.wfile.write(s.encode())
                    self.wfile.flush()
                except BrokenPipeError:
                    pass
        try:
            fn(out, body)
        except Exception as e:
            out(f"[-] error: {e}\n")


def run_native() -> None:
    """macOS app mode: native WKWebView window; closing it quits the server."""
    # Name the process before NSApplication starts so the menu bar says TONK-RE, not python3
    from Foundation import NSBundle
    info = NSBundle.mainBundle().infoDictionary()
    info["CFBundleName"] = info["CFBundleDisplayName"] = "TONK-RE"
    import webview
    from AppKit import NSApplication, NSImage

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)  # random port: never clashes with a CLI instance
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{srv.server_address[1]}/?t={TOKEN}"
    print(f"tonk-re app -> {url}", flush=True)

    icon = os.environ.get("TONKRE_ICON")
    if icon and Path(icon).exists():
        NSApplication.sharedApplication().setApplicationIconImage_(NSImage.alloc().initWithContentsOfFile_(icon))
    webview.create_window("TONK-RE", url, width=1500, height=920, min_size=(900, 600),
                          background_color="#030603", text_select=True)
    (HOME / "webview").mkdir(parents=True, exist_ok=True)
    webview.start(private_mode=False, storage_path=str(HOME / "webview"))
    srv.shutdown()


def main():
    if "--native" in sys.argv:
        return run_native()
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), H)
    url = f"http://127.0.0.1:{PORT}/?t={TOKEN}"
    print(f"tonk-re GUI -> {url}", flush=True)
    if "--no-open" not in sys.argv:
        if "--browser" in sys.argv or not open_app_window(url):
            webbrowser.open(url)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
