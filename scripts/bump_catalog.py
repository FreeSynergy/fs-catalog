#!/usr/bin/env python3
"""Raises `tag` in packages.toml to the newest PUBLISHED, COMPLETE release of each program (pull, no cross-repo token).

Complete = SHA256SUMS.txt (+ .asc), every file it lists and the `.asc` of each, and the package's own asset.
Drafts (invisible to the API without write rights anyway), incomplete releases and API trouble are skipped with a
::warning:: - this script never fails a run for them. Never lowers a tag; unchanged state writes nothing.
Exit 0 always; prints `changed` when packages.toml was edited. Read only, via `gh api` (token only lifts the rate limit).
"""
import json
import re
import subprocess
import sys
import tomllib

PATH = sys.argv[1] if len(sys.argv) > 1 else "packages.toml"
TAG = re.compile(r"^v(\d+)\.(\d+)\.(\d+)$")


def ver(tag):
    return tuple(int(x) for x in TAG.match(tag).groups())


def gh(path):
    done = subprocess.run(["gh", "api", path], capture_output=True, text=True, timeout=60)
    if done.returncode != 0:
        raise RuntimeError(done.stderr.strip() or "gh api failed")
    return json.loads(done.stdout)


def complete(p, release):
    """Returns None when the release is complete, else the reason it is not."""
    names = {a["name"]: a for a in release["assets"]}
    if "SHA256SUMS.txt" not in names:
        return "no SHA256SUMS.txt"
    if "SHA256SUMS.txt.asc" not in names:
        return "no SHA256SUMS.txt.asc"
    text = subprocess.run(["curl", "-fsSL", "--max-time", "60", names["SHA256SUMS.txt"]["browser_download_url"]],
                          capture_output=True, text=True).stdout
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
