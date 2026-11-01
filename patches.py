"""Static patch engine: manifest + smali rewrites applied to a decompiled apktool tree.

Patch families (all land as on-disk edits the user then rebuilds with BUILD+SIGN):

  * make_interceptable()   -- Burp/mitmproxy prep: debuggable + a network_security_config
    that trusts user CAs + cleartext allowed.
  * patch_method_return()  -- force a method to return true / false / 0 / null, or no-op a
    void method. Static counterpart to a Frida return hook (root/premium/license gates).
  * neutralize_calls()     -- delete call sites (invoke-*) to a given method inside a class;
    if the result was consumed (move-result*) it is replaced with 0/null so the verifier is
    happy. Good for ripping out an integrity/analytics/kill-switch call.

Every patch snapshots the files it touches into <project>/.tonkre_backups first, so revert()
can restore the pristine decompiled tree in one call (and delete any files a patch created).

The engine is pure w.r.t. tonk-re's other modules: callers pass the project dir and the
resolved smali files, so it stays unit-testable with no import cycle. Edits to the manifest/
resources need a FULL apktool rebuild — the code-only dex-swap fallback keeps the original
resources, so it will NOT include a MITM patch. Smali-only patches work with either build path.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

NSC_XML = """<?xml version="1.0" encoding="utf-8"?>
<!-- Added by tonk-re "make interceptable": trust user-installed CAs (Burp / mitmproxy). -->
<network-security-config>
    <base-config cleartextTrafficPermitted="true">
        <trust-anchors>
            <certificates src="system" />
            <certificates src="user" />
        </trust-anchors>
    </base-config>
</network-security-config>
"""

GUIDED_ACTIONS = ("force_true", "force_false", "return_zero", "return_null", "noop")

# return descriptor from a .method signature, e.g. "...isRooted()Z" -> "Z", "...get()Ljava/lang/String;" -> "L..;"
_RET_RE = re.compile(r"\([^)]*\)(\[*(?:[VZBSCIJFD]|L[^;]+;))\s*$")

_BAK_DIR = ".tonkre_backups"
_MANIFEST = "manifest.json"


# ---------- backup / revert (undo) ----------

def _bak_root(proj: Path) -> Path:
    return proj / _BAK_DIR


def _load(proj: Path) -> dict:
    f = _bak_root(proj) / _MANIFEST
    if f.is_file():
        try:
            return json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {"backed_up": [], "created": []}


def _save(proj: Path, m: dict) -> None:
    root = _bak_root(proj)
    root.mkdir(parents=True, exist_ok=True)
    (root / _MANIFEST).write_text(json.dumps(m, indent=2), encoding="utf-8")


def _snapshot(proj: Path, modified: list[Path], created: list[Path]) -> None:
    """Copy soon-to-be-modified files into the backup tree (once, keeping the earliest pristine
    copy) and record newly-created files so revert() can delete them."""
    m = _load(proj)
    bak = _bak_root(proj)
    for f in modified:
        f = Path(f)
        if not f.is_file():
            continue
        rel = f.relative_to(proj).as_posix()
        if rel in m["backed_up"] or rel in m["created"]:
            continue  # already have a pristine copy from an earlier patch
        dest = bak / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(f.read_bytes())
        m["backed_up"].append(rel)
    for f in created:
        rel = Path(f).relative_to(proj).as_posix()
        if rel not in m["created"] and rel not in m["backed_up"]:
            m["created"].append(rel)
    _save(proj, m)


def has_backups(proj: Path) -> bool:
    m = _load(proj)
    return bool(m["backed_up"] or m["created"])


def revert(proj: Path) -> dict:
    """Restore every file a patch modified and delete every file a patch created, returning the
    tree to its freshly-decompiled state. Clears the backup store."""
    proj = Path(proj)
    m = _load(proj)
    bak = _bak_root(proj)
    restored, deleted = [], []
    for rel in m["backed_up"]:
        src = bak / rel
        if src.is_file():
            (proj / rel).parent.mkdir(parents=True, exist_ok=True)
            (proj / rel).write_bytes(src.read_bytes())
            restored.append(rel)
    for rel in m["created"]:
        target = proj / rel
        if target.is_file():
            target.unlink()
            deleted.append(rel)
    # clear the store
    for p in sorted(bak.rglob("*"), reverse=True):
        p.unlink() if p.is_file() else p.rmdir()
    if bak.exists():
        bak.rmdir()
    return {"op": "revert", "restored": restored, "deleted": deleted,
            "count": len(restored) + len(deleted),
            "next": "BUILD+SIGN to produce an un-patched APK again." if (restored or deleted)
                    else "nothing to revert (no tonk-re patches recorded for this project)."}


# ---------- manifest: make interceptable (MITM) ----------

def _upsert_attr(tag_attrs: str, attr: str, value: str) -> str:
    """Set android:<attr>="value" inside an opening-tag attribute string (replace or append)."""
    pat = re.compile(rf'\s{re.escape(attr)}="[^"]*"')
    repl = f' {attr}="{value}"'
    return pat.sub(repl, tag_attrs) if pat.search(tag_attrs) else tag_attrs + repl


def make_interceptable(proj: Path) -> dict:
    """Edit the manifest + add a network-security-config so the app trusts user CA certs.
    `proj` is the project dir (apktool output is proj/apktool). Needs a full apktool rebuild."""
    proj = Path(proj)
    apk = proj / "apktool"
    manifest = apk / "AndroidManifest.xml"
    if not manifest.is_file():
        raise ValueError("AndroidManifest.xml not found (decode with apktool first)")
    nsc = apk / "res" / "xml" / "network_security_config.xml"
    _snapshot(proj, [manifest], [] if nsc.exists() else [nsc])

    text = manifest.read_text(encoding="utf-8", errors="ignore")
    m = re.search(r"(<application\b)(.*?)(/?>)", text, re.DOTALL)
    if not m:
        raise ValueError("no <application> element in the manifest")
    head, attrs, close = m.groups()
    changes, before = [], attrs
    existing = re.search(r'networkSecurityConfig="([^"]*)"', attrs)
    attrs = _upsert_attr(attrs, "android:debuggable", "true")
    attrs = _upsert_attr(attrs, "android:usesCleartextTraffic", "true")
    attrs = _upsert_attr(attrs, "android:networkSecurityConfig", "@xml/network_security_config")
    if attrs != before:
        text = text[:m.start()] + head + attrs + close + text[m.end():]
        manifest.write_text(text, encoding="utf-8", newline="")
        changes = ["android:debuggable=true", "android:usesCleartextTraffic=true",
                   "android:networkSecurityConfig=@xml/network_security_config"]
        if existing and existing.group(1) != "@xml/network_security_config":
            changes.append(f"replaced existing networkSecurityConfig ({existing.group(1)})")

    nsc.parent.mkdir(parents=True, exist_ok=True)
    nsc.write_text(NSC_XML, encoding="utf-8", newline="")
    return {
        "op": "make_interceptable",
        "changes": changes,
        "files_written": ["AndroidManifest.xml", "res/xml/network_security_config.xml"],
        "requires_full_build": True,
        "revertable": True,
        "next": "BUILD+SIGN with apktool 3.x (the code-only build keeps the ORIGINAL manifest/resources, "
                "so it will NOT include this patch), install, then point your device proxy at Burp/mitmproxy.",
    }


# ---------- smali: guided method-return patches ----------

def _return_body(ret: str, value) -> tuple[int, list[str]]:
    """(.locals count, body instruction lines) for forcing a method's return value."""
    if ret == "V":
        return 0, ["return-void"]
    if ret == "J":  # long (wide)
        n = int(value) if str(value).lstrip("-").isdigit() else 0
        return 2, [f"const-wide v0, {hex(n & 0xFFFFFFFFFFFFFFFF)}", "return-wide v0"]
    if ret == "D":  # double
        return 2, ["const-wide v0, 0x0", "return-wide v0"]
    if ret == "F":  # float
        return 1, ["const v0, 0x0", "return v0"]
    if ret.startswith("L") or ret.startswith("["):  # object / array -> null only
        return 1, ["const/4 v0, 0x0", "return-object v0"]
    # int family: Z B S C I
    if str(value).lower() in ("true", "1"):
        n = 1
    elif str(value).lower() in ("false", "0", "null", ""):
        n = 0
    else:
        n = int(value)
    if n in (0, 1):
        return 1, [f"const/4 v0, {hex(n)}", "return v0"]
    return 1, [f"const v0, {hex(n & 0xFFFFFFFF)}", "return v0"]


def _value_for(action: str, ret: str):
    if action == "force_true":
        return "true"
    if action == "force_false":
        return "false"
    return 0  # return_zero / return_null / noop -> 0 (null for objects, 0 for primitives, void for V)


def patch_method_return(proj: Path, smali_files: list[Path], method: str, action: str = "force_true") -> dict:
    """Rewrite every overload of `method` in the given smali files to immediately return a
    constant (per `action`). Skips native/abstract methods (no body to replace)."""
    if action not in GUIDED_ACTIONS:
        raise ValueError(f"action must be one of {GUIDED_ACTIONS}")
    _snapshot(Path(proj), [Path(f) for f in smali_files], [])
    patched, skipped = [], []
    for sf in smali_files:
        sf = Path(sf)
        if not sf.is_file():
            continue
        lines = sf.read_text(encoding="utf-8", errors="ignore").splitlines()
        out, i, changed = [], 0, False
        start_re = re.compile(rf"^\s*\.method\b.*\b{re.escape(method)}\s*\(")
        while i < len(lines):
            line = lines[i]
            if start_re.search(line):
                j = i + 1
                while j < len(lines) and not lines[j].strip().startswith(".end method"):
                    j += 1
                rm = _RET_RE.search(line.strip())
                if (" native " in f" {line} ") or (" abstract " in f" {line} ") or not rm:
                    skipped.append(f"{sf.name}:{method} (native/abstract or unparsable return)")
                    out.extend(lines[i:j + 1])
                else:
                    ret = rm.group(1)
                    val = _value_for("return_zero" if (action == "noop" and ret != "V") else action, ret)
                    locals_n, body = _return_body(ret, val)
                    out.append(line)
                    out.append(f"    .locals {locals_n}")
                    out += [f"    {b}" for b in body]
                    out.append(".end method")
                    patched.append(f"{sf.name}::{method}(){ret}  ->  {' '.join(body)}")
                    changed = True
                i = j + 1
                continue
            out.append(line)
            i += 1
        if changed:
            sf.write_text("\n".join(out) + "\n", encoding="utf-8", newline="")
    return {
        "op": "guided_patch",
        "action": action,
        "method": method,
        "patched": patched,
        "skipped": skipped,
        "count": len(patched),
        "revertable": True,
        "next": "BUILD+SIGN, then install. (Smali-only patch: works with the full or code-only build.)"
                if patched else "no matching method found — check the class/method name.",
    }


# ---------- smali: neutralize a call ----------

_MOVE_RE = re.compile(r"^\s*move-result(-wide|-object)?\s+([vp]\d+)")


def neutralize_calls(proj: Path, smali_files: list[Path], callee: str) -> dict:
    """Delete `invoke-*` call sites to `callee` inside the given smali files. If the call's result
    was consumed by a following move-result*, it is replaced with 0/null so the register stays
    defined. `callee` is a bare method name ('isValid') or a full ref ('Lcom/x/Y;->isValid')."""
    _snapshot(Path(proj), [Path(f) for f in smali_files], [])
    needle = (re.escape(callee) + r"\(") if "->" in callee else (r"->" + re.escape(callee) + r"\(")
    inv_re = re.compile(r"^\s*invoke-[\w/-]+\b.*" + needle)
    removed = []
    for sf in smali_files:
        sf = Path(sf)
        if not sf.is_file():
            continue
        lines = sf.read_text(encoding="utf-8", errors="ignore").splitlines()
        out, i, changed = [], 0, False
        while i < len(lines):
            if inv_re.search(lines[i]):
                invoke = lines[i].strip()
                # is the result consumed by the next meaningful line?
                k = i + 1
                while k < len(lines) and (not lines[k].strip() or lines[k].strip().startswith("#")):
                    k += 1
                mv = _MOVE_RE.match(lines[k]) if k < len(lines) else None
                if mv:
                    kind, reg = mv.group(1), mv.group(2)
                    repl = f"    const-wide {reg}, 0x0" if kind == "-wide" else f"    const/4 {reg}, 0x0"
                    out.append(repl)  # replace invoke + move-result with a constant assignment
                    i = k + 1
                else:
                    i += 1  # void call: just drop the invoke line
                removed.append(f"{sf.name}: {invoke[:80]}")
                changed = True
                continue
            out.append(lines[i])
            i += 1
        if changed:
            sf.write_text("\n".join(out) + "\n", encoding="utf-8", newline="")
    return {
        "op": "neutralize_calls",
        "callee": callee,
        "removed": removed,
        "count": len(removed),
        "revertable": True,
        "next": "BUILD+SIGN, then install." if removed
                else "no call sites to that method found in this class.",
    }
