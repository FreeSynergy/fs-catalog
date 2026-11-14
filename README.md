# fs-catalog

The reference catalog of FreeSynergy.Store (`fs-store`): an AppStream collection (`catalog.xml`) and its detached
OpenPGP signature (`catalog.xml.asc`, made by CI with the project signing subkey of `16A4 A3EE 563A EF51 FCF0  C55D ED7B 57C4 A190 4342`).

- `packages.toml` lists what is offered; `python3 scripts/gen_catalog.py` writes `catalog.xml` from the public releases.
- Format 2 (sizes, release texts per language, icons, pictures with licence, capabilities, origin): [docs/format.md](docs/format.md) (EN), [docs/format.de.md](docs/format.de.md) (DE); check with `python3 -I scripts/gen_catalog.py --check`.
- The store refuses a catalog whose signature is not valid for the trusted key. TUF metadata (ADR 0062) is planned.
- Status: pre-release packages only.

Licence: MIT OR Apache-2.0.

CI chain: `bump` (new release found) -> `sign` (generate, sign, commit) -> `verify` (fresh clone, signature and versions checked, `scripts/verify-catalog.sh`); see DESIGN.md.
