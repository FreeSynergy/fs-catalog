import pathlib
import tempfile
import unittest
from unittest import mock

import support

ROOT = support.ROOT
vt = support.load("verify_tags")
gen = support.gen

XML = '<components><component><id>fs-a</id><releases><release version="0.0.2"/></releases></component>' \
      '<component><id>fs-b</id><releases><release version="0.0.9"/></releases></component></components>'


def pk(i, tag):
    return {"id": i, "tag": tag}


class VerifyTagsTest(unittest.TestCase):
    def test_all_present(self):
        self.assertEqual(vt.check(XML, [pk("fs-a", "v0.0.2"), pk("fs-b", "v0.0.9")], set()), ([], []))

    def test_version_of_another_component_does_not_count(self):
        self.assertEqual(vt.check(XML, [pk("fs-a", "v0.0.9")], set())[0], ["fs-a v0.0.9"])

    def test_draft_is_only_a_notice(self):
        self.assertEqual(vt.check(XML, [pk("fs-a", "v0.0.3")], {"fs-a v0.0.3"}), ([], ["fs-a v0.0.3"]))

    def test_incomplete_tag_is_red(self):
        errors, notices = vt.check(XML, [pk("fs-a", "v0.0.3")], {"fs-b v0.0.3"})
        self.assertEqual((errors, notices), (["fs-a v0.0.3"], []))


TOML = '''[[package]]
id = "fs-x"
name = "X"
summary = "s"
repo = "FreeSynergy/fs-x"
tag = "v0.0.2"
asset = "fs-x-{version}-linux-x86_64.tar.gz"
'''


class GenDraftsTest(unittest.TestCase):
    def test_only_a_draft_release_is_listed(self):
        for exc, listed in ((gen.Draft("draft"), True), (gen.Skip("asset missing"), False)):
            with tempfile.TemporaryDirectory() as t:
                d = pathlib.Path(t)
                (d / "scripts").mkdir()
                gen.HERE = t
                (d / "catalog.xml").write_text('<components>\n  <component type="x">\n    <id>fs-x</id>\n    <releases>\n      <release version="0.0.1">\n      </release>\n    </releases>\n  </component>\n</components>\n')
                (d / "p.toml").write_text(TOML)
                with mock.patch.object(gen, "entry", side_effect=exc), mock.patch("sys.argv", ["g", str(d / "p.toml")]):
                    gen.main()
                self.assertEqual((d / "catalog.drafts").read_text(), "fs-x v0.0.2\n" if listed else "")


if __name__ == "__main__":
    unittest.main()
