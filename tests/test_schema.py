"""Tests for catalog format 2 (scripts/catalog_schema.py and the generator): positive, negative and counter-checks, all offline.
Run: python3 -I -m unittest discover -s tests"""
import copy
import hashlib
import importlib.util
import pathlib
import re
import tomllib
import unittest
import xml.etree.ElementTree as ET
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent
CAPS_FILE = ROOT / "tests" / "fixtures" / "capabilities.txt"


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


gen = load("gen_catalog")
S = gen.schema
CAPS = S.parse_capabilities(CAPS_FILE.read_text())
RAW = "https://raw.githubusercontent.com/FreeSynergy/fs-catalog/main/"

GOOD = {
    "id": "fs-x", "name": "X", "summary": "s", "description": "d", "repo": "FreeSynergy/fs-x", "tag": "v0.0.2",
    "asset": "fs-x-{version}-linux-x86_64.tar.gz", "kind": "program", "icon": "https://x/i.png", "provides": ["tasks 1.0"],
}


def problems(p, schema=2, caps=CAPS):
    return [i for i in S.validate(p, caps, schema) if i.error]


def messages(p, **kw):
    return " | ".join(str(i) for i in problems(p, **kw))


def with_(**kw):
    p = copy.deepcopy(GOOD)
    p.update(kw)
    return p


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
            p = with_(kind=k, requires=["tasks"])
            self.assertEqual(problems(p), [], k)
        self.assertIn("kind", messages(with_(kind="Server")))
        self.assertIn("kind", messages(with_(kind="app")))

    def test_required_per_kind(self):
        no = {k: v for k, v in GOOD.items() if k != "provides"}
        self.assertIn("provides", messages({**no, "kind": "server"}))
        self.assertIn("provides", messages({**no, "kind": "program"}))
        self.assertIn("requires", messages({**no, "kind": "frontend"}))
        self.assertEqual(problems({**no, "kind": "theme"}), [])      # counter-check: a theme offers nothing
        self.assertEqual(problems({**no, "kind": "icon-theme"}), [])
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
        self.assertEqual(problems(with_(description_wiki={"block": block, "lang": "en"})), [])
        self.assertEqual(problems(with_(description_wiki={"block": block, "lang": "de", "source_rev": 3})), [])
        self.assertIn("UUIDv7", messages(with_(description_wiki={"block": "0192f3a0-7b1c-4a3e-8c4d-5e6f7a8b9c0d", "lang": "en"})))  # v4
        self.assertIn("UUIDv7", messages(with_(description_wiki={"block": "not-a-uuid", "lang": "en"})))
        self.assertIn("source_rev", messages(with_(description_wiki={"block": block, "lang": "de"})))  # translation without sourceRev
        self.assertIn("lang", messages(with_(description_wiki={"block": block})))
        self.assertIn("source_rev", messages(with_(description_wiki={"block": block, "lang": "de", "source_rev": -1})))

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
        self.assertIn("control", messages(with_(summary="a\x00b")))
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
def release_for(p):
    version = p["tag"].lstrip("v")
    name = p["asset"].format(version=version)
    names = [name, name + ".asc", "SHA256SUMS.txt"]
    assets = [{"name": n, "browser_download_url": f"https://x/{p['id']}/{n}", "size": 123456 if n == name else 10} for n in names]
    return {"tag_name": p["tag"], "draft": False, "published_at": "2026-11-12T08:00:00Z", "assets": assets}


def local_fetch(url):
    if url.startswith(RAW):
        return (ROOT / url[len(RAW):]).read_bytes()
    if url.endswith(".png"):
        return (ROOT / "examples/images/example-program-icon.png").read_bytes()
    return b"<html>404</html>"


def wrap(body):
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<components version="1.0" origin="freesynergy" fs-schema="2" fs-serial="0" fs-expires="0">\n{body}\n</components>\n'


def build(p, fetch=local_fetch, schema=2):
    gen.CTX.update(schema=schema, caps=CAPS, caps_file=None)
    with mock.patch.object(gen, "gh", lambda _path: release_for(p)), mock.patch.object(gen, "sums", lambda r: {a["name"]: "ab" * 32 for a in r["assets"]}), \
            mock.patch.object(gen, "fetch", fetch):
        return gen.entry(p)


class Generator(unittest.TestCase):
    def setUp(self):
        self.addCleanup(gen.CTX.update, schema=1, caps=None, caps_file=None)

    def test_new_fields_come_out(self):
        p = with_(
            description={"en": "Hello.\n\nTwo.", "de": "Hallo."}, installed_size={"0.0.2": 999}, mediatypes=["text/calendar"],
            requires=["store"], recommends=["comments 1.0"], upstream="https://u.org/x", source_code="https://u.org/s.tgz",
            upstream_signature="ABCD" * 10, maker="M",
            history=[{"version": "0.0.2", "changes": {"en": "Fixed.", "de": "Behoben."}}, {"version": "0.0.1", "date": "2026-11-01", "changes": "First."}],
            description_wiki={"block": "0192f3a0-7b1c-7a3e-8c4d-5e6f7a8b9c0d", "lang": "de", "source_rev": 3},
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
        self.assertEqual((c["fs:description-wiki"], c["fs:description-wiki-lang"], c["fs:description-wiki-source-rev"]), ("0192f3a0-7b1c-7a3e-8c4d-5e6f7a8b9c0d", "de", "3"))
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
            x = build(with_(kind=kind, requires=["tasks"]))
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
            build(with_(icon="https://x/i.png"), fetch=lambda u: b"<html>404</html>")
        self.assertIn("not a picture", str(r.exception))

    def test_download_failure_is_skip_not_error(self):
        def down(_):
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
        self.assertEqual(golden, built, "run `python3 -I tests/test_schema.py --write-golden` and look at the diff")
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
    import sys
    if "--write-golden" in sys.argv:
        data = tomllib.loads((ROOT / "examples/packages.example.toml").read_text())
        gen.CTX.update(schema=2, caps=CAPS)
        (ROOT / "examples/catalog.example.xml").write_text(wrap("\n".join(build(p) for p in data["package"])))
        print("written")
    else:
        unittest.main()
