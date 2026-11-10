"""Tests for scripts/bump_catalog.py and the skip logic of scripts/gen_catalog.py. Run: python3 -I -m unittest discover -s tests"""
import importlib.util
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parent.parent


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


bump = load("bump_catalog")
gen = load("gen_catalog")

TOML = '''[[package]]
id = "fs-x"
name = "X"
summary = "s"
repo = "FreeSynergy/fs-x"
tag = "v0.0.2"
asset = "fs-x-{version}-linux-x86_64.tar.gz"
'''
PKG = {"id": "fs-x", "repo": "FreeSynergy/fs-x", "tag": "v0.0.2", "asset": "fs-x-{version}-linux-x86_64.tar.gz"}


def release(tag, draft=False, extra=()):
    names = [f"fs-x-{tag[1:]}-linux-x86_64.tar.gz", f"fs-x-{tag[1:]}-linux-x86_64.tar.gz.asc", "SHA256SUMS.txt", "SHA256SUMS.txt.asc", *extra]
    return {"tag_name": tag, "draft": draft, "assets": [{"name": n, "browser_download_url": f"https://x/{tag}/{n}"} for n in names]}


def sums(tag):
    return f"{'a' * 64}  fs-x-{tag[1:]}-linux-x86_64.tar.gz\n".encode()


class BumpTest(unittest.TestCase):
    def run_bump(self, releases, sig_ok=True, toml=TOML):
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d)
        path = os.path.join(d, "packages.toml")
        pathlib.Path(path).write_text(toml)
        by_tag = {r["tag_name"]: r for r in releases}

        def fetch(url):
            tag = url.split("/")[3]
            return sums(tag) if url.endswith("SHA256SUMS.txt") else b"sig"

        with mock.patch.object(bump, "PATH", path), mock.patch.object(bump, "gh", lambda _p: releases), \
                mock.patch.object(bump, "fetch", fetch), mock.patch.object(bump, "signed_by_project", lambda *_: sig_ok):
            bump.main()
        return pathlib.Path(path).read_text(), by_tag

    def test_takes_highest_complete(self):
        text, _ = self.run_bump([release("v0.0.3"), release("v0.0.5"), release("v0.0.4")])
        self.assertIn('tag = "v0.0.5"', text)

    def test_ignores_draft(self):
        text, _ = self.run_bump([release("v0.0.9", draft=True), release("v0.0.3")])
        self.assertIn('tag = "v0.0.3"', text)

    def test_never_older_and_idempotent(self):
        for rels in ([release("v0.0.1")], [release("v0.0.2")], []):
            text, _ = self.run_bump(rels)
            self.assertEqual(text, TOML)

    def test_incomplete_release_skipped_falls_back(self):
        broken = release("v0.0.4")
        broken["assets"] = [a for a in broken["assets"] if a["name"] != "SHA256SUMS.txt.asc"]
        text, _ = self.run_bump([broken, release("v0.0.3")])
        self.assertIn('tag = "v0.0.3"', text)

    def test_package_file_missing_asc(self):
        rel = release("v0.0.4")
        rel["assets"] = [a for a in rel["assets"] if a["name"] != "fs-x-0.0.4-linux-x86_64.tar.gz.asc"]
        with mock.patch.object(bump, "fetch", lambda url: sums("v0.0.4") if url.endswith("SHA256SUMS.txt") else b"sig"), \
                mock.patch.object(bump, "signed_by_project", lambda *_: True):
            self.assertIn(".asc is missing", bump.complete(PKG, rel))

    def test_bad_signature_not_taken(self):
        text, _ = self.run_bump([release("v0.0.3")], sig_ok=False)
        self.assertEqual(text, TOML)

    def test_foreign_repo_ignored(self):
        evil = TOML.replace("FreeSynergy/fs-x", "someone/fs-x")
        text, _ = self.run_bump([release("v0.0.9")], toml=evil)
        self.assertEqual(text, evil)


@unittest.skipUnless(shutil.which("gpg"), "gpg missing")
class SignatureTest(unittest.TestCase):
    def test_real_signature_wrong_key_is_refused(self):
        with tempfile.TemporaryDirectory() as home:
            os.chmod(home, 0o700)
            env = {**os.environ, "GNUPGHOME": home}
            subprocess.run(["gpg", "--batch", "--passphrase", "", "--quick-gen-key", "Test <t@example.org>", "ed25519", "sign", "never"],
                           env=env, check=True, capture_output=True)
            data = pathlib.Path(home, "d")
            data.write_bytes(b"hello")
            subprocess.run(["gpg", "--batch", "--armor", "--detach-sign", str(data)], env=env, check=True, capture_output=True)
            sig = pathlib.Path(home, "d.asc").read_bytes()
        # signed by a key that is not the pinned project key
        self.assertFalse(bump.signed_by_project(b"hello", sig))

    def test_key_file_has_the_pinned_fingerprint(self):
        out = subprocess.run(["gpg", "--batch", "--with-colons", "--show-keys", bump.KEY_FILE], capture_output=True, text=True).stdout
        self.assertIn(bump.FPR, out)


class GenSkipTest(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.d)
        (pathlib.Path(self.d) / "scripts").mkdir()
        gen.HERE = self.d

    def write(self, tag):
        pathlib.Path(self.d, "catalog.xml").write_text(
            f'<components>\n  <component type="x">\n    <id>fs-x</id>\n    <releases>\n      <release version="{tag}">\n      </release>\n    </releases>\n  </component>\n</components>\n')

    def test_previous_found(self):
        self.write("0.0.2")
        self.assertIn("<id>fs-x</id>", gen.previous("fs-x"))
        self.assertIsNone(gen.previous("fs-y"))

    def run_main(self, tag):
        pathlib.Path(self.d, "p.toml").write_text(TOML.replace("v0.0.2", tag))
        with mock.patch.object(gen, "entry", side_effect=gen.Skip("gone")), mock.patch("sys.argv", ["g", str(pathlib.Path(self.d, "p.toml"))]):
            gen.main()

    def test_new_unavailable_tag_is_skipped_keeps_previous(self):
        self.write("0.0.2")
        self.run_main("v0.0.3")  # would be "no package could be listed" without the kept entry
        self.assertIn('<release version="0.0.2">', pathlib.Path(self.d, "catalog.xml").read_text())

    def test_vanished_tag_is_an_error(self):
        self.write("0.0.2")
        with self.assertRaises(SystemExit) as r:
            self.run_main("v0.0.2")
        self.assertIn("was in the signed catalog", str(r.exception))


if __name__ == "__main__":
    unittest.main()
