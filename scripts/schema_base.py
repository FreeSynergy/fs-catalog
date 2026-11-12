"""Format 2, part 1: constants, small value checks and text helpers (pure; used by schema_rules*.py and schema_xml.py).

Every helper here accepts ANY value (packages.toml is typed by people): a wrong type is "not valid", never an exception."""
import re
from xml.sax.saxutils import escape, quoteattr  # noqa: F401  (re-exported for schema_xml)

# fs:kind value -> AppStream component type. `server` and `icon-theme` are new in format 2.
KINDS = {
    "program": "desktop-application",
    "frontend": "desktop-application",
    "component": "addon",
    "theme": "addon",
    "server": "service",
    "icon-theme": "icon-theme",
}
# Kinds that stores before the one with the fixed reader drop (they skip the entry with "unknown fs:kind").
NEW_KINDS = ("server", "icon-theme")

SHA256 = re.compile(r"^[0-9a-f]{64}$")
UUID7 = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
LANG = re.compile(r"^[a-z]{2,3}(-[A-Za-z0-9]{2,8})*$")
VERSION = re.compile(r"^\d+\.\d+\.\d+$")
TAG = re.compile(r"^v\d+\.\d+\.\d+$")
DATE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])-(0[1-9]|[12]\d|3[01])$")
MEDIATYPE = re.compile(r"^[a-z0-9][a-z0-9!#$&^_.+-]*/[a-z0-9][a-z0-9!#$&^_.+-]*$")
FEATURE_KEY = re.compile(r"^[a-z0-9][a-z0-9-]*$")
CAPABILITY = re.compile(r"^([a-z0-9][a-z0-9._-]*)\s*(?:>=|=)?\s*(\d+(?:\.\d+)?)?$")
FINGERPRINT = re.compile(r"^[0-9A-Fa-f ]{40,}$")
# characters XML 1.0 does not allow (control characters, the non-characters U+FFFE/U+FFFF, lone surrogates)
CONTROL = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\ud800-\udfff￾￿]")

PNG_MAGIC = b"\x89PNG\r\n\x1a\n"
ICON_LIMIT = 1024 * 1024          # icons: PNG only, at most 1 MiB (as fs-store-engine/src/icons.rs)
SCREENSHOT_LIMIT = 5 * 1024 * 1024
# The same rule as the store's reader (fs-store-catalog details.rs `clear_license`).
NOT_A_LICENSE = ("unknown", "none", "proprietary", "all rights reserved")


class Issue:
    """One finding. `error` stops the run; a warning is printed."""

    def __init__(self, error, package, field, message):
        self.error, self.package, self.field, self.message = error, package, field, message

    def __str__(self):
        return f"{self.package}: {self.field}: {self.message}"


def is_str(x):
    return isinstance(x, str)


def is_int(x):
    return isinstance(x, int) and not isinstance(x, bool)


def clear_license(text):
    """Named, only letters, digits and ` .-+()` (so no `/` or `,`), and not one of the words that mean "unknown"."""
    if not is_str(text):
        return False
    t = text.strip()
    plain = all(c.isascii() and (c.isalnum() or c in " .-+()") for c in t)
    return bool(t) and plain and t.lower() not in NOT_A_LICENSE


def https(url):
    return is_str(url) and url.startswith("https://") and " " not in url and "\n" not in url and len(url) > len("https://")


# --- texts: one string, or a table language -> string (variants of ONE text) -------------------------------------------
def text_problem(value):
    """None when `value` is a text or a table of language = text (keys language codes, `en` present); else why not."""
    if is_str(value):
        return CONTROL.search(value) and "contains a character that XML does not allow"
    if not isinstance(value, dict):
        return "must be text, or a table of language = text"
    for lang, t in value.items():
        if not is_str(lang) or not LANG.match(lang):
            return f"`{lang}` is not a language code like `en` or `pt-BR`"
        if not is_str(t):
            return f"the text for `{lang}` must be text"
        if CONTROL.search(t):
            return "contains a character that XML does not allow"
    if "en" not in value:
        return "a table of languages needs `en` (English is the source language)"
    return None


def texts(value):
    """[(lang or None, text)], English first; anything that is not text is left out."""
    if is_str(value):
        return [(None, value)]
    if isinstance(value, dict):
        return sorted(((k, v) for k, v in value.items() if is_str(k) and is_str(v)), key=lambda kv: (kv[0] != "en", kv[0]))
    return []


def has_text(value):
    return any(t.strip() for _, t in texts(value))


def paragraphs(text):
    """Blank-line separated paragraphs, each one `<p>`."""
    parts = [" ".join(p.split()) for p in re.split(r"\n\s*\n", text.strip())]
    return "".join(f"<p>{escape(p)}</p>" for p in parts if p)


def lang_attr(lang):
    return f" xml:lang={quoteattr(lang)}" if lang else ""


# --- capabilities (ADR 0068): the ONE list is schema/capabilities.txt of fs-interfaces ---------------------------------
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
    m = CAPABILITY.match(text.strip()) if is_str(text) else None
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


def uses_capabilities(p):
    """Does this package name a capability anywhere (so that the list is needed to check it)?"""
    feats = p.get("feature") if isinstance(p.get("feature"), list) else []
    return any(p.get(k) for k in ("provides", "requires", "recommends")) or any(
        isinstance(f, dict) and any(f.get(k) for k in ("provides", "requires", "recommends")) for f in feats
    )


# --- picture files -------------------------------------------------------------------------------------------------------
def icon_ok(data):
    """An icon is a PNG (SVG is refused: it can carry script and external references) of at most ICON_LIMIT bytes."""
    return data.startswith(PNG_MAGIC) and len(data) <= ICON_LIMIT


def image_ok(data):
    """A picture is PNG, JPEG or WebP (RIFF only with `WEBP` at offset 8), at most SCREENSHOT_LIMIT bytes; never SVG or XML."""
    magic = data.startswith(PNG_MAGIC) or data.startswith(b"\xff\xd8\xff") or (data[:4] == b"RIFF" and data[8:12] == b"WEBP")
    return magic and len(data) <= SCREENSHOT_LIMIT


class Ctx:
    """Collects the findings of one package. `err` is always an error (wrong data); `need` is missing data of format 2
    (an error in schema 2, a warning in schema 1); `warn` is always a warning."""

    def __init__(self, package, schema):
        self.package, self.schema, self.issues = package, schema, []

    def err(self, field, msg):
        self.issues.append(Issue(True, self.package, field, msg))

    def need(self, field, msg):
        self.issues.append(Issue(self.schema >= 2, self.package, field, msg))

    def warn(self, field, msg):
        self.issues.append(Issue(False, self.package, field, msg))
