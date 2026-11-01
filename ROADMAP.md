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
- **Native `.so` analysis** — pure-stdlib ELF parser: arch, JNI entry points, exports/imports, NEEDED libs, exploit mitigations (NX/RELRO/canary/FORTIFY), URLs/strings + secret scan; shown read-only in the editor. Optional radare2 pseudo-code backend (`decompile_native`).
- **One-click "Make interceptable" (MITM) patch** — debuggable + a `network_security_config` trusting user CA certs + cleartext, via the `[ PATCH ▾ ]` menu (`make_interceptable`).
- **Guided smali patches** — right-click a method → force return true/false, return null/0, no-op, or **neutralize calls** to it → smali rewrite, then BUILD (`patch_method` / `neutralize_call`). Static counterpart to the Frida generator.
- **Reversible patches** — every static patch snapshots what it touches; `PATCH ▸ Revert` (`revert_patches`) restores the freshly-decompiled tree.
- **Editor method menu** — right-click a Java/smali method for Frida (trace / override return), "ask Claude for a Frida hook", guided smali patches, neutralize-call; right-click a symbol in the native report to pseudo-decompile it (radare2).
- **CI** — GitHub Actions smoke test: byte-compile, headless engine unit tests, full uv import, inline-UI-JS parse.
- Built-in Claude assistant (conversation memory, editable pre-prompt, orange tree-flash on file reads)
- Missing-tool handling + setup banner, apktool version warning + updater
- Cross-platform (macOS/Windows/Linux), native macOS Dock app, MCP server for Claude Code

## Biggest capability gaps (next)

- [ ] **Richer native decompilation** — bundle/offer a Ghidra-headless backend for cleaner pseudo-code than radare2, and a clickable function list in the native report (symbol → decompile) rather than right-click only.
- [ ] **Overload-specific patch targeting** — target a single overload by descriptor, not just by method name; and a signature/integrity-check bypass recipe.
- [ ] **Patch diff view** — show a before/after diff of what a one-click patch changed (undo already ships via `revert_patches`).

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
