# fs-catalog

The reference catalog of FreeSynergy.Store (`fs-store`): an AppStream collection (`catalog.xml`) and its detached
OpenPGP signature (`catalog.xml.asc`, made by CI with the project signing subkey of `16A4 A3EE 563A EF51 FCF0  C55D ED7B 57C4 A190 4342`).

- `packages.toml` lists what is offered; `python3 scripts/gen_catalog.py` writes `catalog.xml` from the public releases.
- The store refuses a catalog whose signature is not valid for the trusted key. TUF metadata (ADR 0062) is planned.
- Status: pre-release packages only.

Licence: MIT OR Apache-2.0.
