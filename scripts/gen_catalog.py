#!/usr/bin/env python3
"""Writes catalog.xml (AppStream collection) from packages.toml and the public GitHub releases.

Pattern: Builder. No network except `gh api`; sha256 comes from the release's SHA256SUMS.txt, the signature of each
file is the `.asc` next to it. The catalog itself is signed by CI (see .github/workflows/sign.yml), never here.
"""
import hashlib
import json
import re
import subprocess
import sys
import time
import tomllib
from xml.sax.saxutils import escape, quoteattr

HERE = __file__.rsplit("/scripts/", 1)[0] if "/scripts/" in __file__ else "."


class Skip(Exception):
    """This package cannot be listed right now (draft, missing release or file). The run goes on without it."""


# The catalog is valid for this long; CI renews it twice a week (sign.yml), so several runs may fail before it lapses.
VALID_DAYS = 35


def gh(path):
    done = subprocess.run(["gh", "api", path], capture_output=True, text=True)
    if done.returncode != 0:
        if "404" in done.stderr or "Not Found" in done.stderr:
            raise Skip(f"{path} does not exist (draft or unknown tag: drafts are invisible to the API token)")
        sys.exit(f"gh api {path} failed: {done.stderr.strip()}")
    return json.loads(done.stdout)


def sums(release):
    asset = next((a for a in release["assets"] if a["name"] == "SHA256SUMS.txt"), None)
    if asset is None:
        raise Skip(f"{release['tag_name']}: no SHA256SUMS.txt")
    text = subprocess.run(["curl", "-fsSL", asset["browser_download_url"]], check=True, capture_output=True, text=True).stdout
    return {line.split()[1].lstrip("*"): line.split()[0] for line in text.splitlines() if line.strip()}


# (file name ending, fs-format, platform): what the store's catalog reader (fs-store-catalog) matches by arch and system.
NATIVE = [
    (".x86_64.rpm", "rpm", "x86_64-linux-gnu"),
    (".aarch64.rpm", "rpm", "aarch64-linux-gnu"),
    ("_amd64.deb", "deb", "x86_64-linux-gnu"),
    ("_arm64.deb", "deb", "aarch64-linux-gnu"),
    ("-windows-x86_64-setup.exe", "exe", "x86_64-windows-msvc"),
]


def entry(p):
    release = gh(f"repos/{p['repo']}/releases/tags/{p['tag']}")
    if release.get("draft"):
        raise Skip(f"{p['repo']} {p['tag']} is still a draft; publish it first (drafts are not downloadable)")
    version = p["tag"].lstrip("v")
    wanted = p["asset"].format(version=version)
    asset = next((a for a in release["assets"] if a["name"] == wanted), None)
    if asset is None:
        raise Skip(f"{p['repo']} {p['tag']}: asset {wanted} not found")
    sig = next((a for a in release["assets"] if a["name"] == wanted + ".asc"), None)
    if sig is None:
        raise Skip(f"{wanted}: no .asc signature")
    sha = sums(release).get(wanted)
    if sha is None:
        raise Skip(f"{wanted}: not in SHA256SUMS.txt")
    q = quoteattr
    description_line = f"\n    <description><p>{escape(p['description'])}</p></description>" if p.get('description') else ""
    # optional PNG icon: `icon = "https://..."` in packages.toml; its SHA-256 goes into the signed catalog
    icon_line = ""
    if p.get("icon"):
        data = subprocess.run(["curl", "-fsSL", p["icon"]], check=True, capture_output=True).stdout
        icon_line = f"\n    <icon type=\"remote\" fs-sha256=\"{hashlib.sha256(data).hexdigest()}\">{escape(p['icon'])}</icon>"
    # every native package of the release (rpm, deb, Windows setup.exe) per machine, each with its own signature: the
    # store takes the one of its own system. A file without a `.asc` or without a line in SHA256SUMS.txt is left out.
    native_lines = ""
    sha_by_name = sums(release)
    names = {x["name"] for x in release["assets"]}
    for a in sorted(release["assets"], key=lambda a: a["name"]):
        n = a["name"]
        for suffix, fmt, platform in NATIVE:
            if n.endswith(suffix) and (n + ".asc") in names and n in sha_by_name:
                sig_url = next(x["browser_download_url"] for x in release["assets"] if x["name"] == n + ".asc")
                native_lines += f"""
          <artifact type="binary" platform="{platform}" fs-format="{fmt}" fs-signature={q(sig_url)}>
            <location>{escape(a['browser_download_url'])}</location>
            <checksum type="sha256">{sha_by_name[n]}</checksum>
          </artifact>"""
    return f"""  <component type="desktop-application">
    <id>{escape(p['id'])}</id>
    <name>{escape(p['name'])}</name>
    <summary>{escape(p['summary'])}</summary>{description_line}
    <url type="homepage">https://github.com/{escape(p['repo'])}</url>{icon_line}
    <releases>
      <release version={q(version)}>
        <artifacts>
          <artifact type="binary" platform="x86_64-linux-gnu">
            <location>{escape(asset['browser_download_url'])}</location>
            <checksum type="sha256">{sha}</checksum>
          </artifact>{native_lines}
        </artifacts>
      </release>
    </releases>
    <custom>
      <value key="fs:kind">{escape(p.get('kind', 'program'))}</value>
      <value key="fs:format">tar.gz</value>
      <value key="fs:signature">{escape(sig['browser_download_url'])}</value>
    </custom>
  </component>"""


def previous(component_id):
    """The component block of this id from the catalog.xml that is already signed, or None."""
    try:
        with open(f"{HERE}/catalog.xml", encoding="utf-8") as f:
            text = f.read()
    except OSError:
        return None
    for block in re.findall(r"  <component .*?</component>", text, re.S):
        if f"<id>{escape(component_id)}</id>" in block:
            return block
    return None


def main():
    with open(sys.argv[1] if len(sys.argv) > 1 else f"{HERE}/packages.toml", "rb") as f:
        packages = tomllib.load(f)["package"]
    blocks, skipped = [], 0
    for p in packages:
        try:
            blocks.append(entry(p))
        except Skip as why:
            # A NEW tag that is not available yet (still a draft, files missing) is skipped. A tag the last signed catalog
            # already offered that has now vanished (release deleted or withdrawn) is an error: stay red, look at it.
            old = previous(p["id"])
            if old and f"<release version={quoteattr(p['tag'].lstrip('v'))}" in old:
                sys.exit(f"{p['id']} {p['tag']} was in the signed catalog but is gone now: {why}")
            skipped += 1
            # Keep what the last signed catalog said (an older version is better than a vanished program), and say so.
            if old:
                blocks.append(old)
            print(f"::warning title=catalog: {p['id']} skipped::{why}; " + ("kept the entry of the last signed catalog" if old else "no earlier entry, package left out"))
    if not blocks:
        sys.exit("no package could be listed - not writing an empty catalog")
    body = "\n".join(blocks)
    if skipped:
        print(f"{skipped} of {len(packages)} packages skipped (see warnings)")
    # Freshness for the store: the serial only goes up (rollback), the catalog goes stale after VALID_DAYS (freeze).
    # CI regenerates and signs twice a week, so a mirror that keeps serving an old copy is refused after five weeks.
    serial = int(time.time())
    expires = serial + VALID_DAYS * 24 * 3600
    with open(f"{HERE}/catalog.xml", "w") as f:
        f.write(f'<?xml version="1.0" encoding="UTF-8"?>\n<components version="1.0" origin="freesynergy" fs-serial="{serial}" fs-expires="{expires}">\n{body}\n</components>\n')


if __name__ == "__main__":
    main()
