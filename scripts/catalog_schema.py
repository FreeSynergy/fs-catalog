"""The schema of the FreeSynergy catalog (format 2): what a package in packages.toml may say, and the checks.

Pattern: Specification (every rule is one small check that adds a message) and Builder helpers for the XML pieces.
Pure: no network, no files. `gen_catalog.py` loads this module by path and does the reading and fetching.

The XML is AppStream "collection metadata" (as before). Standard elements are used where AppStream has them
(`<size>`, `<release date>`, `<description xml:lang>`, `<icon>`, `<screenshots>`, `<provides><mediatype>`); our own facts
are `<custom><value key="fs:...">` values, which is how AppStream allows extensions. See docs/format.md.
"""
import re
from difflib import get_close_matches
from xml.sax.saxutils import escape, quoteattr

# --- kinds -----------------------------------------------------------------------------------------------------------
# fs:kind value -> AppStream component type. `server` and `icon-theme` are new in format 2; the store shows them
# locked until packages of that kind exist.
KINDS = {
    "program": "desktop-application",
    "frontend": "desktop-application",
    "component": "addon",
    "theme": "addon",
    "server": "service",
    "icon-theme": "icon-theme",
}

# Kinds that stores before the one with the fixed reader refuse (they skip the entry with "unknown fs:kind").
NEW_KINDS = ("server", "icon-theme")

SHA256 = re.compile(r"^[0-9a-f]{64}$")
UUID7 = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
LANG = re.compile(r"^[a-z]{2,3}(-[A-Za-z0-9]{2,8})*$")
VERSION = re.compile(r"^\d+\.\d+\.\d+$")
DATE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$")
MEDIATYPE = re.compile(r"^[a-z0-9][a-z0-9!#$&^_.+-]*/[a-z0-9][a-z0-9!#$&^_.+-]*$")
FEATURE_KEY = re.compile(r"^[a-z0-9][a-z0-9-]*$")
CAPABILITY = re.compile(r"^([a-z0-9][a-z0-9._-]*)\s*(?:>=|=)?\s*(\d+(?:\.\d+)?)?$")
FINGERPRINT = re.compile(r"^[0-9A-Fa-f ]{40,}$")
CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
ICON_LIMIT = 1024 * 1024          # icons: PNG only, at most 1 MiB (as fs-store-engine/src/icons.rs)
SCREENSHOT_LIMIT = 5 * 1024 * 1024

# The same rule as the store's reader (fs-store-catalog details.rs `clear_license`): named, plain characters, and not one of
# the words that mean "unknown". A picture without a clear licence is an error here (the store would withhold it).
NOT_A_LICENSE = ("unknown", "none", "proprietary", "all rights reserved")


class Issue:
    """One finding. `error` stops the run; a warning is printed."""

    def __init__(self, error, package, field, message):
        self.error, self.package, self.field, self.message = error, package, field, message

    def __str__(self):
        return f"{self.package}: {self.field}: {self.message}"


def clear_license(text):
    t = (text or "").strip()
    plain = all(c.isascii() and (c.isalnum() or c in " .-+()") for c in t)
    return bool(t) and plain and t.lower() not in NOT_A_LICENSE


# --- capabilities (ADR 0068): the ONE list is schema/capabilities.txt of fs-interfaces -------------------------------------
def parse_capabilities(text):
    """`key | display | status | description` lines -> {key: status}. Comments (`#`) and empty lines are skipped."""
    caps = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = [x.strip() for x in line.split("|")]
        if len(parts) >= 3 and parts[0]:
            caps[parts[0]] = parts[2]
    return caps


def parse_capability(text):
    """`people.persons`, `people.persons 1.2`, `people.persons>=1`: (name, level or "") or None when it is not one."""
    m = CAPABILITY.match(str(text).strip())
    if not m:
        return None
    level = m.group(2) or ""
    if level and "." not in level:
        level += ".0"
    return m.group(1), level


def format_capabilities(items):
    """The value of fs:provides and the like: `people.persons 1.2, tasks`, the form the store's reader parses."""
    out = []
    for item in items:
        name, level = parse_capability(item)
        out.append(f"{name} {level}" if level else name)
    return ", ".join(out)


# --- small helpers -------------------------------------------------------------------------------------------------------
def texts(value):
    """A text that may be one string or a table of language -> string: [(lang or None, text)], English first."""
    if isinstance(value, str):
        return [(None, value)]
    if isinstance(value, dict):
        return sorted(value.items(), key=lambda kv: (kv[0] != "en", kv[0]))
    return []


def paragraphs(text):
    """Blank-line separated paragraphs, each one `<p>`."""
    parts = [" ".join(p.split()) for p in re.split(r"\n\s*\n", text.strip())]
    return "".join(f"<p>{escape(p)}</p>" for p in parts if p)


def lang_attr(lang):
    return f" xml:lang={quoteattr(lang)}" if lang else ""


def https(url):
    return isinstance(url, str) and url.startswith("https://") and " " not in url and "\n" not in url and len(url) > len("https://")


# --- validation ----------------------------------------------------------------------------------------------------------
def validate(p, caps=None, schema=1):
    """Every finding of one package table. `schema` 2 (set at the top of packages.toml) makes the rules of format 2 errors;
    with 1 they are warnings, so an old packages.toml stays valid and the signing run (bump, sign) never stops for them.
    `caps` is the capability list (parse_capabilities); None = it could not be read: names are then not checked (the
    generator refuses that case before it gets here when a package names a capability)."""
    pid = p.get("id", "?")
    out = []

    def err(field, msg):  # always an error: wrong data
        out.append(Issue(True, pid, field, msg))

    def need(field, msg):  # missing data of format 2: an error in schema 2, a warning in schema 1
        out.append(Issue(schema >= 2, pid, field, msg))

    def warn(field, msg):
        out.append(Issue(False, pid, field, msg))

    for key in ("id", "name", "summary", "repo", "tag", "asset"):
        if not isinstance(p.get(key), str) or not p.get(key, "").strip():
            err(key, "required text is missing")
    if isinstance(p.get("id"), str) and not re.match(r"^[a-z0-9][a-z0-9-]*$", p["id"]):
        err("id", "must be lower-case letters, digits and `-`")
    if isinstance(p.get("tag"), str) and not re.match(r"^v\d+\.\d+\.\d+$", p["tag"]):
        err("tag", f"`{p['tag']}` is not vMAJOR.MINOR.PATCH")
    kind = p.get("kind", "program")
    if kind not in KINDS:
        err("kind", f"`{kind}` is not one of: {', '.join(KINDS)}")

    for key in ("name", "summary", "description"):
        for _, t in texts(p.get(key)):
            if CONTROL.search(str(t)):
                err(key, "contains a control character (not allowed in XML)")
    desc = p.get("description")
    if desc is None or not texts(desc) or not any(t.strip() for _, t in texts(desc)):
        need("description", "the text description is the fallback of the store and is required")
    if isinstance(desc, dict):
        if "en" not in desc:
            err("description", "a table of languages needs `en` (English is the source language)")
        for lang in desc:
            if not LANG.match(lang):
                err("description", f"`{lang}` is not a language code like `en` or `pt-BR`")

    # icon: required for EVERY package
    icon = p.get("icon")
    if not icon:
        need("icon", "every package needs an icon (https address of a PNG, at most 1 MiB); the store shows it as missing")
    elif not https(icon):
        err("icon", "must be an https address")
    if p.get("icon_sha256") and not SHA256.match(str(p["icon_sha256"])):
        err("icon_sha256", "must be 64 lower-case hex characters")

    # sizes and origin
    inst = p.get("installed_size")
    if inst is not None:
        if not isinstance(inst, dict) or not all(VERSION.match(str(k)) and isinstance(v, int) and not isinstance(v, bool) and v >= 0 for k, v in inst.items()):
            err("installed_size", "must be a table version = bytes, e.g. { \"0.0.7\" = 1048576 }")
    for key in ("upstream", "source_code"):
        if p.get(key) is not None and not https(p[key]):
            err(key, "must be an https address")
    sig = p.get("upstream_signature")
    if sig is not None and not (https(sig) or (isinstance(sig, str) and FINGERPRINT.match(sig.strip()))):
        err("upstream_signature", "must be a key fingerprint (hex) or an https address of the signature")
    if sig and not p.get("upstream"):
        err("upstream_signature", "needs `upstream` (what the signature belongs to)")
    if p.get("upstream") and not p.get("source_code"):
        need("source_code", "a package that comes from an upstream is mirrored with its source code of exactly this version (ADR 0068)")
    if p.get("maker") is not None and (not isinstance(p["maker"], str) or not p["maker"].strip() or CONTROL.search(p["maker"])):
        err("maker", "must be a name")

    # capabilities (ADR 0068): names only from the list of fs-interfaces
    named = {}
    for field in ("provides", "requires", "recommends"):
        named[field] = capability_list(p.get(field), field, caps, err if schema >= 2 else warn, warn)
    for name in set(named["provides"]) & (set(named["requires"]) | set(named["recommends"])):
        warn("requires", f"`{name}` is both offered and needed by the same package")
    feats = p.get("feature", [])
    if not isinstance(feats, list):
        err("feature", "must be a list of tables ([[package.feature]])")
        feats = []
    seen = set()
    for i, f in enumerate(feats):
        where = f"feature[{i}]"
        if not isinstance(f, dict) or not FEATURE_KEY.match(str(f.get("key", ""))):
            err(where, "needs `key` (lower-case letters, digits, `-`)")
            continue
        if f["key"] in seen:
            err(where, f"feature `{f['key']}` is listed twice")
        seen.add(f["key"])
        for field in ("provides", "requires", "recommends"):
            capability_list(f.get(field), f"feature `{f['key']}` {field}", caps, err if schema >= 2 else warn, warn)

    mt = p.get("mediatypes", [])
    if not isinstance(mt, list) or not all(isinstance(m, str) and MEDIATYPE.match(m) for m in mt):
        err("mediatypes", "must be a list of media types like `text/calendar`")

    # description from the wiki (ADR 0072): ONE block id (UUIDv7); the language variants live inside the block
    w = p.get("description_wiki")
    if w is not None:
        if not isinstance(w, dict):
            err("description_wiki", "must be a table: block, source_rev (and optionally lang)")
        else:
            if not UUID7.match(str(w.get("block", ""))):
                err("description_wiki", "`block` must be a UUIDv7 (the id of the wiki block)")
            rev = w.get("source_rev")
            if not isinstance(rev, int) or isinstance(rev, bool) or rev < 0:
                err("description_wiki", "`source_rev` (the rev of the block this catalog entry was made from) is required, a whole number")
            if w.get("lang") is not None and (not isinstance(w["lang"], str) or not LANG.match(w["lang"])):
                err("description_wiki", "`lang` is only a wish for reading (a language code like `de`); leave it out for the reader's own language")
            for k in w:
                if k not in ("block", "source_rev", "lang"):
                    err("description_wiki", f"`{k}` is not a field (one block, variants inside it: no translationOf, no block per language)")

    # kinds the first stores do not know: only with an explicit minimum store version, and only in format 2
    if kind in NEW_KINDS:
        if schema < 2:
            err("kind", f"`{kind}` is only written with `schema = 2` in packages.toml (older stores do not know it)")
        if not p.get("min_store"):
            err("min_store", f"`{kind}` needs `min_store` (the first fs-store version that reads this kind, e.g. \"0.0.13\"); put such packages into the real catalog only AFTER that store is released")
    if p.get("min_store") is not None and not (isinstance(p["min_store"], str) and VERSION.match(p["min_store"])):
        err("min_store", "must be a version MAJOR.MINOR.PATCH")

    # pictures: only https, hash, CLEAR licence, source and caption
    shots = p.get("screenshot", [])
    if not isinstance(shots, list):
        err("screenshot", "must be a list of tables ([[package.screenshot]])")
        shots = []
    for i, s in enumerate(shots):
        where = f"screenshot[{i}]"
        if not isinstance(s, dict):
            err(where, "must be a table")
            continue
        if not https(s.get("url")):
            err(where, "`url` must be an https address")
        if not clear_license(s.get("license", "")):
            err(where, "no clear licence: a picture without one is not allowed (give an SPDX id such as `CC0-1.0`)")
        src = s.get("source")
        if not isinstance(src, str) or not src.strip():
            err(where, "`source` (where the picture comes from: address or name of the maker) is required")
        elif src.startswith("http") and not https(src):
            err(where, "`source` as an address must be https")
        if s.get("sha256") is not None and not SHA256.match(str(s["sha256"])):
            err(where, "`sha256` must be 64 lower-case hex characters")
        cap = s.get("caption")
        if not any(str(t).strip() for _, t in texts(cap)):
            err(where, "`caption` is required (text, or a table of languages)")
        for lang, t in texts(cap):
            if lang and not LANG.match(lang):
                err(where, f"caption language `{lang}` is not a language code")
            if CONTROL.search(str(t)):
                err(where, "caption contains a control character")

    # changes per release (history); the entry of the current version is the release description
    hist = p.get("history", [])
    if not isinstance(hist, list):
        err("history", "must be a list of tables ([[package.history]])")
        hist = []
    versions = set()
    for i, h in enumerate(hist):
        where = f"history[{i}]"
        if not isinstance(h, dict) or not VERSION.match(str(h.get("version", ""))):
            err(where, "needs `version` as MAJOR.MINOR.PATCH")
            continue
        if h["version"] in versions:
            err(where, f"version {h['version']} is listed twice")
        versions.add(h["version"])
        if h.get("date") is not None and not DATE.match(str(h["date"])):
            err(where, "`date` must be YYYY-MM-DD")
        current = isinstance(p.get("tag"), str) and h["version"] == p["tag"].lstrip("v")
        if not current and h.get("date") is None:
            err(where, "an older release needs a `date` (the catalog cannot ask GitHub for it)")
        ch = h.get("changes")
        if not any(str(t).strip() for _, t in texts(ch)):
            err(where, "`changes` is required (text, or a table of languages)")
        if isinstance(ch, dict) and "en" not in ch:
            err(where, "a table of languages needs `en`")
        for _, t in texts(ch):
            if CONTROL.search(str(t)):
                err(where, "changes contain a control character")
    if isinstance(p.get("tag"), str) and VERSION.match(p["tag"].lstrip("v")) and p["tag"].lstrip("v") not in versions:
        warn("history", f"no change text for the current version {p['tag'].lstrip('v')} (the release is listed without one)")

    # per kind (format 2): what a package of this kind must say
    if kind in ("program", "server") and not named["provides"]:
        need("provides", f"a {kind} says what it offers (a name of the capability list)")
    if kind == "frontend" and not named["requires"]:
        need("requires", "a frontend says which interface it needs")
    return out


def capability_list(value, field, caps, err, warn):
    """Checks one list of capability names; returns the names. A name that is not in the list is an error."""
    if value is None:
        return []
    if not isinstance(value, list):
        err(field, "must be a list of capabilities, e.g. [\"people.persons 1.2\"]")
        return []
    names = []
    for item in value:
        parsed = parse_capability(item) if isinstance(item, str) else None
        if parsed is None:
            err(field, f"`{item}` is not a capability (name, or name and level `major.minor`)")
            continue
        name, _ = parsed
        if name in names:
            err(field, f"`{name}` is listed twice")
        names.append(name)
        if caps is None:
            continue
        if name not in caps:
            near = get_close_matches(name, caps, n=1)
            hint = f"; did you mean `{near[0]}`?" if near else ""
            err(field, f"`{name}` is not in the capability list of fs-interfaces (schema/capabilities.txt){hint}")
        elif caps[name] != "stable":
            warn(field, f"`{name}` is {caps[name]}: named in fs-interfaces, the interface is not built yet")
    return names


def uses_capabilities(p):
    """Does this package name a capability anywhere (so that the list is needed to check it)?"""
    return any(p.get(k) for k in ("provides", "requires", "recommends")) or any(
        isinstance(f, dict) and any(f.get(k) for k in ("provides", "requires", "recommends")) for f in p.get("feature", []) if isinstance(p.get("feature"), list)
    )


def icon_ok(data):
    """An icon is a PNG (SVG is refused: it can carry script and external references) of at most ICON_LIMIT bytes."""
    return data.startswith(PNG_MAGIC) and len(data) <= ICON_LIMIT


def image_ok(data):
    """A picture is PNG, JPEG or WebP (RIFF only with `WEBP` at offset 8), at most SCREENSHOT_LIMIT bytes; never SVG or XML."""
    magic = data.startswith(PNG_MAGIC) or data.startswith(b"\xff\xd8\xff") or (data[:4] == b"RIFF" and data[8:12] == b"WEBP")
    return magic and len(data) <= SCREENSHOT_LIMIT


# --- XML pieces ----------------------------------------------------------------------------------------------------------
def description_xml(p):
    value = p.get("description")
    if not value:
        return ""
    if isinstance(value, str):
        return f"\n    <description>{paragraphs(value)}</description>"
    return "".join(f"\n    <description{lang_attr(lang)}>{paragraphs(t)}</description>" for lang, t in texts(value))


def release_description_xml(changes, indent="        "):
    return "".join(f"\n{indent}<description{lang_attr(lang)}>{paragraphs(t)}</description>" for lang, t in texts(changes))


def screenshots_xml(shots, hashes):
    """`hashes[i]` is the verified SHA-256 of picture i. The first picture is the default one."""
    if not shots:
        return ""
    out = "\n    <screenshots>"
    for i, s in enumerate(shots):
        default = ' type="default"' if i == 0 else ""
        out += f"\n      <screenshot{default}>"
        out += (
            f"\n        <image type=\"source\" fs-sha256=\"{hashes[i]}\" fs-license={quoteattr(s['license'].strip())}"
            f" fs-source={quoteattr(s['source'].strip())}>{escape(s['url'])}</image>"
        )
        out += "".join(f"\n        <caption{lang_attr(lang)}>{escape(' '.join(t.split()))}</caption>" for lang, t in texts(s["caption"]))
        out += "\n      </screenshot>"
    return out + "\n    </screenshots>"


def custom_values(p, kind, format_, signature_url):
    """The `<custom>` values, in a fixed order. The first three are the ones of format 1."""
    vals = [("fs:kind", kind), ("fs:format", format_), ("fs:signature", signature_url)]
    for field in ("provides", "requires", "recommends"):
        if p.get(field):
            vals.append((f"fs:{field}", format_capabilities(p[field])))
    feats = [f for f in p.get("feature", [])]
    if feats:
        vals.append(("fs:features", ", ".join(f["key"] for f in feats)))
    for f in feats:
        for field in ("provides", "requires", "recommends"):
            if f.get(field):
                vals.append((f"fs:feature.{f['key']}.{field}", format_capabilities(f[field])))
        if f.get("name"):
            vals.append((f"fs:feature.{f['key']}.name", f["name"]))
    for field, key in (("upstream", "fs:upstream"), ("upstream_signature", "fs:upstream-signature"), ("source_code", "fs:source-code"), ("maker", "fs:maker")):
        if p.get(field):
            vals.append((key, " ".join(str(p[field]).split())))
    w = p.get("description_wiki")
    if w:
        vals.append(("fs:description-wiki", w["block"]))
        vals.append(("fs:description-wiki-source-rev", str(w["source_rev"])))
        if w.get("lang"):
            vals.append(("fs:description-wiki-lang", w["lang"]))
    if p.get("min_store"):
        vals.append(("fs:min-store", p["min_store"]))
    return "".join(f"\n      <value key={quoteattr(k)}>{escape(str(v))}</value>" for k, v in vals)
