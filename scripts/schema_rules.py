"""Format 2, part 2: `validate` (Specification: every rule adds a finding; nothing raises, whatever is in packages.toml)."""
import re
from difflib import get_close_matches

from schema_base import CONTROL, FEATURE_KEY, KINDS, MEDIATYPE, NEW_KINDS, TAG, VERSION, Ctx, is_str, parse_capability
from schema_rules_content import (check_history, check_icon, check_origin, check_screenshots, check_text, check_wiki)


def capability_list(c, value, field, caps):
    """Checks one list of capability names; returns the names. A form error is ALWAYS an error; a name that is not in the list
    is an error in schema 2 and a warning in schema 1 (the signing run must not stop for an old file)."""
    if value is None:
        return []
    if not isinstance(value, list):
        c.err(field, 'must be a list of capabilities, e.g. ["people.persons 1.2"]')
        return []
    names = []
    for item in value:
        parsed = parse_capability(item)
        if parsed is None:
            c.err(field, f"`{item}` is not a capability (name, or name and level `major.minor`)")
            continue
        name = parsed[0]
        if name in names:
            c.err(field, f"`{name}` is listed twice")
        names.append(name)
        if caps is None:
            continue
        if name not in caps:
            near = get_close_matches(name, caps, n=1)
            hint = f"; did you mean `{near[0]}`?" if near else ""
            (c.err if c.schema >= 2 else c.warn)(field, f"`{name}` is not in the capability list of fs-interfaces (schema/capabilities.txt){hint}")
        elif caps[name] != "stable":
            c.warn(field, f"`{name}` is {caps[name]}: named in fs-interfaces, the interface is not built yet")
    return names


def check_capabilities(c, p, caps):
    named = {f: capability_list(c, p.get(f), f, caps) for f in ("provides", "requires", "recommends")}
    for name in set(named["provides"]) & (set(named["requires"]) | set(named["recommends"])):
        c.warn("requires", f"`{name}` is both offered and needed by the same package")
    feats = p.get("feature", [])
    if not isinstance(feats, list):
        c.err("feature", "must be a list of tables ([[package.feature]])")
        feats = []
    seen = set()
    for i, f in enumerate(feats):
        where = f"feature[{i}]"
        if not isinstance(f, dict) or not (is_str(f.get("key")) and FEATURE_KEY.match(f["key"])):
            c.err(where, "needs `key` as text (lower-case letters, digits, `-`)")
            continue
        if f["key"] in seen:
            c.err(where, f"feature `{f['key']}` is listed twice")
        seen.add(f["key"])
        if f.get("name") is not None and not (is_str(f["name"]) and f["name"].strip()):
            c.err(where, "`name` must be text")
        for field in ("provides", "requires", "recommends"):
            capability_list(c, f.get(field), f"feature `{f['key']}` {field}", caps)
    mt = p.get("mediatypes", [])
    if not isinstance(mt, list) or not all(is_str(m) and MEDIATYPE.match(m) for m in mt):
        c.err("mediatypes", "must be a list of media types like `text/calendar`")
    return named


def validate(p, caps=None, schema=1):
    """Every finding of one package table. `schema` 2 (set at the top of packages.toml) makes the rules of format 2 errors;
    with 1 they are warnings. `caps` is the capability list (parse_capabilities); None = names are not checked."""
    c = Ctx(p["id"] if is_str(p.get("id")) and p["id"].strip() else "?", schema)
    for key in ("id", "name", "summary", "repo", "tag", "asset"):
        if not is_str(p.get(key)) or not p[key].strip():
            c.err(key, "required text is missing")
    if is_str(p.get("id")) and not re.match(r"^[a-z0-9][a-z0-9-]*$", p["id"]):
        c.err("id", "must be lower-case letters, digits and `-`")
    if is_str(p.get("tag")) and not TAG.match(p["tag"]):
        c.err("tag", f"`{p['tag']}` is not vMAJOR.MINOR.PATCH")
    kind = p.get("kind", "program")
    if not (is_str(kind) and kind in KINDS):
        c.err("kind", f"must be one of: {', '.join(KINDS)}")
    for key in ("name", "summary"):
        if is_str(p.get(key)) and CONTROL.search(p[key]):
            c.err(key, "contains a character that XML does not allow")
    check_text(c, "description", p.get("description"), "the text description is the fallback of the store and is required")
    check_icon(c, p)
    check_origin(c, p)
    named = check_capabilities(c, p, caps)
    check_wiki(c, p)
    check_screenshots(c, p)
    check_history(c, p)
    check_kind(c, p, kind, named)
    return c.issues


def check_kind(c, p, kind, named):
    """Kinds the first stores do not know need format 2 and a minimum store version; and per kind what must be said."""
    if kind in NEW_KINDS:
        if c.schema < 2:
            c.err("kind", f"`{kind}` is only written with `schema = 2` in packages.toml (older stores do not know it)")
        if not p.get("min_store"):
            c.err("min_store", f"`{kind}` needs `min_store` (the first fs-store version that reads this kind, e.g. \"0.0.13\"); put such packages into the real catalog only AFTER that store is released")
    if p.get("min_store") is not None and not (is_str(p["min_store"]) and VERSION.match(p["min_store"])):
        c.err("min_store", "must be a version MAJOR.MINOR.PATCH")
    if kind in ("program", "server") and not named["provides"]:
        c.need("provides", f"a {kind} says what it offers (a name of the capability list)")
    if kind == "frontend" and not named["requires"]:
        c.need("requires", "a frontend says which interface it needs")
