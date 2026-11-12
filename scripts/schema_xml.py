"""Format 2, part 3: the XML pieces (Builder). Only called for packages without errors, but never trusting more than needed."""
from schema_base import escape, format_capabilities, lang_attr, paragraphs, quoteattr, texts


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
    feats = list(p.get("feature", []))
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
