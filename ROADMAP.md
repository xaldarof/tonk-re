# TONK-RE Roadmap

Planned and proposed features, grouped by impact. Not committed to dates — a backlog to pull from.
Contributions welcome; open an issue to claim one.

## Shipped

- Decompile `.apk/.xapk/.apks/.apkm` (jadx + apktool)
- Manifest attack-surface summary (exported components, deep links, permissions, flags, native libs, framework detection)
- Secret / URL / crypto-security scanners, regex search (java/smali/resources)
- Syntax-highlighted editor, Java ⇄ smali bridge
- Rebuild & sign (apktool / zipalign / apksigner), with code-only build fallback when resource re-linking fails
- `RESIGN APK`, `INSTALL ▸ ADB`
- Deep-link / intent tester (exported components + deep links as `adb am` commands)
- Version diff (permissions / components / classes / URLs / flags)
- Frida hook generator (trace / stacktrace / return-override / SSL & root bypass)
- Built-in Claude assistant (conversation memory, editable pre-prompt, orange tree-flash on file reads)
- Missing-tool handling + setup banner, apktool version warning + updater
- Cross-platform (macOS/Windows/Linux), native macOS Dock app, MCP server for Claude Code

## Biggest capability gaps (next)

- [ ] **Native `.so` analysis** — hand `.so` files to the REA tools for decompiled pseudo-code + exports, shown in the editor. Unblocks Flutter / NDK / game apps where logic lives in native code.
- [ ] **One-click "Make interceptable" (MITM) patch** — set `android:debuggable="true"` and inject a `network_security_config` that trusts user CA certs, then rebuild + sign. The standard prep for Burp / mitmproxy.
- [ ] **Guided smali patches** — pick a method → "force return true/false", "bypass root/premium check", "neutralize a call" → apply the smali edit, then BUILD. Static counterpart to the Frida generator.

## Dynamic analysis (uses adb / maestro)

- [ ] **Device panel** — list devices, screenshot, pull/push files.
- [ ] **Live logcat viewer** — stream logcat filtered to the package; pairs with the intent tester.
- [ ] **Run + observe** — launch via adb and capture logcat around a triggered action.

## Quick wins

- [ ] **Tracker / SDK detection** — flag bundled ad / analytics / tracking SDKs (Exodus-style signatures) in the INFO panel.
- [ ] **Report export** — dump findings (manifest risks, secrets, URLs, crypto issues) as a shareable Markdown / HTML audit report.
- [ ] **Resource viewer** — render drawables / icons and the strings table instead of raw XML.
- [ ] **Claude "full audit" button** — one click runs a structured Claude pass and writes `AUDIT.md` into the project.
- [ ] **Per-project bookmarks / notes** — mark interesting classes / lines while exploring.

## Polish

- [ ] **CI** — `py_compile` + a headless smoke test on push.
- [ ] **Demo GIF** in the README.
- [ ] **Method-level diff** in the version-diff view (not just changed-class list).
- [ ] **Native window** on Windows/Linux (currently a Chromium app window), matching the macOS app.

---

Only analyze apps you own or are authorized to test.
