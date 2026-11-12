"""Format 2, part 2b: the rules for texts, icon, wiki block, pictures and the change history (Specification)."""
from schema_base import (CONTROL, DATE, FINGERPRINT, LANG, SHA256, UUID7, VERSION, clear_license, has_text, https, is_int, is_str,
                         text_problem)


def check_text(c, field, value, what):
    """A required text field: a string or a language table (all texts strings, `en` present), not empty."""
    bad = text_problem(value) if value is not None else None
    if bad:
        c.err(field, bad)
    elif not has_text(value):
        c.need(field, what)


def check_icon(c, p):
    icon = p.get("icon")
    if not icon:
        c.need("icon", "every package needs an icon (https address of a PNG, at most 1 MiB); the store shows it as missing")
    elif not https(icon):
        c.err("icon", "must be an https address")
    if p.get("icon_sha256") is not None and not (is_str(p["icon_sha256"]) and SHA256.match(p["icon_sha256"])):
        c.err("icon_sha256", "must be 64 lower-case hex characters")


def check_wiki(c, p):
    """ADR 0072: ONE block id (UUIDv7); the language variants live inside the block."""
    w = p.get("description_wiki")
    if w is None:
        return
    if not isinstance(w, dict):
        c.err("description_wiki", "must be a table: block, source_rev (and optionally lang)")
        return
    if not (is_str(w.get("block")) and UUID7.match(w["block"])):
        c.err("description_wiki", "`block` must be a UUIDv7 (the id of the wiki block)")
    rev = w.get("source_rev")
    if not is_int(rev) or rev < 0:
        c.err("description_wiki", "`source_rev` (the rev of the block this catalog entry was made from) is required, a whole number")
    if w.get("lang") is not None and not (is_str(w["lang"]) and LANG.match(w["lang"])):
        c.err("description_wiki", "`lang` is only a wish for reading (a language code like `de`); leave it out for the reader's own language")
    for k in w:
        if k not in ("block", "source_rev", "lang"):
            c.err("description_wiki", f"`{k}` is not a field (one block, variants inside it: no translationOf, no block per language)")


def check_screenshots(c, p):
    shots = p.get("screenshot", [])
    if not isinstance(shots, list):
        c.err("screenshot", "must be a list of tables ([[package.screenshot]])")
        return
    for i, s in enumerate(shots):
        where = f"screenshot[{i}]"
        if not isinstance(s, dict):
            c.err(where, "must be a table")
            continue
        if not https(s.get("url")):
            c.err(where, "`url` must be an https address")
        if not clear_license(s.get("license", "")):
            c.err(where, "no clear licence: a picture without one is not allowed (give an SPDX id such as `CC0-1.0`; letters, digits and ` .-+()` only)")
        src = s.get("source")
        if not is_str(src) or not src.strip() or CONTROL.search(src):
            c.err(where, "`source` (where the picture comes from: address or name of the maker) is required, as text")
        elif src.startswith("http") and not https(src):
            c.err(where, "`source` as an address must be https")
        if s.get("sha256") is not None and not (is_str(s["sha256"]) and SHA256.match(s["sha256"])):
            c.err(where, "`sha256` must be 64 lower-case hex characters")
        bad = text_problem(s.get("caption")) if s.get("caption") is not None else "`caption` is required (text, or a table of languages)"
        if bad:
            c.err(where, f"caption: {bad}" if s.get("caption") is not None else bad)
        elif not has_text(s["caption"]):
            c.err(where, "`caption` is required (text, or a table of languages)")


def check_history(c, p):
    """Changes per release; the entry of the current version is the release description."""
    hist = p.get("history", [])
    if not isinstance(hist, list):
        c.err("history", "must be a list of tables ([[package.history]])")
        return
    tag = p.get("tag") if is_str(p.get("tag")) else ""
    versions = set()
    for i, h in enumerate(hist):
        where = f"history[{i}]"
        if not isinstance(h, dict) or not (is_str(h.get("version")) and VERSION.match(h["version"])):
            c.err(where, "needs `version` as MAJOR.MINOR.PATCH")
            continue
        if h["version"] in versions:
            c.err(where, f"version {h['version']} is listed twice")
        versions.add(h["version"])
        if h.get("date") is not None and not (is_str(h["date"]) and DATE.match(h["date"])):
            c.err(where, "`date` must be YYYY-MM-DD")
        if h.get("date") is None and h["version"] != tag.lstrip("v"):
            c.err(where, "an older release needs a `date` (the catalog cannot ask GitHub for it)")
        bad = text_problem(h.get("changes")) if h.get("changes") is not None else "`changes` is required (text, or a table of languages)"
        if bad:
            c.err(where, f"changes: {bad}" if h.get("changes") is not None else bad)
        elif not has_text(h["changes"]):
            c.err(where, "`changes` is required (text, or a table of languages)")
    current = tag.lstrip("v")
    if VERSION.match(current) and current not in versions:
        c.warn("history", f"no change text for the current version {current} (the release is listed without one)")


def check_origin(c, p):
    inst = p.get("installed_size")
    if inst is not None and not (isinstance(inst, dict) and all(is_str(k) and VERSION.match(k) and is_int(v) and v >= 0 for k, v in inst.items())):
        c.err("installed_size", 'must be a table version = bytes, e.g. { "0.0.7" = 1048576 }')
    for key in ("upstream", "source_code"):
        if p.get(key) is not None and not https(p[key]):
            c.err(key, "must be an https address")
    sig = p.get("upstream_signature")
    if sig is not None and not (https(sig) or (is_str(sig) and FINGERPRINT.match(sig.strip()))):
        c.err("upstream_signature", "must be a key fingerprint (hex) or an https address of the signature")
    if sig and not p.get("upstream"):
        c.err("upstream_signature", "needs `upstream` (what the signature belongs to)")
    if p.get("upstream") and not p.get("source_code"):
        c.need("source_code", "a package that comes from an upstream is mirrored with its source code of exactly this version (ADR 0068)")
    if p.get("maker") is not None and (not is_str(p["maker"]) or not p["maker"].strip() or CONTROL.search(p["maker"])):
        c.err("maker", "must be a name")

