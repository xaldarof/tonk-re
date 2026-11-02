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
import projects  # noqa: E402
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


class TestProjectsContainer(unittest.TestCase):
    def _doc(self):
        doc = projects.new_doc("base-aa")
        projects.add_member(doc, "base-aa", ".", "/x/base.apk", "aa", "base")
        projects.add_member(doc, "split-bb", projects.member_dirname("split-bb"),
                            "/x/split.apk", "bb", "split")
        return doc

    def test_add_member_is_idempotent_on_name(self):
        doc = self._doc()
        projects.add_member(doc, "base-aa", ".", None, None)  # same name again
        self.assertEqual(len(doc["members"]), 2)

    def test_primary_and_member_dirname(self):
        doc = self._doc()
        self.assertTrue(projects.is_primary(doc, "base-aa"))
        self.assertFalse(projects.is_primary(doc, "split-bb"))
        self.assertEqual(projects.member_dirname("split-bb"), "attached/split-bb")

    def test_member_dirname_sanitizes(self):
        # path separators / unsafe chars collapse to underscores, leading ./_ are stripped,
        # so a hostile member name cannot escape the attached/ subdir
        out = projects.member_dirname("../../etc/passwd")
        self.assertEqual(out, "attached/etc_passwd")
        self.assertNotIn("..", out)
        self.assertNotIn("/", out[len("attached/"):])

    def test_round_trip_preserves_members_and_fills_defaults(self):
        doc = projects.load(projects.dumps(self._doc()))
        self.assertEqual(doc["primary"], "base-aa")
        self.assertEqual(doc["members"][1]["label"], "split")

    def test_load_defaults_label_and_dir(self):
        doc = projects.load('{"members": [{"name": "only"}]}')
        self.assertEqual(doc["members"][0]["label"], "only")
        self.assertEqual(doc["members"][0]["dir"], ".")
        self.assertEqual(doc["primary"], "only")  # inferred from first member

    def test_load_rejects_malformed(self):
        with self.assertRaises(ValueError):
            projects.load('{"nope": 1}')


if __name__ == "__main__":
    unittest.main()
