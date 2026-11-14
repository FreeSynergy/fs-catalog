"""Every tag of packages.toml must be a release of its own component in catalog.xml.
Usage: verify_tags.py catalog.xml packages.toml catalog.drafts
A tag listed in catalog.drafts (written by gen_catalog.py for a release that is explicitly a draft) is only noticed;
any other missing tag (incomplete files, missing assets, unknown tag) is an error. Exit 1 on error."""
import sys
import tomllib
import xml.etree.ElementTree as ET


def check(xml_text, packages, drafts):
    """Returns (errors, notices) as lists of strings."""
    offered = {c.findtext("id"): {r.get("version") for r in c.iterfind("releases/release")} for c in ET.fromstring(xml_text).iter("component")}
    errors, notices = [], []
    for p in packages:
        if p["tag"].lstrip("v") in offered.get(p["id"], set()):
            continue
        (notices if f"{p['id']} {p['tag']}" in drafts else errors).append(f"{p['id']} {p['tag']}")
    return errors, notices


def main(xml_path, toml_path, drafts_path):
    with open(toml_path, "rb") as f:
        packages = tomllib.load(f)["package"]
    try:
        with open(drafts_path, encoding="utf-8") as f:
            drafts = {line.strip() for line in f if line.strip()}
    except FileNotFoundError:
        drafts = set()
    with open(xml_path, encoding="utf-8") as f:
        errors, notices = check(f.read(), packages, drafts)
    for n in notices:
        print(f"::notice::{n} is still a draft release; not in the catalog yet (expected)")
    if errors:
        print("::error::tag(s) in packages.toml missing from the signed catalog: " + ", ".join(errors))
        return 1
    print(f"{len(packages)} packages: all tags present in the signed catalog ({len(notices)} draft(s) skipped)")
    return 0


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:4]))
