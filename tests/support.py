"""Shared helpers of the schema tests (loaded by the test modules as `import support`)."""
import copy
import hashlib
import importlib.util
import pathlib
import tomllib
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



def release_for(p):
    version = p["tag"].lstrip("v")
    name = p["asset"].format(version=version)
    names = [name, name + ".asc", "SHA256SUMS.txt"]
    assets = [{"name": n, "browser_download_url": f"https://x/{p['id']}/{n}", "size": 123456 if n == name else 10} for n in names]
    return {"tag_name": p["tag"], "draft": False, "published_at": "2026-11-12T08:00:00Z", "assets": assets}


def local_fetch(url, limit=None):
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


PNG = (ROOT / "examples/images/example-program-icon.png").read_bytes()


def refresh_golden():
    data = tomllib.loads((ROOT / "examples/packages.example.toml").read_text())
    gen.CTX.update(schema=2, caps=CAPS)
    (ROOT / "examples/catalog.example.xml").write_text(wrap("\n".join(build(p) for p in data["package"])))
    print("written")


if __name__ == "__main__":  # python3 -I tests/support.py --write-golden
    import sys
    if "--write-golden" in sys.argv:
        refresh_golden()
