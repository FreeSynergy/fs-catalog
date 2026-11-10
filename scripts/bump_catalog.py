#!/usr/bin/env python3
"""Raises `tag` in packages.toml to the newest PUBLISHED, COMPLETE release of each program (pull, no cross-repo token).

Complete = SHA256SUMS.txt (+ .asc, cryptographically verified against the pinned project key; only repos under FreeSynergy/), every file it lists and the `.asc` of each, and the package's own asset.
Drafts (invisible to the API without write rights anyway), incomplete releases and API trouble are skipped with a
::warning:: - this script never fails a run for them. Never lowers a tag; unchanged state writes nothing.
Exit 0 always; prints `changed` when packages.toml was edited. Read only, via `gh api` (token only lifts the rate limit).
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import tomllib

PATH = sys.argv[1] if len(sys.argv) > 1 else "packages.toml"
HERE = os.path.dirname(os.path.abspath(__file__))
# The one trust anchor: the project's primary key, the same as in the README, fs-release/release-signing-key.asc and the
# store's built-in key (fs-store-pgp/keys/release-signing-key.asc). The key file next to the catalog must have this fingerprint.
FPR = "16A4A3EE563AEF51FCF0C55DED7B57C4A1904342"
KEY_FILE = os.path.join(HERE, "..", "release-signing-key.asc")
ORG = "FreeSynergy/"
TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")


def ver(tag):
    return tuple(int(x) for x in TAG.match(tag).groups())


def gh(path):
    done = subprocess.run(["gh", "api", path], capture_output=True, text=True, timeout=60)
    if done.returncode != 0:
        raise RuntimeError(done.stderr.strip() or "gh api failed")
    return json.loads(done.stdout)


def fetch(url):
    return subprocess.run(["curl", "-fsSL", "--max-time", "60", url], capture_output=True, check=True).stdout


def signed_by_project(data, sig):
    """True when `sig` is a good detached signature over `data` by a key of FPR (primary or one of its subkeys)."""
    with tempfile.TemporaryDirectory() as home:
        os.chmod(home, 0o700)
        env = {**os.environ, "GNUPGHOME": home}
        shown = subprocess.run(["gpg", "--batch", "--with-colons", "--show-keys", KEY_FILE], capture_output=True, text=True, env=env).stdout
        primary = next((l.split(":")[9] for l in shown.splitlines() if l.startswith("fpr:")), "")
        if primary != FPR:
            return False  # the key file in this repo is not the pinned key
        subprocess.run(["gpg", "--batch", "--import", KEY_FILE], capture_output=True, env=env, check=True)
        for name, blob in (("data", data), ("data.asc", sig)):
            with open(os.path.join(home, name), "wb") as f:
                f.write(blob)
        done = subprocess.run(["gpg", "--batch", "--status-fd", "1", "--verify", os.path.join(home, "data.asc"), os.path.join(home, "data")],
                              capture_output=True, text=True, env=env)
        status = done.stdout.splitlines()
        bad = any(l.startswith(("[GNUPG:] EXPKEYSIG", "[GNUPG:] REVKEYSIG", "[GNUPG:] BADSIG", "[GNUPG:] ERRSIG")) for l in status)
        good = any(l.startswith("[GNUPG:] GOODSIG") for l in status)
        valid = [l.split() for l in status if l.startswith("[GNUPG:] VALIDSIG")]
        return done.returncode == 0 and good and not bad and any(v[-1] == FPR for v in valid)


def complete(p, release):
    """Returns None when the release is complete, else the reason it is not."""
    names = {a["name"]: a for a in release["assets"]}
    if "SHA256SUMS.txt" not in names:
        return "no SHA256SUMS.txt"
    if "SHA256SUMS.txt.asc" not in names:
        return "no SHA256SUMS.txt.asc"
    raw = fetch(names["SHA256SUMS.txt"]["browser_download_url"])
    # Existence of an .asc proves nothing: check the signature against the project key before trusting a single line.
    if not signed_by_project(raw, fetch(names["SHA256SUMS.txt.asc"]["browser_download_url"])):
        return "SHA256SUMS.txt.asc is not a valid signature by the project key"
    text = raw.decode("utf-8", "replace")
    listed = [line.split(None, 1)[1].strip().lstrip("*") for line in text.splitlines() if len(line.split(None, 1)) == 2]
    if not listed:
        return "SHA256SUMS.txt is empty"
    wanted = p["asset"].format(version=release["tag_name"].lstrip("v"))
    if wanted not in listed:
        return f"{wanted} not in SHA256SUMS.txt"
    for f in listed:
        if f not in names:
            return f"{f} is listed but not attached"
        if f + ".asc" not in names:
            return f"{f}.asc is missing"
    return None


def newest(p):
    if not p["repo"].startswith(ORG):
        raise RuntimeError(f"{p['repo']} is not under {ORG} - ignored")
    current = ver(p["tag"])
    releases = gh(f"repos/{p['repo']}/releases?per_page=30")
    cands = sorted((r for r in releases if not r.get("draft") and TAG.match(r["tag_name"]) and ver(r["tag_name"]) > current),
                   key=lambda r: ver(r["tag_name"]), reverse=True)
    for r in cands:
        why = complete(p, r)
        if why is None:
            return r["tag_name"]
        print(f"::warning title=catalog: {p['id']} {r['tag_name']} not taken::{why}; waiting for it to be complete")
    return None


def main():
    text = open(PATH, encoding="utf-8").read()
    changed = False
    for p in tomllib.loads(text)["package"]:  # one program after the other: few API calls, easy on the rate limit
        try:
            tag = newest(p)
        except Exception as why:  # network, rate limit, odd data: try again in 15 minutes
            print(f"::warning title=catalog: {p['id']} skipped::{why}")
            continue
        if tag is None:
            continue
        blocks = re.split(r"(?m)^(?=\[\[package\]\])", text)
        for i, b in enumerate(blocks):
            if re.search(rf'(?m)^id\s*=\s*"{re.escape(p["id"])}"\s*$', b):
                blocks[i] = re.sub(r'(?m)^(tag\s*=\s*)"[^"]*"', lambda m: f'{m.group(1)}"{tag}"', b, count=1)
        text = "".join(blocks)
        changed = True
        print(f"{p['id']}: {p['tag']} -> {tag}")
    if changed:
        open(PATH, "w", encoding="utf-8").write(text)
        print("changed")


if __name__ == "__main__":
    main()
