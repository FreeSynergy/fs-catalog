#!/usr/bin/env python3
"""Writes catalog.xml (AppStream collection) from packages.toml and the public GitHub releases.

Pattern: Builder. No network except `gh api`; sha256 comes from the release's SHA256SUMS.txt, the signature of each
file is the `.asc` next to it. The catalog itself is signed by CI (see .github/workflows/sign.yml), never here.
"""
import hashlib
import importlib.util
import ipaddress
import json
import os
import re
import socket
import subprocess
import sys
import time
import tomllib
import urllib.parse
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape, quoteattr

HERE = __file__.rsplit("/scripts/", 1)[0] if "/scripts/" in __file__ else "."


def _load_schema():
    # by path, not by `import`: `python3 -I` and importlib loading do not have scripts/ on the module path
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "catalog_schema.py")
    spec = importlib.util.spec_from_file_location("catalog_schema", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


schema = _load_schema()

# Settings of this run (set by main; defaults let `entry` be called alone, as the tests do).
CTX = {"schema": 1, "caps": None, "caps_file": None, "caps_ref": "v0.0.19"}


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


class Transient(Skip):
    """A download failed (network, server): nothing is wrong with the data. Never stops bump or sign (see `main`)."""


def _public_host(url):
    """False when the host of `url` resolves to a loopback, private, link-local or otherwise internal address."""
    host = urllib.parse.urlsplit(url).hostname or ""
    try:
        found = {a[4][0] for a in socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)}
    except OSError:
        return True  # cannot resolve now: curl fails the same way and that is reported as a transient failure
    return all(ipaddress.ip_address(a.split("%")[0]).is_global for a in found)


def fetch(url, limit=schema.SCREENSHOT_LIMIT):
    """Bytes of a public file (icon, picture): https only (also after redirects), at most `limit` bytes, no internal hosts.
    A failed download is `Transient` (try again next run), never a half entry; a file over the limit is an error."""
    if not _public_host(url):
        sys.exit(f"{url}: the host is a loopback or private address; only public https addresses are fetched")
    done = subprocess.run(
        ["curl", "-fsSL", "--proto", "=https", "--proto-redir", "=https", "--max-redirs", "3", "--max-time", "60", "--max-filesize", str(limit), url],
        capture_output=True)
    if done.returncode == 63:  # CURLE_FILESIZE_EXCEEDED
        sys.exit(f"{url}: larger than {limit} bytes")
    if done.returncode != 0:
        raise Transient(f"{url}: could not be downloaded (curl exit {done.returncode})")
    if len(done.stdout) > limit:
        sys.exit(f"{url}: larger than {limit} bytes")
    return done.stdout


class CapabilityListError(Exception):
    """The capability list could not be read."""


def capabilities():
    """The capability list of fs-interfaces (ADR 0068): ONE list, read from there, never copied here. A local file
    (`--capabilities FILE` or $FS_CAPABILITIES_FILE) is for offline runs and tests; otherwise the pinned tag is read with `gh api`."""
    if CTX["caps"] is None:
        path = CTX["caps_file"] or os.environ.get("FS_CAPABILITIES_FILE")
        if path:
            with open(path, encoding="utf-8") as f:
                text = f.read()
        else:
            done = subprocess.run(
                ["gh", "api", "-H", "Accept: application/vnd.github.raw", f"repos/FreeSynergy/fs-interfaces/contents/schema/capabilities.txt?ref={CTX['caps_ref']}"],
                capture_output=True, text=True)
            if done.returncode != 0:
                raise CapabilityListError(f"cannot read the capability list of fs-interfaces {CTX['caps_ref']}: {done.stderr.strip() or 'gh api failed'}")
            text = done.stdout
        CTX["caps"] = schema.parse_capabilities(text)
        if not CTX["caps"]:
            CTX["caps"] = None
            raise CapabilityListError("the capability list is empty or not in the form `key | name | status | text`")
    return CTX["caps"]


def check(packages):
    """Validates every package, reports ALL findings at once, stops on errors. Warnings go out as workflow warnings."""
    issues = []
    for p in packages:
        caps = None
        if schema.uses_capabilities(p):
            try:
                caps = capabilities()
            except CapabilityListError as why:
                # format 2 must check the names; for format 1 a failing read (no token, network) is a warning, never a stopped run
                if CTX["schema"] >= 2:
                    sys.exit(str(why))
                print(f"::warning title=catalog: capability names not checked::{why}")
        issues += schema.validate(p, caps, CTX["schema"])
    for i in issues:
        if not i.error:
            print(f"::warning title=catalog: {i.package}::{i.field}: {i.message}")
    errors = [str(i) for i in issues if i.error]
    if errors:
        sys.exit("packages.toml is not valid:\n  " + "\n  ".join(errors))


# (file name ending, fs-format, platform): what the store's catalog reader (fs-store-catalog) matches by arch and system.
NATIVE = [
    (".x86_64.rpm", "rpm", "x86_64-linux-gnu"),
    (".aarch64.rpm", "rpm", "aarch64-linux-gnu"),
    ("_amd64.deb", "deb", "x86_64-linux-gnu"),
    ("_arm64.deb", "deb", "aarch64-linux-gnu"),
    ("-windows-x86_64-setup.exe", "exe", "x86_64-windows-msvc"),
]


def entry(p):
    if not CTX.get("checked"):  # main has already checked (and warned) for every package
        check([p])
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
    sha_by_name = sums(release)
    sha = sha_by_name.get(wanted)
    if sha is None:
        raise Skip(f"{wanted}: not in SHA256SUMS.txt")
    q = quoteattr
    kind = p.get("kind", "program")
    # optional PNG icon: `icon = "https://..."` in packages.toml; its SHA-256 goes into the signed catalog
    icon_line = ""
    if p.get("icon"):
        data = picture(p["id"], "icon", p["icon"], p.get("icon_sha256"), icon=True)
        icon_line = f"\n    <icon type=\"remote\" fs-sha256=\"{hashlib.sha256(data).hexdigest()}\">{escape(p['icon'])}</icon>"
    shots = p.get("screenshot", [])
    hashes = [hashlib.sha256(picture(p["id"], f"screenshot[{i}]", s["url"], s.get("sha256"))).hexdigest() for i, s in enumerate(shots)]
    mediatypes = "".join(f"\n      <mediatype>{escape(m)}</mediatype>" for m in p.get("mediatypes", []))
    provides_line = f"\n    <provides>{mediatypes}\n    </provides>" if mediatypes else ""

    def size_line(n, kind_):
        return f"\n            <size type=\"{kind_}\">{n}</size>" if isinstance(n, int) and n >= 0 else ""

    # every native package of the release (rpm, deb, Windows setup.exe) per machine, each with its own signature: the
    # store takes the one of its own system. A file without a `.asc` or without a line in SHA256SUMS.txt is left out.
    native_lines = ""
    names = {x["name"] for x in release["assets"]}
    for a in sorted(release["assets"], key=lambda a: a["name"]):
        n = a["name"]
        for suffix, fmt, platform in NATIVE:
            if n.endswith(suffix) and (n + ".asc") in names and n in sha_by_name:
                sig_url = next(x["browser_download_url"] for x in release["assets"] if x["name"] == n + ".asc")
                native_lines += f"""
          <artifact type="binary" platform="{platform}" fs-format="{fmt}" fs-signature={q(sig_url)}>
            <location>{escape(a['browser_download_url'])}</location>
            <checksum type="sha256">{sha_by_name[n]}</checksum>{size_line(a.get('size'), 'download')}
          </artifact>"""
    # releases: the current one (date from GitHub, change text from `history`), then the older ones named in `history`
    history = {h["version"]: h for h in p.get("history", [])}
    mine = history.get(version, {})
    date = mine.get("date") or str(release.get("published_at") or "")[:10]
    date_attr = f" date={q(date)}" if schema.DATE.match(date) else ""
    installed = (p.get("installed_size") or {}).get(version)
    older = ""
    for v in sorted((v for v in history if v != version), key=lambda v: tuple(int(x) for x in v.split(".")), reverse=True):
        h = history[v]
        older += f"""
      <release version={q(v)} date={q(h['date'])}>{schema.release_description_xml(h['changes'])}
      </release>"""
    component = f"""  <component type="{schema.KINDS[kind]}">
    <id>{escape(p['id'])}</id>
    <name>{escape(p['name'])}</name>
    <summary>{escape(p['summary'])}</summary>{schema.description_xml(p)}
    <url type="homepage">https://github.com/{escape(p['repo'])}</url>{icon_line}{provides_line}{schema.screenshots_xml(shots, hashes)}
    <releases>
      <release version={q(version)}{date_attr}>{schema.release_description_xml(mine.get('changes'))}
        <artifacts>
          <artifact type="binary" platform="x86_64-linux-gnu">
            <location>{escape(asset['browser_download_url'])}</location>
            <checksum type="sha256">{sha}</checksum>{size_line(asset.get('size'), 'download')}{size_line(installed, 'installed')}
          </artifact>{native_lines}
        </artifacts>
      </release>{older}
    </releases>
    <custom>{schema.custom_values(p, kind, 'tar.gz', sig['browser_download_url'])}
    </custom>
  </component>"""
    try:
        ET.fromstring(component)  # a catalog that is not well-formed XML would be signed and then refused by every store
    except ET.ParseError as why:
        sys.exit(f"{p['id']}: the generated entry is not well-formed XML: {why}")
    return component


def picture(pid, field, url, declared, icon=False):
    """The bytes of an icon or picture: an icon is a PNG of at most 1 MiB (SVG is refused, as in the store's icons.rs); a picture is
    PNG, JPEG or WebP. Must match the hash given in packages.toml when there is one."""
    data = fetch(url, schema.ICON_LIMIT if icon else schema.SCREENSHOT_LIMIT)
    if not (schema.icon_ok if icon else schema.image_ok)(data):
        sys.exit(f"{pid}: {field}: {url} is not {'a PNG icon (SVG is not accepted)' if icon else 'a PNG, JPEG or WebP picture'} (an error page?)")
    if declared and hashlib.sha256(data).hexdigest() != declared:
        sys.exit(f"{pid}: {field}: {url} does not match the given sha256 (the file changed)")
    return data


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
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if "--capabilities" in sys.argv:  # --capabilities FILE: the capability list from a local file (offline)
        CTX["caps_file"] = sys.argv[sys.argv.index("--capabilities") + 1]
        args = [a for a in args if a != CTX["caps_file"]]
    with open(args[0] if args else f"{HERE}/packages.toml", "rb") as f:
        data = tomllib.load(f)
    packages = data["package"]
    CTX["schema"] = data.get("schema", 1)
    CTX["caps_ref"] = data.get("capabilities_ref", CTX["caps_ref"])
    if CTX["schema"] not in (1, 2):
        sys.exit(f"packages.toml: schema = {CTX['schema']} is not known (1 or 2)")
    check(packages)  # all findings at once, before any network use
    CTX["checked"] = True
    if "--check" in sys.argv:
        print(f"{len(packages)} packages checked, schema {CTX['schema']}: no errors")
        return
    blocks, skipped = [], 0
    for p in packages:
        try:
            blocks.append(entry(p))
        except Transient as why:
            # A failed download must never stop bump or sign: keep what the last signed catalog said for this package.
            old = previous(p["id"])
            skipped += 1
            if old:
                blocks.append(old)
            print(f"::warning title=catalog: {p['id']} download failed::{why}; " + ("kept the entry of the last signed catalog" if old else "no earlier entry, package left out this time"))
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
        f.write(f'<?xml version="1.0" encoding="UTF-8"?>\n<components version="1.0" origin="freesynergy"{' fs-schema="2"' if CTX['schema'] >= 2 else ''} fs-serial="{serial}" fs-expires="{expires}">\n{body}\n</components>\n')


if __name__ == "__main__":
    main()
