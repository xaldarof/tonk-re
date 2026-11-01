#!/usr/bin/env python3
"""Headless engine tests for the pure-stdlib modules (native.py, patches.py).

Runnable with plain `python tests/test_engines.py` — no third-party deps, no external tools,
no network. Covers the guided/neutralize/MITM patches, revert, and ELF parsing + graceful
failure. Used by CI as the engine smoke test.
"""
import struct
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import native  # noqa: E402
import patches  # noqa: E402


def _mk_proj(tmp: str):
    proj = Path(tmp) / "proj"
    (proj / "apktool" / "smali" / "com" / "x").mkdir(parents=True)
    (proj / "apktool" / "AndroidManifest.xml").write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<manifest xmlns:android="http://schemas.android.com/apk/res/android" package="com.x">\n'
        '  <application android:label="X" android:allowBackup="true">\n'
        '    <activity android:name=".Main"/>\n  </application>\n</manifest>\n', encoding="utf-8")
    sm = proj / "apktool" / "smali" / "com" / "x" / "Root.smali"
    sm.write_text(
        '.class public Lcom/x/Root;\n.super Ljava/lang/Object;\n\n'
        '.method public isRooted()Z\n    .locals 2\n'
        '    invoke-static {}, Lcom/x/Root;->chk()Z\n    move-result v1\n    return v1\n.end method\n\n'
        '.method public report()V\n    .locals 0\n'
        '    invoke-static {}, Lcom/x/Log;->report()V\n    return-void\n.end method\n', encoding="utf-8")
    return proj, sm


def test_guided_patch():
    with tempfile.TemporaryDirectory() as t:
        proj, sm = _mk_proj(t)
        r = patches.patch_method_return(proj, [sm], "isRooted", "force_false")
        assert r["count"] == 1, r
        body = sm.read_text()
        assert "const/4 v0, 0x0" in body and "return v0" in body, body
        assert "Lcom/x/Root;->chk()" not in body, "isRooted body was not replaced"
        print("  guided_patch OK")


def test_neutralize():
    with tempfile.TemporaryDirectory() as t:
        proj, sm = _mk_proj(t)
        r = patches.neutralize_calls(proj, [sm], "report")
        assert r["count"] == 1, r
        assert "Lcom/x/Log;->report()" not in sm.read_text()
        print("  neutralize_calls OK")


def test_mitm_and_revert():
    with tempfile.TemporaryDirectory() as t:
        proj, sm = _mk_proj(t)
        patches.make_interceptable(proj)
        man = (proj / "apktool" / "AndroidManifest.xml").read_text()
        assert 'android:debuggable="true"' in man and 'networkSecurityConfig' in man, man
        assert (proj / "apktool" / "res" / "xml" / "network_security_config.xml").is_file()
        patches.patch_method_return(proj, [sm], "isRooted", "force_true")
        rev = patches.revert(proj)
        assert rev["count"] >= 1, rev
        man2 = (proj / "apktool" / "AndroidManifest.xml").read_text()
        assert 'android:debuggable="true"' not in man2, "manifest not restored"
        assert not (proj / "apktool" / "res" / "xml" / "network_security_config.xml").is_file(), "created file not deleted"
        assert "invoke-static" in sm.read_text(), "smali not restored"
        print("  mitm + revert OK")


def test_native_elf():
    with tempfile.TemporaryDirectory() as t:
        so = Path(t) / "mini.so"
        ident = b"\x7fELF" + bytes([2, 1, 1, 0]) + b"\x00" * 8  # ELF64, little-endian
        hdr = ident + struct.pack("<HHIQQQIHHHHHH", 3, 0xB7, 1, 0, 0, 0, 0, 64, 0, 0, 0, 0, 0)
        so.write_bytes(hdr)
        a = native.analyze_so(so)
        assert a.get("bits") == 64 and "AArch64" in a.get("arch", ""), a
        bad = Path(t) / "x.so"
        bad.write_bytes(b"not an elf")
        assert "error" in native.analyze_so(bad)
        print("  native ELF parse + graceful failure OK")


if __name__ == "__main__":
    print("engine tests:")
    test_guided_patch()
    test_neutralize()
    test_mitm_and_revert()
    test_native_elf()
    print("ALL ENGINE TESTS PASSED")
