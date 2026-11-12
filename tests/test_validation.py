"""Tests for catalog format 2, part 1: validation rules. Run: python3 -I -m unittest discover -s tests"""
import copy
import hashlib
import pathlib
import re
import tomllib
import unittest
import xml.etree.ElementTree as ET
from unittest import mock

from support import *  # noqa: F401,F403
from support import CAPS, CAPS_FILE, GOOD, PNG, RAW, ROOT, S, build, gen, local_fetch, messages, problems, release_for, with_, wrap

class Validation(unittest.TestCase):
    def test_minimal_good_package(self):
        self.assertEqual(problems(GOOD), [])

    def test_old_entry_is_valid_in_schema_1(self):
        old = {k: GOOD[k] for k in ("id", "name", "summary", "repo", "tag", "asset")}
        self.assertEqual(problems(old, schema=1), [])
        warned = [str(i) for i in S.validate(old, None, 1) if not i.error]
        self.assertTrue(any("icon" in w for w in warned))  # ... but it says what is missing

    def test_same_old_entry_is_an_error_in_schema_2(self):
        old = {k: GOOD[k] for k in ("id", "name", "summary", "repo", "tag", "asset")}
        m = messages(old, schema=2)
        self.assertIn("icon", m)
        self.assertIn("provides", m)
        self.assertIn("description", m)

    def test_kinds(self):
        for k in ("program", "frontend", "component", "theme", "server", "icon-theme"):
            p = with_(kind=k, requires=["tasks"], min_store="0.0.13")
            self.assertEqual(problems(p), [], k)
        self.assertIn("kind", messages(with_(kind="Server")))
        self.assertIn("kind", messages(with_(kind="app")))

    def test_required_per_kind(self):
        no = {k: v for k, v in GOOD.items() if k != "provides"}
        self.assertIn("provides", messages({**no, "kind": "server"}))
        self.assertIn("provides", messages({**no, "kind": "program"}))
        self.assertIn("requires", messages({**no, "kind": "frontend"}))
        self.assertEqual(problems({**no, "kind": "theme"}), [])      # counter-check: a theme offers nothing
        self.assertEqual(problems({**no, "kind": "icon-theme", "min_store": "0.0.13"}), [])
        self.assertEqual(problems({**no, "kind": "frontend", "requires": ["tasks"]}), [])

    def test_capability_names_only_from_the_list(self):
        self.assertIn("not in the capability list", messages(with_(provides=["tsaks"])))
        self.assertIn("did you mean `tasks`", messages(with_(provides=["tsaks"])))
        self.assertIn("not in the capability list", messages(with_(requires=["wiki"])))
        self.assertIn("not in the capability list", messages(with_(recommends=["people.persons.x"])))
        for ok in ("tasks", "people.persons 1.2", "people.persons>=1.2", "identity.oidc 2"):
            self.assertEqual(problems(with_(provides=[ok])), [], ok)

    def test_capability_form(self):
        self.assertIn("is not a capability", messages(with_(provides=["Tasks"])))
        self.assertIn("is not a capability", messages(with_(provides=["tasks 1.2.3"])))
        self.assertIn("is not a capability", messages(with_(provides=["tasks one"])))
        self.assertIn("listed twice", messages(with_(provides=["tasks", "tasks 1.0"])))
        self.assertIn("must be a list", messages(with_(provides="tasks")))

    def test_planned_capability_is_only_a_warning(self):
        issues = S.validate(with_(provides=["storage.provider"]), CAPS, 2)
        self.assertEqual([i for i in issues if i.error], [])
        self.assertTrue(any("planned" in str(i) for i in issues))

    def test_feature_level(self):
        self.assertEqual(problems(with_(feature=[{"key": "export"}])), [])  # may stay empty
        self.assertEqual(problems(with_(feature=[{"key": "c", "provides": ["people.persons 1.0"], "requires": ["comments"]}])), [])
        self.assertIn("not in the capability list", messages(with_(feature=[{"key": "c", "provides": ["nope"]}])))
        self.assertIn("needs `key`", messages(with_(feature=[{"provides": ["tasks"]}])))
        self.assertIn("listed twice", messages(with_(feature=[{"key": "a"}, {"key": "a"}])))

    def test_pictures_need_a_clear_licence(self):
        shot = {"url": "https://x/a.png", "license": "CC0-1.0", "source": "own work", "caption": "c"}
        self.assertEqual(problems(with_(screenshot=[shot])), [])
        for bad in ("", "unknown", "None", "proprietary", "All rights reserved", "<b>", "CC0;1.0"):
            self.assertIn("licence", messages(with_(screenshot=[{**shot, "license": bad}])), bad)
        no_license = {k: v for k, v in shot.items() if k != "license"}
        self.assertIn("licence", messages(with_(screenshot=[no_license])))
        self.assertEqual(problems(with_(screenshot=[{**shot, "license": "CC-BY-SA-4.0 OR MIT"}])), [])

    def test_picture_other_fields(self):
        shot = {"url": "https://x/a.png", "license": "CC0-1.0", "source": "own work", "caption": {"en": "c"}}
        self.assertIn("https", messages(with_(screenshot=[{**shot, "url": "http://x/a.png"}])))
        self.assertIn("source", messages(with_(screenshot=[{k: v for k, v in shot.items() if k != "source"}])))
        self.assertIn("source", messages(with_(screenshot=[{**shot, "source": "http://insecure"}])))
        self.assertIn("caption", messages(with_(screenshot=[{**shot, "caption": ""}])))
        self.assertIn("sha256", messages(with_(screenshot=[{**shot, "sha256": "ABC"}])))
        self.assertIn("sha256", messages(with_(screenshot=[{**shot, "sha256": "A" * 64}])))  # upper case is not the format
        self.assertEqual(problems(with_(screenshot=[{**shot, "sha256": "a" * 64}])), [])

    def test_icon(self):
        self.assertIn("https", messages(with_(icon="http://x/i.png")))
        self.assertIn("icon_sha256", messages(with_(icon_sha256="xyz")))
        self.assertEqual(problems(with_(icon_sha256="0" * 64)), [])

    def test_origin(self):
        ok = {"upstream": "https://u.org/x", "source_code": "https://u.org/x.tar.gz", "upstream_signature": "16A4 A3EE 563A EF51 FCF0  C55D ED7B 57C4 A190 4342"}
        self.assertEqual(problems(with_(**ok)), [])
        self.assertEqual(problems(with_(**{**ok, "upstream_signature": "https://u.org/x.asc"})), [])
        self.assertIn("source_code", messages(with_(upstream="https://u.org/x")))          # mirrored: source code is mandatory
        self.assertIn("upstream_signature", messages(with_(**{**ok, "upstream_signature": "trust me"})))
        self.assertIn("needs `upstream`", messages(with_(upstream_signature="https://u.org/x.asc")))
        self.assertIn("https", messages(with_(upstream="http://u.org/x", source_code="https://a/b")))

    def test_wiki_description(self):
        block = "0192f3a0-7b1c-7a3e-8c4d-5e6f7a8b9c0d"
        self.assertEqual(problems(with_(description_wiki={"block": block, "source_rev": 3})), [])
        self.assertEqual(problems(with_(description_wiki={"block": block, "source_rev": 0, "lang": "de"})), [])  # lang = optional wish
        self.assertIn("UUIDv7", messages(with_(description_wiki={"block": "0192f3a0-7b1c-4a3e-8c4d-5e6f7a8b9c0d", "source_rev": 1})))  # v4
        self.assertIn("UUIDv7", messages(with_(description_wiki={"block": "not-a-uuid", "source_rev": 1})))
        self.assertIn("source_rev", messages(with_(description_wiki={"block": block})))
        self.assertIn("source_rev", messages(with_(description_wiki={"block": block, "source_rev": -1})))
        self.assertIn("wish", messages(with_(description_wiki={"block": block, "source_rev": 1, "lang": "DE!"})))
        for k in ("translation_of", "translationOf", "blocks"):  # one block, no block per language
            self.assertIn("not a field", messages(with_(description_wiki={"block": block, "source_rev": 1, k: "x"})))

    def test_new_kinds_need_schema_2_and_min_store(self):
        for k in ("server", "icon-theme"):
            p = with_(kind=k, min_store="0.0.13")
            self.assertEqual(problems(p, schema=2), [], k)
            self.assertIn("schema = 2", messages(p, schema=1))
            self.assertIn("min_store", messages(with_(kind=k)))
        self.assertIn("min_store", messages(with_(kind="server", min_store="13")))
        self.assertEqual(problems(with_(kind="theme")), [])            # old kinds need no minimum
        self.assertEqual(problems(with_(min_store="0.0.13")), [])     # but may state one
        self.assertIn("min_store", messages(with_(min_store="new")))

    def test_mediatypes(self):
        self.assertEqual(problems(with_(mediatypes=["text/calendar", "application/vnd.x+json"])), [])
        self.assertIn("mediatypes", messages(with_(mediatypes=["calendar"])))
        self.assertIn("mediatypes", messages(with_(mediatypes=["Text/Calendar"])))

    def test_history_and_changes(self):
        h = [{"version": "0.0.2", "changes": {"en": "a", "de": "b"}}, {"version": "0.0.1", "date": "2026-11-01", "changes": "x"}]
        self.assertEqual(problems(with_(history=h)), [])
        self.assertIn("date", messages(with_(history=[{"version": "0.0.1", "changes": "x"}])))        # old release without a date
        self.assertIn("date", messages(with_(history=[{"version": "0.0.1", "date": "01.11.2026", "changes": "x"}])))
        self.assertIn("`en`", messages(with_(history=[{"version": "0.0.2", "changes": {"de": "b"}}])))
        self.assertIn("changes", messages(with_(history=[{"version": "0.0.2"}])))
        self.assertIn("version", messages(with_(history=[{"version": "2", "changes": "x"}])))

    def test_missing_change_text_never_stops_a_run(self):  # bump raises the tag without knowing a text
        issues = S.validate(GOOD, CAPS, 2)
        self.assertTrue(any(i.field == "history" and not i.error for i in issues))

    def test_installed_size(self):
        self.assertEqual(problems(with_(installed_size={"0.0.2": 5})), [])
        self.assertIn("installed_size", messages(with_(installed_size={"0.0.2": "5"})))
        self.assertIn("installed_size", messages(with_(installed_size=5)))

    def test_text_rules(self):
        self.assertIn("XML does not allow", messages(with_(summary="a\x00b")))
        self.assertIn("`en`", messages(with_(description={"de": "x"})))
        self.assertIn("language", messages(with_(description={"en": "x", "DE!": "y"})))
        self.assertIn("tag", messages(with_(tag="0.0.2")))
        self.assertIn("id", messages(with_(id="Fs_X")))

    def test_error_text_names_package_and_field(self):
        i = problems(with_(provides=["nope"]))[0]
        self.assertTrue(str(i).startswith("fs-x: provides:"))

    def test_the_real_packages_toml_has_no_errors(self):
        data = tomllib.loads((ROOT / "packages.toml").read_text())
        for p in data["package"]:
            self.assertEqual(problems(p, schema=data.get("schema", 1)), [], p["id"])


class Capabilities(unittest.TestCase):
    def test_parse_list_file(self):
        self.assertEqual(CAPS["tasks"], "stable")
        self.assertEqual(CAPS["storage.provider"], "planned")
        self.assertNotIn("# TEST", " ".join(CAPS))

    def test_format_is_what_the_stores_reader_parses(self):
        self.assertEqual(S.format_capabilities(["people.persons>=1.2", "tasks", "identity.oidc 2"]), "people.persons 1.2, tasks, identity.oidc 2.0")


# ---- the generator, with GitHub and the network replaced -------------------------------------------------------------------
