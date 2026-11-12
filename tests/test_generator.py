"""Tests for catalog format 2, part 2: the generator with GitHub and the network replaced, examples, reader contract."""
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

class Generator(unittest.TestCase):
    def setUp(self):
        gen.CTX.update(checked=False)
        self.addCleanup(gen.CTX.update, schema=1, caps=None, caps_file=None, checked=False)

    def test_new_fields_come_out(self):
        p = with_(
            description={"en": "Hello.\n\nTwo.", "de": "Hallo."}, installed_size={"0.0.2": 999}, mediatypes=["text/calendar"],
            requires=["store"], recommends=["comments 1.0"], upstream="https://u.org/x", source_code="https://u.org/s.tgz",
            upstream_signature="ABCD" * 10, maker="M",
            history=[{"version": "0.0.2", "changes": {"en": "Fixed.", "de": "Behoben."}}, {"version": "0.0.1", "date": "2026-11-01", "changes": "First."}],
            description_wiki={"block": "0192f3a0-7b1c-7a3e-8c4d-5e6f7a8b9c0d", "source_rev": 3},
            min_store="0.0.13",
            feature=[{"key": "a", "name": "A", "provides": ["places"]}, {"key": "b"}],
        )
        x = build(p)
        root = ET.fromstring(x)
        self.assertEqual(root.get("type"), "desktop-application")
        art = root.find("releases/release/artifacts/artifact")
        self.assertEqual([(s.get("type"), s.text) for s in art.findall("size")], [("download", "123456"), ("installed", "999")])
        rel = root.find("releases/release")
        self.assertEqual(rel.get("date"), "2026-11-12")
        lang = "{http://www.w3.org/XML/1998/namespace}lang"
        self.assertEqual([(d.get(lang), d.findtext("p")) for d in rel.findall("description")], [("en", "Fixed."), ("de", "Behoben.")])  # English first
        old = root.findall("releases/release")[1]
        self.assertEqual((old.get("version"), old.get("date"), old.find("artifacts")), ("0.0.1", "2026-11-01", None))
        self.assertEqual(len(root.findall("description")), 2)
        self.assertEqual(len(root.find("description[@{}='en']".format(lang)).findall("p")), 2)
        self.assertEqual([m.text for m in root.findall("provides/mediatype")], ["text/calendar"])
        c = {v.get("key"): v.text for v in root.findall("custom/value")}
        self.assertEqual(c["fs:provides"], "tasks 1.0")
        self.assertEqual(c["fs:requires"], "store")
        self.assertEqual(c["fs:recommends"], "comments 1.0")
        self.assertEqual(c["fs:features"], "a, b")
        self.assertEqual(c["fs:feature.a.provides"], "places")
        self.assertNotIn("fs:feature.b.provides", c)
        self.assertEqual((c["fs:upstream"], c["fs:source-code"], c["fs:maker"]), ("https://u.org/x", "https://u.org/s.tgz", "M"))
        self.assertEqual(c["fs:upstream-signature"], "ABCD" * 10)
        self.assertEqual((c["fs:description-wiki"], c["fs:description-wiki-source-rev"], c["fs:min-store"]), ("0192f3a0-7b1c-7a3e-8c4d-5e6f7a8b9c0d", "3", "0.0.13"))
        self.assertNotIn("fs:description-wiki-lang", c)  # optional wish, not written when not given
        self.assertEqual(root.find("icon").get("fs-sha256"), hashlib.sha256(local_fetch("x.png")).hexdigest())

    def test_old_entry_gets_no_new_fields(self):  # Gegenprobe: nothing is made up
        old = {k: GOOD[k] for k in ("id", "name", "summary", "repo", "tag", "asset")}
        x = build(old, schema=1)
        for tag in ("<icon", "<screenshots", "<provides", "fs:provides", "fs:requires", "fs:upstream", "fs:features", "fs:description-wiki", "xml:lang", "installed"):
            self.assertNotIn(tag, x, tag)
        self.assertIn('<release version="0.0.2" date="2026-11-12">', x)
        self.assertEqual({v.get("key") for v in ET.fromstring(x).findall("custom/value")}, {"fs:kind", "fs:format", "fs:signature"})

    def test_kind_to_appstream_type(self):
        for kind, typ in (("server", "service"), ("icon-theme", "icon-theme"), ("theme", "addon"), ("program", "desktop-application"), ("frontend", "desktop-application")):
            x = build(with_(kind=kind, requires=["tasks"], min_store="0.0.13"))
            self.assertEqual(ET.fromstring(x).get("type"), typ)
            self.assertEqual(ET.fromstring(x).findtext("custom/value"), kind)

    def test_picture_hash_is_computed_and_checked(self):
        url = RAW + "examples/images/example-program-screenshot.png"
        shot = {"url": url, "license": "CC0-1.0", "source": "own", "caption": "c"}
        real = hashlib.sha256(local_fetch(url)).hexdigest()
        x = build(with_(screenshot=[shot]))
        img = ET.fromstring(x).find("screenshots/screenshot/image")
        self.assertEqual((img.get("fs-sha256"), img.get("fs-license"), img.get("fs-source"), img.text), (real, "CC0-1.0", "own", url))
        self.assertEqual(build(with_(screenshot=[{**shot, "sha256": real}])), x)
        with self.assertRaises(SystemExit) as r:
            build(with_(screenshot=[{**shot, "sha256": "0" * 64}]))
        self.assertIn("does not match", str(r.exception))

    def test_error_page_is_not_a_picture(self):
        with self.assertRaises(SystemExit) as r:
            build(with_(icon="https://x/i.png"), fetch=lambda u, limit=None: b"<html>404</html>")
        self.assertIn("not a PNG icon", str(r.exception))

    def test_download_failure_is_skip_not_error(self):
        def down(_u, _l=None):
            raise gen.Skip("down")
        with self.assertRaises(gen.Skip):
            build(GOOD, fetch=down)

    def test_invalid_package_stops_before_any_network(self):
        with mock.patch.object(gen, "gh", side_effect=AssertionError("network used")):
            gen.CTX.update(schema=2, caps=CAPS)
            with self.assertRaises(SystemExit) as r:
                gen.entry(with_(provides=["tsaks"], kind="nope"))
        self.assertIn("not in the capability list", str(r.exception))
        self.assertIn("kind", str(r.exception))  # both findings in one message

    def test_text_is_escaped(self):
        x = build(with_(summary="a <b> & c", description="x & <y>"))
        self.assertEqual(ET.fromstring(x).findtext("summary"), "a <b> & c")
        self.assertEqual(ET.fromstring(x).findtext("description/p"), "x & <y>")

    def test_check_mode_and_unknown_schema(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            f = pathlib.Path(d, "p.toml")
            f.write_text('schema = 3\n[[package]]\nid="a"\n')
            with mock.patch("sys.argv", ["g", str(f), "--check"]), self.assertRaises(SystemExit) as r:
                gen.main()
            self.assertIn("not known", str(r.exception))
            f.write_text('schema = 2\n[[package]]\nid="a"\nname="A"\nsummary="s"\nrepo="r"\ntag="v0.0.1"\nasset="a"\nprovides=["tsaks"]\n')
            with mock.patch("sys.argv", ["g", str(f), "--check", "--capabilities", str(CAPS_FILE)]), self.assertRaises(SystemExit) as r:
                gen.main()
            self.assertIn("did you mean `tasks`", str(r.exception))
        self.addCleanup(gen.CTX.update, caps_file=None)



class Examples(unittest.TestCase):
    """examples/: the checked-in example packages and the catalog built from them (a golden file)."""

    def setUp(self):
        self.addCleanup(gen.CTX.update, schema=1, caps=None, caps_file=None)

    def test_examples_are_valid_and_the_golden_file_is_current(self):
        data = tomllib.loads((ROOT / "examples/packages.example.toml").read_text())
        self.assertEqual(data["schema"], 2)
        gen.CTX.update(schema=2, caps=CAPS)
        gen.check(data["package"])
        built = wrap("\n".join(build(p) for p in data["package"]))
        golden = (ROOT / "examples/catalog.example.xml").read_text()
        self.assertEqual(golden, built, "run `python3 -I tests/support.py --write-golden` and look at the diff")
        root = ET.fromstring(golden)
        self.assertEqual(root.get("fs-schema"), "2")
        self.assertEqual([c.findtext("id") for c in root.findall("component")], ["example-notes", "example-server", "example-icons"])

    def test_example_pictures_match_their_script(self):
        before = {f.name: f.read_bytes() for f in (ROOT / "examples/images").glob("*.png")}
        self.assertEqual(len(before), 4)
        for d in before.values():
            self.assertTrue(S.image_ok(d))
        self.assertTrue(all(len(d) < 2000 for d in before.values()))


class ReaderContract(unittest.TestCase):
    """A small copy of what the store reads (fs-store-catalog details.rs), applied to the generated XML: if this breaks, the
    store would read the catalog differently."""

    def test_store_would_find_everything(self):
        data = tomllib.loads((ROOT / "examples/packages.example.toml").read_text())
        gen.CTX.update(schema=2, caps=CAPS)
        self.addCleanup(gen.CTX.update, schema=1, caps=None, caps_file=None)
        c = ET.fromstring(build(data["package"][0]))
        custom = {v.get("key"): (v.text or "").strip() for v in c.findall("custom/value")}
        for item in custom["fs:provides"].split(","):  # Capability::parse_list: `name` or `name major.minor`
            self.assertRegex(item.strip(), r"^[a-z0-9._-]+( \d+\.\d+)?$")
        art = c.find("releases/release/artifacts/artifact")
        self.assertEqual(art.find("size[@type='download']").text, "123456")      # the reader takes the artifact's size
        self.assertRegex(c.find("releases/release").get("date"), r"^\d{4}-\d\d-\d\d$")  # millis_of(YYYY-MM-DD)
        icon = c.find("icon")
        self.assertEqual(icon.get("type"), "remote")
        self.assertRegex(icon.get("fs-sha256"), r"^[0-9a-f]{64}$")
        img = c.find("screenshots/screenshot/image")
        self.assertTrue(img.text.startswith("https://") and S.clear_license(img.get("fs-license")) and S.SHA256.match(img.get("fs-sha256")))
        self.assertTrue(c.find("screenshots/screenshot/caption").text)
        self.assertTrue(S.UUID7.match(custom["fs:description-wiki"]))



if __name__ == "__main__":
    unittest.main()
