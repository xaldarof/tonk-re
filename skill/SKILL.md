---
name: tonk-re
description: Decompile and reverse engineer Android APK/XAPK/APKS files with the tonk-re MCP tools (jadx + apktool). Use when the user gives an .apk or asks to analyze, audit, or understand an Android app.
---

# APK reverse engineering workflow

Tools come from the `tonk-re` MCP server (`mcp__tonk-re__*`).

1. **Decompile**: `decompile_apk(apk_path)` (cached by SHA-256). Keep the returned `project` name.
   Use `deobfuscate=true` if class names look like `a.b.c`.
2. **Orient**: review the manifest summary, then `package_tree` to separate app code from libraries
   (androidx, kotlin, okhttp, com.google are usually noise).
3. **Attack surface**: `apk_info` → exported components, deep-link schemes, debuggable/allowBackup/
   cleartext flags. Read handlers for every exported component with `read_class`.
4. **Sweeps**: `find_secrets`, `find_urls`, `find_crypto_and_security`. Confirm every hit by reading
   the surrounding code; regex hits are leads, not findings.
5. **Dig in**: `search_code` (scopes: java/smali/resources/all), `xrefs`, `read_class`, `read_file`.
   When jadx output is broken (`/* JADX WARNING */`), read the smali at `apktool/smali*/...`.
6. **Native / non-Java**: Flutter (`libapp.so`), React Native (`assets/index.android.bundle`),
   Unity, and Xamarin need other tools. Hand `.so` files to the REA tools
   (`reverse-engineer-anything` skill) and use `read_file` for JS bundles.
7. **Report**: package, SDKs, frameworks, attack surface, confirmed findings with
   `file:line` evidence and severity, and open questions.

Analyze only apps the user owns or is authorized to test.
