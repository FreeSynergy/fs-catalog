"""Tests for catalog format 2, part 3: downloads, picture files, transient failures, capability handling."""
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

class Hardening(unittest.TestCase):
    def setUp(self):
        self.addCleanup(gen.CTX.update, schema=1, caps=None, caps_file=None, checked=False)

    def test_magic_bytes_are_strict(self):
        self.assertTrue(S.image_ok(PNG) and S.icon_ok(PNG))
        self.assertTrue(S.image_ok(b"\xff\xd8\xff\xe0" + b"0" * 20))
        self.assertTrue(S.image_ok(b"RIFF\x10\x00\x00\x00WEBPVP8 "))
        self.assertFalse(S.image_ok(b"RIFF\x10\x00\x00\x00WAVEfmt "))   # RIFF without WEBP (a WAV, an AVI)
        self.assertFalse(S.image_ok(b"RIFF"))
        for bad in (b"<svg xmlns='x'/>", b"<?xml version='1.0'?><svg/>", b"<html>", b"GIF89a", b""):
            self.assertFalse(S.image_ok(bad), bad)

    def test_icons_are_png_only_up_to_1_mib(self):
        self.assertFalse(S.icon_ok(b"\xff\xd8\xff\xe0" + b"0" * 20))      # JPEG is a picture, not an icon
        self.assertFalse(S.icon_ok(b"RIFF\x10\x00\x00\x00WEBPVP8 "))
        self.assertFalse(S.icon_ok(b"<svg xmlns='http://www.w3.org/2000/svg'/>"))
        self.assertTrue(S.icon_ok(PNG + b"0" * (S.ICON_LIMIT - len(PNG))))
        self.assertFalse(S.icon_ok(PNG + b"0" * (S.ICON_LIMIT - len(PNG) + 1)))
        gen.CTX.update(schema=2, caps=CAPS)
        with self.assertRaises(SystemExit) as r:
            build(with_(icon="https://x/i.svg"), fetch=lambda u, limit=None: b"<svg xmlns='x'/>")
        self.assertIn("SVG is not accepted", str(r.exception))
        with self.assertRaises(SystemExit):  # a JPEG as icon
            build(with_(icon="https://x/i.jpg"), fetch=lambda u, limit=None: b"\xff\xd8\xff\xe0" + b"0" * 20)
        # but a JPEG is fine as a screenshot (hash computed)
        shot = {"url": "https://x/a.jpg", "license": "CC0-1.0", "source": "own", "caption": "c"}
        self.assertIn("<screenshots>", build(with_(screenshot=[shot]), fetch=lambda u, limit=None: PNG if u.endswith("i.png") else b"\xff\xd8\xff\xe0" + b"0" * 20))

    def test_fetch_uses_https_only_and_a_size_limit(self):
        calls = []
        done = mock.Mock(returncode=0, stdout=b"x")
        with mock.patch.object(gen.subprocess, "run", lambda args, **k: calls.append(args) or done), mock.patch.object(gen.net, "_public_host", lambda u: True):
            gen.fetch("https://e.org/a.png", 123)
        a = calls[0]
        self.assertEqual(a[a.index("--proto") + 1], "=https")
        self.assertEqual(a[a.index("--proto-redir") + 1], "=https")
        self.assertEqual(a[a.index("--max-filesize") + 1], "123")
        self.assertIn("--max-redirs", a)

    def test_fetch_size_exceeded_is_an_error_not_transient(self):
        with mock.patch.object(gen.subprocess, "run", lambda *a, **k: mock.Mock(returncode=63, stdout=b"")), mock.patch.object(gen.net, "_public_host", lambda u: True):
            with self.assertRaises(SystemExit):
                gen.fetch("https://e.org/a.png", 10)
        with mock.patch.object(gen.subprocess, "run", lambda *a, **k: mock.Mock(returncode=7, stdout=b"")), mock.patch.object(gen.net, "_public_host", lambda u: True):
            with self.assertRaises(gen.Transient):
                gen.fetch("https://e.org/a.png", 10)

    def test_internal_hosts_are_refused(self):
        for host in ("127.0.0.1", "10.1.2.3", "192.168.0.5", "169.254.169.254", "[::1]", "localhost"):
            self.assertFalse(gen.net._public_host(f"https://{host}/a.png"), host)
        with mock.patch.object(gen.subprocess, "run", side_effect=AssertionError("curl called")):
            with self.assertRaises(SystemExit):
                gen.fetch("https://127.0.0.1/a.png")

    def test_transient_download_never_stops_the_run(self):
        import tempfile, io, contextlib
        old = '  <component type="x">\n    <id>fs-x</id>\n    <releases>\n      <release version="0.0.2">\n      </release>\n    </releases>\n  </component>'
        with tempfile.TemporaryDirectory() as d:
            (pathlib.Path(d) / "catalog.xml").write_text(f"<components>\n{old}\n</components>\n")
            (pathlib.Path(d) / "p.toml").write_text('[[package]]\nid="fs-x"\nname="X"\nsummary="s"\nrepo="FreeSynergy/fs-x"\ntag="v0.0.2"\nasset="a"\nicon="https://x/i.png"\n')
            def down(_u, _l=None):
                raise gen.Transient("net down")
            with mock.patch.object(gen, "HERE", d), mock.patch.object(gen, "gh", lambda _p: release_for({"id": "fs-x", "tag": "v0.0.2", "asset": "a"})), \
                    mock.patch.object(gen, "sums", lambda r: {"a": "ab" * 32}), mock.patch.object(gen, "fetch", down), \
                    mock.patch("sys.argv", ["g", str(pathlib.Path(d, "p.toml"))]), contextlib.redirect_stdout(io.StringIO()) as out:
                gen.main()   # the version IS in the signed catalog; still no exit, no "gone now"
            self.assertIn("kept the entry of the last signed catalog", out.getvalue())
            self.assertNotIn("gone now", out.getvalue())
            self.assertIn("<id>fs-x</id>", (pathlib.Path(d) / "catalog.xml").read_text())

    def test_wrong_capability_names_are_only_warnings_in_schema_1(self):
        p = with_(provides=["tsaks"])
        self.assertEqual(problems(p, schema=1), [])
        self.assertTrue(any("capability list" in str(i) for i in S.validate(p, CAPS, 1)))
        self.assertIn("capability list", messages(p, schema=2))   # counter-check

    def test_unreadable_capability_list_is_a_warning_in_schema_1_and_an_error_in_2(self):
        import io, contextlib
        gen.CTX.update(caps=None, caps_file=None, checked=False)
        bad = mock.Mock(returncode=1, stdout="", stderr="no token")
        with mock.patch.object(gen.subprocess, "run", lambda *a, **k: bad), mock.patch.dict(gen.os.environ, {}, clear=False):
            gen.os.environ.pop("FS_CAPABILITIES_FILE", None)
            gen.CTX.update(schema=1)
            with contextlib.redirect_stdout(io.StringIO()) as out:
                gen.check([with_(provides=["tasks"])])
            self.assertIn("not checked", out.getvalue())
            gen.CTX.update(schema=2, caps=None)
            with self.assertRaises(SystemExit):
                gen.check([with_(provides=["tasks"])])
        # and no list is read at all when no capability is named
        with mock.patch.object(gen.subprocess, "run", side_effect=AssertionError("gh called")):
            gen.CTX.update(schema=1, caps=None)
            gen.check([{k: GOOD[k] for k in ("id", "name", "summary", "repo", "tag", "asset")}])

    def test_warnings_are_printed_once(self):
        import io, contextlib
        old = {k: GOOD[k] for k in ("id", "name", "summary", "repo", "tag", "asset")}
        gen.CTX.update(schema=1, caps=None, checked=True)  # as after main's check
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            build(old, schema=1)
        self.assertEqual(buf.getvalue(), "")
        gen.CTX.update(checked=False)



if __name__ == "__main__":
    unittest.main()
