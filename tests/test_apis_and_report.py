"""Unit tests for the dependency-light leaf engines (apis, report).

These modules are stdlib-only, so this runs with a bare interpreter and no install:

    python -m unittest discover -s tests

(The server-level helpers — Java method extraction, secret entropy, API scanning —
are covered by `tonkre selftest`, which runs under the uv script runtime that provides
the `mcp` dependency `server.py` needs.)
"""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import apis  # noqa: E402
import report  # noqa: E402


class TestApiCatalog(unittest.TestCase):
    def test_catalog_patterns_nonempty(self):
        pats = apis.catalog_patterns()
        self.assertIn("camera", pats)
        self.assertTrue(all(isinstance(v, list) and v for v in pats.values()))

    def test_used_without_permission_flagged(self):
        r = apis.cross_reference({"camera": ["x.java:1:CameraManager"]},
                                 ["android.permission.INTERNET"])
        self.assertEqual(r["summary"]["capabilities_used"], 1)
        self.assertEqual(r["summary"]["used_not_declared"], 1)
        self.assertEqual(r["used_not_declared"][0]["capability"], "camera")

    def test_used_with_permission_not_flagged(self):
        r = apis.cross_reference({"camera": ["x.java:1:CameraManager"]},
                                 ["android.permission.CAMERA"])
        self.assertEqual(r["summary"]["used_not_declared"], 0)
        self.assertTrue(r["capabilities"][0]["permission_declared"])

    def test_declared_but_unused_flagged(self):
        r = apis.cross_reference({}, ["android.permission.CAMERA"])
        self.assertEqual(r["summary"]["declared_but_unused"], 1)
        self.assertEqual(r["declared_but_unused"][0]["capability"], "camera")

    def test_no_permission_capability_has_none_state(self):
        # clipboard has no backing permission -> permission_declared is None, never flagged
        r = apis.cross_reference({"clipboard": ["x.java:1:ClipboardManager"]}, [])
        self.assertIsNone(r["capabilities"][0]["permission_declared"])
        self.assertEqual(r["summary"]["used_not_declared"], 0)

    def test_format_report_empty(self):
        self.assertIn("No sensitive API usage", apis.format_report(apis.cross_reference({}, [])))


class TestReport(unittest.TestCase):
    def test_renders_empty_project(self):
        md = report.build_markdown({"project": "p", "info": {}})
        self.assertIn("# Security audit", md)
        self.assertIn("No secret patterns matched", md)

    def test_renders_populated(self):
        md = report.build_markdown({
            "project": "demo", "sha256": "ab", "info": {
                "package": "com.x", "application": {"debuggable": "true"},
                "permissions": ["android.permission.CAMERA"],
                "exported_components": [{"type": "activity", "name": "A", "permission": None, "schemes": []}],
                "native_libs": [],
            },
            "secrets": {"google_api_key": ["res/strings.xml:3:AIza..."]},
            "urls": {"https://x.test": "a.java"},
            "security": {"ecb_or_des": ["c.java:1:AES/ECB"]},
            "signing": None,
        })
        self.assertIn("com.x", md)
        self.assertIn("google_api_key", md)
        self.assertIn("https://x.test", md)


if __name__ == "__main__":
    unittest.main()
