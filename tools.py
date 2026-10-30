"""tonk-re toolchain manager: one-click, per-user installs of the external tools TONK-RE drives.

Everything lands in ~/.tonkre/tools (no admin rights, no package manager, nothing outside that folder;
uninstall = delete it). activate() prepends the managed dirs to this process's PATH, which every
subprocess inherits, so the rest of the code keeps using plain shutil.which(). Tools the user already
has on PATH or in an Android SDK are detected and left alone.

Every download is checksum-verified (Adoptium sha256, GitHub release sha256, Google repo sha1) before
it is unpacked, and unpacked into a temp dir that only replaces the old install once complete.
"""
from __future__ import annotations

import glob
import hashlib
import json
import os
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import threading
import urllib.request
import zipfile
from pathlib import Path

import defusedxml.ElementTree as ET

IS_WIN, IS_MAC = sys.platform == "win32", sys.platform == "darwin"
HOME = Path(os.environ.get("TONKRE_HOME", Path.home() / ".tonkre"))
TOOLS = HOME / "tools"
JDK, JADX, APKTOOL, SDK, BIN = (TOOLS / d for d in ("jdk", "jadx", "apktool", "android-sdk", "bin"))
EXTS = [".bat", ".exe", ".cmd", ""] if IS_WIN else [""]

ANDROID_REPO = "https://dl.google.com/android/repository/"
ANDROID_LICENSE_URL = "https://developer.android.com/studio/terms"
UA = {"User-Agent": "tonk-re-setup"}

# id -> label, what it provides, whether TONK-RE needs it, and whether Google's SDK license applies
COMPONENTS = {
    "jdk": {"label": "JDK 21 (Temurin)", "provides": ["java", "keytool"], "required": True,
            "desc": "runs jadx/apktool/apksigner; keytool signs"},
    "jadx": {"label": "jadx", "provides": ["jadx"], "required": True, "desc": "Java/Kotlin decompiler"},
    "apktool": {"label": "apktool 3.x", "provides": ["apktool"], "required": True,
                "desc": "manifest, resources, smali; rebuild"},
    "build-tools": {"label": "Android build-tools", "provides": ["apksigner", "zipalign"], "required": True,
                    "desc": "apksigner + zipalign (v2/v3 signing)", "license": True},
    "platform-tools": {"label": "Android platform-tools", "provides": ["adb"], "required": False,
                       "desc": "adb: INSTALL to device, intents", "license": True},
    "frida": {"label": "frida-tools", "provides": ["frida"], "required": False,
              "desc": "only to RUN generated hooks"},
}
_lock = threading.Lock()


# ---------- discovery ----------

def system_sdk() -> Path:
    for var in ("ANDROID_HOME", "ANDROID_SDK_ROOT"):
        if os.environ.get(var):
            return Path(os.environ[var])
    if IS_WIN:
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "Android" / "Sdk"
    if IS_MAC:
        return Path.home() / "Library" / "Android" / "sdk"
    return Path.home() / "Android" / "Sdk"


def _which_in(dirs: list[Path], name: str) -> str | None:
    for d in dirs:
        for ext in EXTS:
            if (d / (name + ext)).is_file():
                return str(d / (name + ext))
    return None


def _ver_key(p: Path) -> list[int]:
    return [int(x) if x.isdigit() else 0 for x in re.split(r"[.\-]", p.name)]


def build_tool(name: str) -> str | None:
    """apksigner / zipalign: PATH first, then the newest build-tools in the user's SDK or ours."""
    if shutil.which(name):
        return shutil.which(name)
    dirs = [Path(p) for sdk in (system_sdk(), SDK) for p in glob.glob(str(sdk / "build-tools" / "*"))]
    return _which_in(sorted(dirs, key=_ver_key, reverse=True), name)


def find(name: str) -> str | None:
    if name in ("apksigner", "zipalign"):
        return build_tool(name)
    if name == "adb":
        return shutil.which("adb") or _which_in([system_sdk() / "platform-tools", SDK / "platform-tools"], "adb")
    return shutil.which(name)


def _jdk_home() -> Path | None:
    for home in (JDK, JDK / "Contents" / "Home"):  # macOS tarballs nest the JDK in a bundle
        if _which_in([home / "bin"], "java"):
            return home
    return None


def _uv_tool_bin() -> Path:
    for var in ("UV_TOOL_BIN_DIR", "XDG_BIN_HOME"):
        if os.environ.get(var):
            return Path(os.environ[var])
    return Path.home() / ".local" / "bin"


def activate() -> None:
    """Put managed tools on this process's PATH (inherited by every subprocess). Idempotent."""
    jdk = _jdk_home()
    if jdk and not (os.environ.get("JAVA_HOME") and _which_in([Path(os.environ["JAVA_HOME"]) / "bin"], "java")):
        os.environ["JAVA_HOME"] = str(jdk)  # jadx.bat / apksigner.bat prefer JAVA_HOME over PATH
    front = [BIN, JADX / "bin", SDK / "platform-tools"] + ([jdk / "bin"] if jdk else [])
    parts = os.environ.get("PATH", "").split(os.pathsep)
    new = [str(d) for d in front if d.is_dir() and str(d) not in parts]
    tail = [] if str(_uv_tool_bin()) in parts else [str(_uv_tool_bin())]  # where `uv tool install` puts frida
    os.environ["PATH"] = os.pathsep.join(new + parts + tail)


def _managed(path: str | None) -> bool:
    try:
        return bool(path) and TOOLS.resolve() in Path(path).resolve().parents
    except OSError:
        return False


def status() -> list[dict]:
    rows = []
    for cid, c in COMPONENTS.items():
        paths = {p: find(p) for p in c["provides"]}
        first = next(iter(paths.values()))
        rows.append({"id": cid, "label": c["label"], "desc": c["desc"], "required": c["required"],
                     "license": bool(c.get("license")), "installed": all(paths.values()),
                     "missing": [p for p, v in paths.items() if not v], "path": first, "managed": _managed(first)})
    return rows


# ---------- download / unpack ----------

def _get(url: str) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
        return r.read()


def _download(out, url: str, dest: Path, algo: str | None, digest: str | None) -> Path:
    """Stream url to dest, printing progress, and verify its checksum. Raises on mismatch."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    h = hashlib.new(algo) if algo else None
    out(f"[*] downloading {url}\n")
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r, part.open("wb") as f:
        total, done, shown = int(r.headers.get("Content-Length") or 0), 0, -1
        while chunk := r.read(1 << 20):
            f.write(chunk)
            h and h.update(chunk)
            done += len(chunk)
            pct = done * 100 // total if total else -1
            if total and pct // 10 > shown:
                shown = pct // 10
                out(f"    {pct:3d}%  {done >> 20} / {total >> 20} MB\n")
    if h:
        if h.hexdigest().lower() != digest.lower():
            part.unlink(missing_ok=True)
            raise ValueError(f"{algo} mismatch for {dest.name}: expected {digest}, got {h.hexdigest()}")
        out(f"[+] {algo} verified\n")
    else:
        out("[!] no published checksum for this file; relying on HTTPS\n")
    os.replace(part, dest)
    return dest


def _extract(out, archive: Path, dest: Path) -> None:
    """Unpack into a temp dir, collapse a single top-level folder, then swap it in for dest."""
    tmp = dest.with_name(dest.name + ".tmp")
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    out(f"[*] unpacking {archive.name}\n")
    if archive.name.endswith(".zip"):
        with zipfile.ZipFile(archive) as z:
            for info in z.infolist():
                p = Path(z.extract(info, tmp))  # extract() sanitises ../ and absolute paths
                mode = info.external_attr >> 16
                if not IS_WIN and mode & 0o111 and p.is_file():
                    p.chmod(mode & 0o777)  # zipfile drops exec bits (adb, apksigner, jadx launcher)
    else:
        with tarfile.open(archive) as t:
            if hasattr(tarfile, "data_filter"):
                t.extractall(tmp, filter="data")
            else:
                root = tmp.resolve()
                for m in t.getmembers():
                    if root not in (root / m.name).resolve().parents:
                        raise ValueError(f"unsafe path in archive: {m.name}")
                t.extractall(tmp)
    kids = list(tmp.iterdir())
    src = kids[0] if len(kids) == 1 and kids[0].is_dir() else tmp
    shutil.rmtree(dest, ignore_errors=True)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dest))
    shutil.rmtree(tmp, ignore_errors=True)
    archive.unlink(missing_ok=True)


def _arch() -> str:
    m = platform.machine().lower()
    return "aarch64" if m in ("arm64", "aarch64") else "x64"


def _github_asset(repo: str, pattern: str) -> tuple[str, str, str | None]:
    """(name, url, sha256-or-None) of the newest release asset matching pattern."""
    rel = json.loads(_get(f"https://api.github.com/repos/{repo}/releases/latest"))
    for a in rel["assets"]:
        if re.fullmatch(pattern, a["name"]):
            d = a.get("digest") or ""
            return a["name"], a["browser_download_url"], d.split(":", 1)[1] if d.startswith("sha256:") else None
    raise ValueError(f"no release asset matching {pattern} in {repo} {rel.get('tag_name')}")


# ---------- installers ----------

def _install_jdk(out) -> None:
    os_ = "windows" if IS_WIN else "mac" if IS_MAC else "linux"
    api = f"https://api.adoptium.net/v3/assets/latest/21/hotspot?os={os_}&architecture={_arch()}&image_type=jdk"
    pkg = json.loads(_get(api))[0]["binary"]["package"]
    _extract(out, _download(out, pkg["link"], TOOLS / pkg["name"], "sha256", pkg["checksum"]), JDK)


def _install_jadx(out) -> None:
    name, url, sha = _github_asset("skylot/jadx", r"jadx-[\d.]+\.zip")
    _extract(out, _download(out, url, TOOLS / name, sha and "sha256", sha), JADX)


def _install_apktool(out) -> None:
    name, url, sha = _github_asset("iBotPeaches/Apktool", r"apktool_[\d.]+\.jar")
    _download(out, url, APKTOOL / "apktool.jar", sha and "sha256", sha)
    BIN.mkdir(parents=True, exist_ok=True)
    if IS_WIN:
        (BIN / "apktool.cmd").write_text('@java -jar "%~dp0..\\apktool\\apktool.jar" %*\r\n', encoding="ascii")
    else:
        sh = BIN / "apktool"
        sh.write_text('#!/bin/sh\nexec java -jar "$(dirname "$0")/../apktool/apktool.jar" "$@"\n', encoding="ascii")
        sh.chmod(0o755)
    out(f"[+] {name}\n")


_repo_cache: dict = {}


def _android_repo():
    if "root" not in _repo_cache:
        _repo_cache["root"] = ET.fromstring(_get(ANDROID_REPO + "repository2-3.xml"))
    return _repo_cache["root"]


def _local(el) -> str:
    return el.tag.rsplit("}", 1)[-1]


def _child(el, name):
    return next((c for c in el if _local(c) == name), None)


def android_license() -> str:
    for el in _android_repo():
        if _local(el) == "license" and el.get("id") == "android-sdk-license":
            return (el.text or "").strip()
    return f"See {ANDROID_LICENSE_URL}"


def _android_pkg(prefix: str) -> tuple[str, str, str]:
    """(version, url, sha1) of the newest stable package whose path starts with prefix, for this OS."""
    host = "windows" if IS_WIN else "macosx" if IS_MAC else "linux"
    best = None
    for p in _android_repo():
        path = p.get("path") or ""
        if _local(p) != "remotePackage" or not path.startswith(prefix) or "-rc" in path:
            continue
        ch = _child(p, "channelRef")
        if ch is not None and ch.get("ref") != "channel-0":
            continue
        rev = _child(p, "revision")
        ver = ".".join((_child(rev, k).text or "0") if _child(rev, k) is not None else "0"
                       for k in ("major", "minor", "micro"))
        arcs = _child(p, "archives")
        for a in (arcs if arcs is not None else []):
            ho, ha = _child(a, "host-os"), _child(a, "host-arch")
            if ho is not None and ho.text != host:
                continue
            # exact arch preferred; x64 is still usable on Apple Silicon via Rosetta
            native = ha is None or ha.text == _arch()
            if not native and not (IS_MAC and ha.text == "x64"):
                continue
            comp = _child(a, "complete")
            url, sha1 = _child(comp, "url").text, _child(comp, "checksum").text
            key = [int(x) for x in ver.split(".")] + [native]
            if best is None or key > best[0]:
                best = (key, ver, url, sha1)
    if not best:
        raise ValueError(f"no stable Android package {prefix}* for {host}")
    return best[1], ANDROID_REPO + best[2], best[3]


def _install_build_tools(out) -> None:
    ver, url, sha1 = _android_pkg("build-tools;")
    _extract(out, _download(out, url, TOOLS / url.rsplit("/", 1)[1], "sha1", sha1), SDK / "build-tools" / ver)


def _install_platform_tools(out) -> None:
    _, url, sha1 = _android_pkg("platform-tools")
    _extract(out, _download(out, url, TOOLS / url.rsplit("/", 1)[1], "sha1", sha1), SDK / "platform-tools")


def _install_frida(out) -> None:
    uv = shutil.which("uv")
    if not uv:
        raise ValueError("uv not found on PATH (needed to install frida-tools)")
    out(f"$ {uv} tool install --upgrade frida-tools\n")
    p = subprocess.Popen([uv, "tool", "install", "--upgrade", "frida-tools"], stdout=subprocess.PIPE,
                         stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace")
    for line in p.stdout:
        out(line)
    if p.wait():
        raise ValueError(f"uv tool install exited {p.returncode}")


INSTALLERS = {"jdk": _install_jdk, "jadx": _install_jadx, "apktool": _install_apktool,
              "build-tools": _install_build_tools, "platform-tools": _install_platform_tools,
              "frida": _install_frida}


def install(out, ids: list[str], accept_license: bool = False) -> bool:
    """Install components. ids may contain 'all' (= everything missing). Returns True if all succeeded."""
    if not _lock.acquire(blocking=False):
        out("[!] a setup job is already running\n")
        return False
    try:
        st = {r["id"]: r for r in status()}
        want = [c for c in COMPONENTS if not st[c]["installed"]] if "all" in ids else list(dict.fromkeys(ids))
        unknown = [c for c in want if c not in COMPONENTS]
        if unknown:
            out(f"[-] unknown component(s): {', '.join(unknown)}  (choose from: {', '.join(COMPONENTS)})\n")
            return False
        if any(c in want for c in ("jadx", "apktool")) and not st["jdk"]["installed"] and "jdk" not in want:
            want.insert(0, "jdk")  # both are Java programs
        if not want:
            out("[+] everything is already installed\n")
            return True
        ok = True
        for cid in want:
            if COMPONENTS[cid].get("license") and not accept_license:
                out(f"[-] {cid}: skipped, the Android SDK License must be accepted first ({ANDROID_LICENSE_URL})\n")
                ok = False
                continue
            out(f"\n== {COMPONENTS[cid]['label']}\n")
            try:
                INSTALLERS[cid](out)
                activate()
                missing = [p for p in COMPONENTS[cid]["provides"] if not find(p)]
                if missing:
                    raise ValueError(f"installed, but {', '.join(missing)} still not found")
                out(f"[+] {cid} ready: {find(COMPONENTS[cid]['provides'][0])}\n")
            except Exception as e:
                ok = False
                out(f"[-] {cid} failed: {e}\n")
        out(f"\n{'[+] setup complete' if ok else '[!] setup finished with errors (see above)'}. "
            f"Tools live in {TOOLS}\n")
        return ok
    finally:
        _lock.release()


def cli(argv: list[str]) -> None:
    """tonkre setup [status | all | COMPONENT...] [--accept-android-license]"""
    activate()
    accept = "--accept-android-license" in argv
    ids = [a for a in argv if not a.startswith("--")]
    if not ids or ids == ["status"]:
        for r in status():
            tag = "[ OK ]" if r["installed"] else "[MISS]"
            kind = "required" if r["required"] else "optional"
            print(f"{tag} {r['id']:<15} {kind:<9} {r['path'] or r['desc']}{'  (managed)' if r['managed'] else ''}")
        print("\ninstall:  tonkre setup all --accept-android-license   (or name components)")
        return
    if not accept and any(COMPONENTS.get(i, {}).get("license") or i == "all" for i in ids):
        print(f"[!] build-tools / platform-tools are covered by the Android SDK License: {ANDROID_LICENSE_URL}\n"
              "    pass --accept-android-license to accept it and install them.")
    sys.exit(0 if install(lambda s: print(s, end="", flush=True), ids, accept) else 1)
