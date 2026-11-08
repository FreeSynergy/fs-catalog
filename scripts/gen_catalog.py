#!/usr/bin/env python3
"""Writes catalog.xml (AppStream collection) from packages.toml and the public GitHub releases.

Pattern: Builder. No network except `gh api`; sha256 comes from the release's SHA256SUMS.txt, the signature of each
file is the `.asc` next to it. The catalog itself is signed by CI (see .github/workflows/sign.yml), never here.
"""
import json
import subprocess
import sys
import time
import tomllib
from xml.sax.saxutils import escape, quoteattr

HERE = __file__.rsplit("/scripts/", 1)[0] if "/scripts/" in __file__ else "."


def gh(path):
    out = subprocess.run(["gh", "api", path], check=True, capture_output=True, text=True).stdout
    return json.loads(out)


def sums(release):
    asset = next((a for a in release["assets"] if a["name"] == "SHA256SUMS.txt"), None)
    if asset is None:
        sys.exit(f"{release['tag_name']}: no SHA256SUMS.txt")
    text = subprocess.run(["curl", "-fsSL", asset["browser_download_url"]], check=True, capture_output=True, text=True).stdout
    return {line.split()[1].lstrip("*"): line.split()[0] for line in text.splitlines() if line.strip()}


def entry(p):
    release = gh(f"repos/{p['repo']}/releases/tags/{p['tag']}")
    if release.get("draft"):
        sys.exit(f"{p['repo']} {p['tag']} is still a draft; publish it first (drafts are not downloadable)")
    version = p["tag"].lstrip("v")
    wanted = p["asset"].format(version=version)
    asset = next((a for a in release["assets"] if a["name"] == wanted), None)
    if asset is None:
        sys.exit(f"{p['repo']} {p['tag']}: asset {wanted} not found")
    sig = next((a for a in release["assets"] if a["name"] == wanted + ".asc"), None)
    if sig is None:
        sys.exit(f"{wanted}: no .asc signature")
    sha = sums(release).get(wanted)
    if sha is None:
        sys.exit(f"{wanted}: not in SHA256SUMS.txt")
    q = quoteattr
    return f"""  <component type="desktop-application">
    <id>{escape(p['id'])}</id>
    <name>{escape(p['name'])}</name>
    <summary>{escape(p['summary'])}</summary>
    <releases>
      <release version={q(version)}>
        <artifacts>
          <artifact type="binary" platform="x86_64-linux-gnu">
            <location>{escape(asset['browser_download_url'])}</location>
            <checksum type="sha256">{sha}</checksum>
          </artifact>
        </artifacts>
      </release>
    </releases>
    <custom>
      <value key="fs:kind">{escape(p.get('kind', 'program'))}</value>
      <value key="fs:format">tar.gz</value>
      <value key="fs:signature">{escape(sig['browser_download_url'])}</value>
    </custom>
  </component>"""


def main():
    with open(sys.argv[1] if len(sys.argv) > 1 else f"{HERE}/packages.toml", "rb") as f:
        packages = tomllib.load(f)["package"]
    body = "\n".join(entry(p) for p in packages)
    # Freshness for the store: the serial only goes up (rollback), the catalog goes stale after 21 days (freeze).
    # CI regenerates and signs every week, so a mirror that keeps serving an old copy is refused after three weeks.
    serial = int(time.time())
    expires = serial + 21 * 24 * 3600
    with open(f"{HERE}/catalog.xml", "w") as f:
        f.write(f'<?xml version="1.0" encoding="UTF-8"?>\n<components version="1.0" origin="freesynergy" fs-serial="{serial}" fs-expires="{expires}">\n{body}\n</components>\n')


if __name__ == "__main__":
    main()
