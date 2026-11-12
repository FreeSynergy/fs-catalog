# Changes for the store agent (fs-catalog format 2) · Änderungsliste für den Store-Agenten

Reference: docs/format.md. Example: examples/catalog.example.xml. Everything below is additive; format 1 entries are unchanged.

## Read as `fs_store_catalog::Details` already reads it (no change needed)
- `<artifact><size type="download">` (main artifact; also rpm/deb/exe artifacts), `<release date="YYYY-MM-DD">` (from the GitHub release).
- `<release><description>`: now one per language (`xml:lang`), **English first**, so today's "first description" is English. Older releases: `<release version date><description>` without artifacts (already listed by `release_notes`).
- `<icon type="remote" fs-sha256>` for every package (format 2 makes it required; `icon_missing` stays for format 1 entries).
- `<screenshots><screenshot><image type="source" fs-sha256 fs-license ...>URL</image><caption>`: the generator already refuses anything the reader would withhold (not https, no hash, no clear licence); the first picture has `type="default"`.
- `fs:provides`, `fs:requires`, `fs:recommends`: comma list `name` or `name major.minor` (always `major.minor`, a bare `1` is written `1.0`); names are validated against fs-interfaces capabilities.txt.
- `fs:upstream`, `fs:upstream-signature` (fingerprint or https address), `fs:source-code`, `fs:description-wiki` (value = block id only, a UUIDv7).

## Deviations / not read yet
1. `fs:kind` may now be `server` and `icon-theme`. Checked in the source of today's reader (fs-store-catalog `catalog.rs`, `entry()`): an unknown kind returns `Err((id, "unknown fs:kind ..."))`, which `parse_catalog` turns into one `Skipped` entry; the catalog and all other packages stay fine. So an old store never fails, but it does not show the entry as "locked, not supported by this store version" either: it only lists it as skipped. Wanted in the store: an unknown `fs:kind` (and an entry with `fs:min-store` above the store's own version) becomes a locked offer with the text "not supported by this store version", never an error. Needs `Kind::Server`/`Kind::IconTheme`; `PackageKind` in store.capnp v0.0.19 has only program/frontend/component/theme: **request to fs-interfaces** (append `server @4`, `iconTheme @5`).
   Rule for the catalog: `kind = server|icon-theme` goes into the REAL catalog only AFTER a store with the fixed reader is released. The generator writes such entries only with `schema = 2` and `min_store` (value `fs:min-store`, `MAJOR.MINOR.PATCH`, the first store that reads the kind); the store should compare it with its own version.
2. Language choice: the reader takes the first `<description>`/`<caption>`; with variants it should pick by `xml:lang` (UI language, then `en`). `Details.changes`/`ReleaseNote.text`/`Screenshot.caption` are single strings today.
3. `<size type="installed">` (artifact): not read; `Details` has no installed size, `Package.size` is one number.
4. `fs:description-wiki` is the block id only (ONE UUIDv7; DE/EN are language variants inside the block, ADR 0072, user decision). `fs:description-wiki-source-rev` is the rev the entry was made from (always written); `fs:description-wiki-lang` is only an optional wish for reading (written only when given). `Description::WikiBlock(String)` and capnp `wikiBlock @18 :Text` carry no sourceRev/lang: **request to fs-interfaces** if the store should flag a block the wiki has moved past.
5. `fs:maker` (capnp `Origin.maker` exists, `Details.origin` has no maker), `fs-source` on the picture image (capnp `Picture` has no source): not read.
6. `fs:features` + `fs:feature.<key>.provides|requires|recommends|name`: feature level, not read; no capnp field yet (Bedarf if wanted).
7. `<provides><mediatype>` (AppStream): not read; no capnp field.
8. `Details.origin.source` stays set by the store (the mirror); the catalog does not write it.
9. Root attribute `fs-schema="2"` on `<components>` when packages.toml says `schema = 2`; the reader ignores it.
