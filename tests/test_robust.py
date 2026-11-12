"""Tests for catalog format 2, part 4: wrong types never crash, form errors are always errors, and the surviving mutants of the review.
Run: python3 -I -m unittest discover -s tests"""
import io
import contextlib
import unittest
from unittest import mock

from support import CAPS, CAPS_FILE, GOOD, PNG, S, build, gen, messages, problems, with_

VALUES = [None, 1, -1, True, 1.5, "", "x", "x y z", "https://x", [], [1], ["x"], ["x y z"], {}, {"en": 1}, {"en": "x", "de": 2}, {"block": 1},
          [{}], [{"key": 1}], [{"key": "k", "name": 1}], [{"url": "https://x", "license": 1, "source": "x", "caption": {"en": 1}}],
          [{"version": 1}], [{"version": "0.0.1", "changes": {"en": 1}}], [[1]], {"0.0.1": "x"}, "\x00", {"en": "￾"}]
FIELDS = ["id", "name", "summary", "kind", "description", "icon", "icon_sha256", "provides", "requires", "recommends", "feature", "mediatypes",
          "installed_size", "history", "upstream", "upstream_signature", "source_code", "maker", "description_wiki", "min_store", "screenshot", "tag"]


class NeverCrashes(unittest.TestCase):
    def setUp(self):
        gen.CTX.update(checked=False)
        self.addCleanup(gen.CTX.update, schema=1, caps=None, caps_file=None, checked=False)

    def test_validate_and_build_survive_every_wrong_type(self):  # a stand-in for the review's fuzz.py
        base = {k: GOOD[k] for k in ("id", "name", "summary", "repo", "tag", "asset")}
        for field in FIELDS:
            for value in VALUES:
                for schema in (1, 2):
                    p = {**base, field: value}
                    where = f"{field}={value!r} schema {schema}"
                    try:
                        issues = S.validate(p, CAPS, schema)
                    except Exception as why:  # noqa: BLE001
                        self.fail(f"validate raised {why!r} for {where}")
                    for i in issues:
                        self.assertTrue(str(i).startswith(f"{i.package}: {i.field}: ") and i.message and i.package and i.field, where)
                    if not any(i.error for i in issues):
                        try:
                            with contextlib.redirect_stdout(io.StringIO()):
                                build(p, fetch=lambda u, limit=None: PNG, schema=schema)  # what sign would do with it
                        except Exception as why:  # noqa: BLE001
                            self.fail(f"the generator raised {why!r} for {where}, which validate accepts")

    def test_each_reported_case_is_a_message_not_a_traceback(self):
        cases = [
            ({"feature": [{"key": 1}]}, "key"), ({"history": [{"version": "0.0.2", "changes": {"en": 1}}]}, "changes"),
            ({"screenshot": [{"url": "https://x/a.png", "license": "CC0-1.0", "source": "s", "caption": {"en": 1}}]}, "caption"),
            ({"description": {"en": "x", "de": 2}}, "description"), ({"kind": []}, "kind"), ({"kind": {}}, "kind"), ({"description": {"en": 1}}, "description"),
            ({"screenshot": [{"url": "https://x/a.png", "license": 1, "source": "s", "caption": "c"}]}, "licence"),
            ({"provides": 1}, "must be a list"), ({"provides": "x"}, "must be a list"), ({"provides": ["x y z"]}, "not a capability"),
        ]
        for extra, word in cases:
            for schema in (1, 2):
                self.assertIn(word, messages(with_(**extra), schema=schema), f"{extra} schema {schema}")
                self.assertTrue(problems(with_(**extra), schema=schema), f"{extra} schema {schema} must be an error")

    def test_only_unknown_names_are_warnings_in_schema_1(self):
        self.assertEqual(problems(with_(provides=["tsaks"]), schema=1), [])
        for bad in (1, "tasks", ["Tasks"], ["tasks 1.2.3"]):
            self.assertTrue(problems(with_(provides=bad), schema=1), bad)       # a form error is an error in schema 1, too
            self.assertTrue(problems(with_(feature=[{"key": "f", "requires": bad}]), schema=1), bad)

    def test_language_tables_only_hold_text(self):
        for bad in ({"en": 1}, {"en": ["x"]}, {"en": "x", "de": None}, {"en": "x", "de": 2}, {1: "x", "en": "y"}):
            self.assertTrue(S.text_problem(bad), bad)
        self.assertIsNone(S.text_problem({"en": "x", "de": "y"}))


class SurvivingMutants(unittest.TestCase):
    def test_licence_characters_are_those_of_the_store(self):  # details.rs: ascii alphanumeric and " .-+()"
        for bad in ("MIT/Apache-2.0", "MIT, Apache-2.0", "CC0;1.0", "Ünlicense", "a_b", "x\ty"):
            self.assertFalse(S.clear_license(bad), bad)
        for ok in ("MIT", "Apache-2.0 OR MIT", "(MIT OR Apache-2.0)", "GPL-3.0+", "LicenseRef-x.1"):
            self.assertTrue(S.clear_license(ok), ok)
        self.assertFalse(S.clear_license(1))
        self.assertFalse(S.clear_license(None))

    def test_picture_size_limit(self):
        limit = S.SCREENSHOT_LIMIT
        self.assertTrue(S.image_ok(PNG + b"0" * (limit - len(PNG))))
        self.assertFalse(S.image_ok(PNG + b"0" * (limit - len(PNG) + 1)))

    def test_duplicate_history_version(self):
        h = {"version": "0.0.2", "changes": "x"}
        self.assertIn("listed twice", messages(with_(history=[h, dict(h)])))
        self.assertNotIn("listed twice", messages(with_(history=[h, {"version": "0.0.1", "date": "2026-11-01", "changes": "y"}])))

    def test_second_length_check_in_fetch(self):  # curl exit 0 but more bytes than allowed
        with mock.patch.object(gen.subprocess, "run", lambda *a, **k: mock.Mock(returncode=0, stdout=b"x" * 11)), mock.patch.object(gen.net, "_public_host", lambda u: True):
            with self.assertRaises(SystemExit) as r:
                gen.fetch("https://e.org/a.png", 10)
            self.assertIn("larger than", str(r.exception))
            self.assertEqual(gen.fetch("https://e.org/a.png", 11), b"x" * 11)

    def test_the_xml_guard_catches_what_validate_missed(self):
        gen.CTX.update(schema=2, caps=CAPS, checked=True)  # as after main's check, which would have refused this
        self.addCleanup(gen.CTX.update, schema=1, caps=None, checked=False)
        with self.assertRaises(SystemExit) as r:
            build(with_(summary="a\x01b"))
        self.assertIn("not well-formed", str(r.exception))

    def test_characters_xml_does_not_allow_are_errors(self):
        for ch in ("\x00", "\x1f", "￾", "￿", "\ud800"):
            self.assertIn("XML does not allow", messages(with_(summary=f"a{ch}b")), repr(ch))
        self.assertEqual(problems(with_(summary="tab\tand\nnewline ok")), [])


class Settings(unittest.TestCase):
    def test_capabilities_ref_form(self):
        for bad in ("0.0.19", "v0.0", "main", "v1.2.3-rc", 19, ["v0.0.19"]):
            with self.assertRaises(SystemExit, msg=repr(bad)):
                gen.checks.read_settings({"capabilities_ref": bad})
        gen.checks.read_settings({"capabilities_ref": "v0.0.20"})
        self.assertEqual(gen.CTX["caps_ref"], "v0.0.20")
        gen.checks.read_settings({})
        self.assertEqual(gen.CTX["caps_ref"], gen.checks.DEFAULT_CAPS_REF)
        for bad in (0, 3, True, "2", []):
            with self.assertRaises(SystemExit, msg=repr(bad)):
                gen.checks.read_settings({"schema": bad})

    def test_fixture_is_the_snapshot_of_the_default_tag(self):  # the tag can move on GitHub; this ties fixture and default together
        head = CAPS_FILE.read_text().splitlines()[0]
        self.assertIn(gen.checks.DEFAULT_CAPS_REF, head)

    def tearDown(self):
        gen.CTX.update(schema=1, caps_ref=gen.checks.DEFAULT_CAPS_REF)


if __name__ == "__main__":
    unittest.main()
