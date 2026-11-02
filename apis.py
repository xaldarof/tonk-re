"""Sensitive-API usage catalog: which notable Android framework APIs an app calls,
grouped by capability, and cross-referenced against its declared permissions.

Pure leaf module (stdlib only, no server/gui import — same rule as native.py /
patches.py / report.py). The facade (server.py) owns scanning: it runs each catalog
pattern through its `_grep` and hands the matches here; this module only holds the
catalog and does the permission cross-reference / summary. That keeps scanning in one
place (DRY) and this module trivially unit-testable.

Each capability lists the regexes that signal it and the Android permission(s) that
*should* back it. Cross-referencing surfaces two interesting states:
  * used-but-not-declared  — the API is called but no matching permission is declared
    (reflection, a library doing it, or a manifest-merge quirk — worth a look).
  * declared-but-unused    — a permission is requested but no matching API call is seen
    (possible over-permission / privacy-policy gap; static-only, so verify).
"""
from __future__ import annotations

# capability -> (human label, [permission suffixes], [signal regexes])
# Permission suffixes are matched against the tail of a declared permission name
# (e.g. "android.permission.CAMERA" endswith "CAMERA").
API_CATALOG: dict[str, tuple[str, list[str], list[str]]] = {
    "location": ("Location", ["ACCESS_FINE_LOCATION", "ACCESS_COARSE_LOCATION", "ACCESS_BACKGROUND_LOCATION"],
                 [r"\bLocationManager\b", r"getLastKnownLocation", r"requestLocationUpdates",
                  r"FusedLocationProviderClient", r"getLastLocation"]),
    "telephony_id": ("Device / SIM identifiers", ["READ_PHONE_STATE", "READ_PHONE_NUMBERS"],
                     [r"getDeviceId\b", r"getImei\b", r"getMeid\b", r"getSubscriberId\b",
                      r"getSimSerialNumber\b", r"getLine1Number\b"]),
    "sms": ("SMS", ["SEND_SMS", "READ_SMS", "RECEIVE_SMS"],
            [r"SmsManager", r"sendTextMessage", r"content://sms"]),
    "contacts": ("Contacts", ["READ_CONTACTS", "WRITE_CONTACTS"],
                 [r"ContactsContract", r"content://com\.android\.contacts"]),
    "call_log": ("Call log", ["READ_CALL_LOG", "WRITE_CALL_LOG"],
                 [r"CallLog\b", r"content://call_log"]),
    "camera": ("Camera", ["CAMERA"],
               [r"android\.hardware\.Camera\b", r"android\.hardware\.camera2", r"androidx\.camera",
                r"\bCameraManager\b"]),
    "microphone": ("Microphone", ["RECORD_AUDIO"],
                   [r"\bMediaRecorder\b", r"\bAudioRecord\b"]),
    "clipboard": ("Clipboard", [],
                  [r"ClipboardManager", r"getPrimaryClip\b", r"setPrimaryClip\b"]),
    "accounts": ("Accounts", ["GET_ACCOUNTS"],
                 [r"\bAccountManager\b", r"getAccountsByType"]),
    "bluetooth": ("Bluetooth", ["BLUETOOTH", "BLUETOOTH_CONNECT", "BLUETOOTH_SCAN"],
                  [r"\bBluetoothAdapter\b", r"\bBluetoothManager\b"]),
    "wifi_scan": ("Wi-Fi / network info", ["ACCESS_WIFI_STATE", "ACCESS_NETWORK_STATE"],
                  [r"\bWifiManager\b", r"getScanResults", r"getConnectionInfo", r"\bConnectivityManager\b"]),
    "installed_apps": ("Installed-app enumeration", ["QUERY_ALL_PACKAGES"],
                       [r"getInstalledPackages", r"getInstalledApplications", r"queryIntentActivities"]),
    "external_storage": ("External storage", ["READ_EXTERNAL_STORAGE", "WRITE_EXTERNAL_STORAGE", "MANAGE_EXTERNAL_STORAGE"],
                         [r"getExternalStorageDirectory", r"\bMediaStore\b", r"Environment\.getExternal"]),
    "crypto": ("Cryptography", [],
               [r"Cipher\.getInstance", r"\bKeyStore\b", r"SecretKeySpec", r"MessageDigest\.getInstance",
                r"\bKeyGenerator\b", r"\bMac\.getInstance"]),
    "network": ("Network I/O", ["INTERNET"],
                [r"HttpURLConnection", r"\bOkHttpClient\b", r"Retrofit", r"\bSocket\b",
                 r"URL\(", r"WebView"]),
    "reflection": ("Reflection", [],
                   [r"Class\.forName", r"getDeclaredMethod", r"getDeclaredField", r"setAccessible",
                    r"getMethod\("]),
    "process_exec": ("Process execution", [],
                     [r"Runtime\.getRuntime\(\)\.exec", r"\bProcessBuilder\b"]),
    "dynamic_load": ("Dynamic code loading", [],
                     [r"DexClassLoader", r"PathClassLoader", r"InMemoryDexClassLoader",
                      r"System\.load\b", r"System\.loadLibrary"]),
    "device_admin": ("Device admin", ["BIND_DEVICE_ADMIN"],
                     [r"DevicePolicyManager", r"DeviceAdminReceiver"]),
    "accessibility": ("Accessibility service", ["BIND_ACCESSIBILITY_SERVICE"],
                      [r"AccessibilityService\b", r"AccessibilityNodeInfo"]),
    "biometric": ("Biometric / fingerprint", ["USE_BIOMETRIC", "USE_FINGERPRINT"],
                  [r"BiometricPrompt", r"FingerprintManager"]),
    "nfc": ("NFC", ["NFC"], [r"\bNfcAdapter\b"]),
    "sensors": ("Sensors", ["BODY_SENSORS", "ACTIVITY_RECOGNITION"],
                [r"\bSensorManager\b", r"registerListener\(.*Sensor"]),
    "notifications": ("Notifications", ["POST_NOTIFICATIONS"],
                      [r"NotificationManager", r"NotificationCompat"]),
    "root_check": ("Root / su probing", [],
                   [r"/system/(?:bin|xbin)/su", r"\bmagisk\b", r"Superuser\.apk", r"RootBeer"]),
}


def catalog_patterns() -> dict[str, list[str]]:
    """capability -> its signal regexes (for the facade to grep)."""
    return {cap: spec[2] for cap, spec in API_CATALOG.items()}


def _declares(perm_suffixes: list[str], declared: set[str]) -> bool:
    return any(d.rsplit(".", 1)[-1] == suf or d.endswith("." + suf) for suf in perm_suffixes for d in declared)


def cross_reference(found: dict[str, list[str]], declared_permissions: list[str]) -> dict:
    """Combine detected API usage with declared permissions.

    `found` maps capability -> list of hit lines (as the facade's grep produced them).
    Returns a per-capability summary plus the two cross-reference lists.
    """
    declared = set(declared_permissions or [])
    capabilities = []
    used_not_declared, declared_not_used = [], []

    for cap, (label, perm_suffixes, _patterns) in API_CATALOG.items():
        hits = found.get(cap, [])
        has_perm = _declares(perm_suffixes, declared) if perm_suffixes else None
        if hits:
            capabilities.append({
                "capability": cap, "label": label, "count": len(hits),
                "permissions": perm_suffixes, "permission_declared": has_perm,
                "hits": hits[:12],
            })
            if perm_suffixes and has_perm is False:
                used_not_declared.append({"capability": cap, "label": label,
                                          "permissions": perm_suffixes})

    # permissions declared but with no matching API usage seen (static-only signal)
    used_caps = {c["capability"] for c in capabilities}
    for cap, (label, perm_suffixes, _patterns) in API_CATALOG.items():
        if perm_suffixes and cap not in used_caps and _declares(perm_suffixes, declared):
            declared_not_used.append({"capability": cap, "label": label, "permissions": perm_suffixes})

    capabilities.sort(key=lambda c: -c["count"])
    return {
        "capabilities": capabilities,
        "used_not_declared": used_not_declared,
        "declared_but_unused": declared_not_used,
        "summary": {"capabilities_used": len(capabilities),
                    "used_not_declared": len(used_not_declared),
                    "declared_but_unused": len(declared_not_used)},
    }


def format_report(result: dict) -> str:
    """Plain-text rendering for the CLI / GUI panel."""
    if not (result["capabilities"] or result["used_not_declared"] or result["declared_but_unused"]):
        return "No sensitive API usage detected."
    out = []
    s = result["summary"]
    out.append(f"{s['capabilities_used']} capability group(s) used · "
               f"{s['used_not_declared']} used-without-permission · "
               f"{s['declared_but_unused']} declared-but-unused\n")
    for c in result["capabilities"]:
        perm = ""
        if c["permissions"]:
            mark = {True: "declared", False: "NOT declared", None: ""}[c["permission_declared"]]
            perm = f"  [perm {'/'.join(c['permissions'])}: {mark}]"
        out.append(f"== {c['label']} ({c['count']}){perm}")
        out.extend("   " + h for h in c["hits"])
        out.append("")
    if result["used_not_declared"]:
        out.append("!! Used without a matching declared permission (verify — reflection/library/merge):")
        out.extend(f"   - {c['label']} (expected {'/'.join(c['permissions'])})"
                   for c in result["used_not_declared"])
        out.append("")
    if result["declared_but_unused"]:
        out.append("?? Declared but no matching API usage seen (possible over-permission; static-only):")
        out.extend(f"   - {'/'.join(c['permissions'])} ({c['label']})"
                   for c in result["declared_but_unused"])
    return "\n".join(out).rstrip()
