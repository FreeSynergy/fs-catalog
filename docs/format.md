# Catalog format 2: reference (EN) · [Deutsch](format.de.md)

`packages.toml` says what is offered; `python3 scripts/gen_catalog.py` reads the public releases and writes `catalog.xml`
(AppStream collection metadata, signed by CI). Format 2 adds the information the store shows per package. Every new field is
optional for the reader: an old entry stays valid and the store shows "unknown" for what it does not say.

Check without network (and without writing): `python3 -I scripts/gen_catalog.py --check [packages.toml] [--capabilities FILE]`.
Every finding is reported at once as `<package>: <field>: <message>`; errors stop the run, warnings do not.

## File level
| Key | Meaning |
|---|---|
| `schema` | `1` (default) or `2`. With `2` the rules marked "format 2" below are **errors**; with `1` they are warnings, so the weekly signing never stops for an old entry. The catalog gets `fs-schema="2"` on `<components>`. |
| `capabilities_ref` | Tag (form `vX.Y.Z`, checked) of `fs-interfaces` whose `schema/capabilities.txt` is THE capability list (default `v0.0.19`). Read with `gh api`; never copied into this repo. `--capabilities FILE` / `$FS_CAPABILITIES_FILE` use a local file (offline). |

## Per package (`[[package]]`)
Write sub-tables (`[package.x]`, `[[package.x]]`) **after** the plain keys of the package: `bump_catalog.py` edits `tag` by text.

| Key | XML | Rule |
|---|---|---|
| `id`, `name`, `summary`, `repo`, `tag`, `asset` | as before | required; `id` lower-case; `tag` `vMAJOR.MINOR.PATCH` |
| `kind` | `fs:kind`, component `type` | `program` (default), `frontend`, `component`, `theme`, `server`, `icon-theme`. AppStream type: program and frontend `desktop-application`, component and theme `addon`, server `service`, icon-theme `icon-theme`. `server` and `icon-theme` are new. Today's stores (before 0.0.13) **drop** such an entry ("unknown fs:kind", listed as skipped; the catalog and the other packages stay fine); a locked "not supported by this store version" offer is shown only by stores from 0.0.13 on (the reader fix is in progress). So they are written only with `schema = 2` AND `min_store`, and go into the REAL catalog only AFTER a store with the fixed reader is released. |
| `description` | `<description>` | text, or a table `{ en = "..", de = ".." }` (variants of ONE description, `xml:lang`; `en` required, written first). Blank line = new paragraph. Format 2: required (it is the fallback of the store). |
| `icon`, `icon_sha256` | `<icon type="remote" fs-sha256>` | https address of a **PNG of at most 1 MiB** (SVG is refused, as in the store). The generator downloads it, checks the PNG signature, writes its SHA-256 (and compares with `icon_sha256` when given). Format 2: **required for every package**. |
| `provides`, `requires`, `recommends` | `fs:provides` ... | list of capabilities `"name"` or `"name major.minor"` (also `name>=1.2`). Names ONLY from `capabilities.txt` of fs-interfaces; unknown name = error with a "did you mean". A `planned` name is a warning. No level = any. Kept apart from rights. |
| `[[package.feature]]` | `fs:features`, `fs:feature.<key>.provides/requires/recommends/name` | a feature: `key` (required), `name`, and its own `provides`/`requires`/`recommends`. May stay empty (`key` only). |
| `mediatypes` | `<provides><mediatype>` | list like `["text/calendar"]` (as AppStream). |
| `installed_size` | `<size type="installed">` | table `{ "0.0.7" = bytes }`; only the entry of the offered version is written (the tag moves by itself, the number must not go stale). |
| (from GitHub) | `<size type="download">` | size of the release file, taken from the release; also on rpm/deb/exe files. |
| `[[package.history]]` | `<release version date><description xml:lang>` | per release: `version`, `changes` (text or language table, `en` required), `date` `YYYY-MM-DD` (required for older releases). The entry of the offered version is the text of the current release (its date comes from GitHub). Older ones become releases without files (change list only). No entry for the current version = a warning (never an error: `bump` raises tags alone). |
| `upstream` | `fs:upstream` | https address where the maker publishes it (mirror source). |
| `upstream_signature` | `fs:upstream-signature` | maker's signature: key fingerprint (hex) or https address; needs `upstream`. |
| `source_code` | `fs:source-code` | https address of the source code of this version. Format 2: required when `upstream` is set (ADR 0068, mirrored with the package). |
| `maker` | `fs:maker` | name of the maker. |
| `[package.description_wiki]` | `fs:description-wiki` (block id), `-source-rev`, optional `-lang` | ADR 0072, Nutzerentscheid: DE/EN are ONE page with language variants, so ONE block id (UUIDv7) and the variants live inside the block. `block`, `source_rev` (number, required: the rev this entry was made from, so the store can tell the wiki moved on), `lang` optional (only a wish for reading, never a second block). No `translationOf`, no block per language. The text description stays the fallback. |
| `min_store` | `fs:min-store` | first fs-store version that reads this entry, `MAJOR.MINOR.PATCH`. It protects only from store 0.0.13 on: older stores ignore `fs:min-store` for kinds they know (program, ...); for unknown kinds they just leave the entry out (skipped), they do not fail. **Required for `server` and `icon-theme`**, which are written only with `schema = 2`. |
| `[[package.screenshot]]` | `<screenshots><screenshot><image type="source" fs-sha256 fs-license fs-source><caption xml:lang>` | `url` https, `license` clear (SPDX id; `unknown`, `none`, `proprietary`, `all rights reserved` and odd characters are refused: **no clear licence, no picture**), `source` (address or maker), `caption` (text or language table), `sha256` optional (downloaded and compared; the computed hash is written). PNG, JPEG or WebP, at most 5 MiB. The first picture is the default. |

Per kind (format 2): `program` and `server` must have `provides`; `frontend` must have `requires`; `theme`, `icon-theme`, `component` need nothing extra.

## Downloads and failures
Icons and pictures are fetched over https only (also after redirects, `--proto =https --proto-redir =https`, at most 3 redirects), with a size limit; the FIRST host is refused when it resolves to a loopback or private address (a redirect, at most 3 and https only, or DNS rebinding between that check and the download is **not** covered: the generator runs on a GitHub runner with no internal services and reads only public pictures); the file type is checked by its first bytes (WebP only with `WEBP` at offset 8; no SVG, no XML). A **failed download never stops bump or sign**: the package is skipped with a warning and the entry of the last signed catalog is kept. A wrong file (not a picture, hash differs, too large) is an error. Under `schema = 1` wrong capability names are only warnings, and the list is read from GitHub only when a package names a capability (if it cannot be read: a warning).

## What the store reads (see `fs_store_catalog::Details`)
`<size type="download">` of the artifact, `<release date>`, the first `<description>` of the release (English), `fs:provides/requires/recommends`
(comma list, `name major.minor`), `fs:upstream*`, `fs:source-code`, `fs:description-wiki` (the whole value is the block id), `<icon>`, `<screenshot>`
(https + `fs-sha256` + clear `fs-license`, else withheld). Not yet read by the store (see CHANGES-FOR-STORE.md): `xml:lang` choice, `<size type="installed">`,
`fs:maker`, `fs-source`, `fs:feature.*`, `<provides><mediatype>`, `fs:description-wiki-source-rev`/`-lang`, kinds `server`/`icon-theme`.

## Examples and tests
`examples/packages.example.toml` shows every field; `examples/catalog.example.xml` is what the generator makes from it (offline, checked by the tests);
`examples/make_images.py` makes the pictures (generated for this repo, CC0-1.0). Tests: `python3 -I -m unittest discover -s tests`.
Refresh the golden file after a change on purpose: `python3 -I tests/support.py --write-golden`.
