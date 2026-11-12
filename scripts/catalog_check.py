"""Checks for the generator: settings of one run (CTX), the capability list of fs-interfaces, and `check` of all packages."""
import os
import re
import subprocess
import sys

import catalog_schema as schema

DEFAULT_CAPS_REF = "v0.0.19"  # the tag of fs-interfaces whose capabilities.txt tests/fixtures/capabilities.txt is a snapshot of
# Settings of this run (set by main; defaults let `entry` be called alone, as the tests do).
CTX = {"schema": 1, "caps": None, "caps_file": None, "caps_ref": DEFAULT_CAPS_REF}


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


def read_settings(data):
    """Schema level and capability tag of packages.toml (top-level keys); exits with a message when they are not valid."""
    level = data.get("schema", 1)
    if isinstance(level, bool) or level not in (1, 2):
        sys.exit(f"packages.toml: schema = {level!r} is not known (1 or 2)")
    ref = data.get("capabilities_ref", DEFAULT_CAPS_REF)
    if not isinstance(ref, str) or not re.match(r"^v\d+\.\d+\.\d+$", ref):
        sys.exit(f"packages.toml: capabilities_ref = {ref!r} must be a tag like v0.0.19")
    CTX["schema"], CTX["caps_ref"] = level, ref
