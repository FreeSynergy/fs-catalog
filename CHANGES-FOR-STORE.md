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
1. `fs:kind` may now be `server` and `icon-theme`. The reader returns "unknown fs:kind" for them (entry refused), so they would show as refused, not as locked. Needs `Kind::Server`/`Kind::IconTheme` in the store; `PackageKind` in store.capnp (v0.0.19) has only program/frontend/component/theme: **request to fs-interfaces** (append `server @4`, `iconTheme @5`).
2. Language choice: the reader takes the first `<description>`/`<caption>`; with variants it should pick by `xml:lang` (UI language, then `en`). `Details.changes`/`ReleaseNote.text`/`Screenshot.caption` are single strings today.
3. `<size type="installed">` (artifact): not read; `Details` has no installed size, `Package.size` is one number.
4. `fs:description-wiki` is the block id only; its language and the sourceRev of a translation are separate values `fs:description-wiki-lang` and `fs:description-wiki-source-rev` (ADR 0072; one block id per language). `Description::WikiBlock(String)` and capnp `wikiBlock @18 :Text` carry no lang/sourceRev: **request to fs-interfaces** if the store should flag outdated translations.
5. `fs:maker` (capnp `Origin.maker` exists, `Details.origin` has no maker), `fs-source` on the picture image (capnp `Picture` has no source): not read.
6. `fs:features` + `fs:feature.<key>.provides|requires|recommends|name`: feature level, not read; no capnp field yet (Bedarf if wanted).
7. `<provides><mediatype>` (AppStream): not read; no capnp field.
8. `Details.origin.source` stays set by the store (the mirror); the catalog does not write it.
9. Root attribute `fs-schema="2"` on `<components>` when packages.toml says `schema = 2`; the reader ignores it.
