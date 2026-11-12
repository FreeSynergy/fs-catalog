"""The schema of the FreeSynergy catalog (format 2): what a package in packages.toml may say, and the checks. See docs/format.md.

Facade over four small modules (ADR 0043: at most 300 lines each): schema_base (constants, value checks, text helpers),
schema_rules and schema_rules_content (`validate`), schema_xml (the XML pieces). Pure: no network, no files.
The modules are loaded by path (`python3 -I` and importlib loading do not have scripts/ on the module path) and registered
under their own names so they can import each other."""
import importlib.util
import os
import sys

for _name in ("schema_base", "schema_rules_content", "schema_rules", "schema_xml"):
    if _name not in sys.modules:
        _spec = importlib.util.spec_from_file_location(_name, os.path.join(os.path.dirname(os.path.abspath(__file__)), _name + ".py"))
        _mod = importlib.util.module_from_spec(_spec)
        sys.modules[_name] = _mod
        _spec.loader.exec_module(_mod)

from schema_base import *  # noqa: E402,F401,F403
from schema_base import (CONTROL, DATE, FEATURE_KEY, ICON_LIMIT, KINDS, NEW_KINDS, PNG_MAGIC, SCREENSHOT_LIMIT, SHA256, UUID7, VERSION,  # noqa: E402,F401
                         Issue, clear_license, format_capabilities, icon_ok, image_ok, parse_capabilities, parse_capability, uses_capabilities)
from schema_rules import validate  # noqa: E402,F401
from schema_xml import custom_values, description_xml, release_description_xml, screenshots_xml  # noqa: E402,F401
