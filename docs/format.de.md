# Katalogformat 2: Referenz (DE) · [English](format.md)

`packages.toml` sagt, was angeboten wird; `python3 scripts/gen_catalog.py` liest die öffentlichen Releases und schreibt `catalog.xml`
(AppStream-Sammlung, von der CI signiert). Format 2 ergänzt, was der Store je Paket zeigt. Jedes neue Feld ist für den Leser optional:
ein alter Eintrag bleibt gültig, der Store zeigt „unbekannt“ für das, was fehlt.

Prüfen ohne Netz (und ohne zu schreiben): `python3 -I scripts/gen_catalog.py --check [packages.toml] [--capabilities DATEI]`.
Alle Befunde auf einmal als `<Paket>: <Feld>: <Meldung>`; Fehler stoppen den Lauf, Warnungen nicht.

## Dateiebene
| Schlüssel | Bedeutung |
|---|---|
| `schema` | `1` (Vorgabe) oder `2`. Mit `2` sind die unten mit „Format 2“ markierten Regeln **Fehler**, mit `1` Warnungen (die wöchentliche Signierung hält für einen alten Eintrag nie an). Der Katalog bekommt `fs-schema="2"` an `<components>`. |
| `capabilities_ref` | Tag von `fs-interfaces`, dessen `schema/capabilities.txt` DIE Fähigkeitenliste ist (Vorgabe `v0.0.19`). Wird mit `gh api` gelesen, nie in dieses Repo kopiert. `--capabilities DATEI` / `$FS_CAPABILITIES_FILE`: lokale Datei (offline). |

## Je Paket (`[[package]]`)
Unter-Tabellen (`[package.x]`, `[[package.x]]`) **nach** den einfachen Schlüsseln des Pakets schreiben: `bump_catalog.py` ändert `tag` als Text.

| Schlüssel | XML | Regel |
|---|---|---|
| `id`, `name`, `summary`, `repo`, `tag`, `asset` | wie bisher | Pflicht; `id` klein geschrieben; `tag` `vMAJOR.MINOR.PATCH` |
| `kind` | `fs:kind`, `type` der Komponente | `program` (Vorgabe), `frontend`, `component`, `theme`, `server`, `icon-theme`. AppStream-Typ: program/frontend `desktop-application`, component/theme `addon`, server `service`, icon-theme `icon-theme`. `server` und `icon-theme` sind neu; der Store zeigt sie gesperrt, bis es Pakete gibt. |
| `description` | `<description>` | Text oder Tabelle `{ en = "..", de = ".." }` (Sprachvarianten EINER Beschreibung, `xml:lang`; `en` Pflicht, wird zuerst geschrieben). Leerzeile = neuer Absatz. Format 2: Pflicht (Rückfall des Stores). |
| `icon`, `icon_sha256` | `<icon type="remote" fs-sha256>` | https-Adresse eines Bildes. Der Generator lädt es, prüft, dass es ein Bild ist, schreibt den SHA-256 (und vergleicht mit `icon_sha256`, falls angegeben). Format 2: **Pflicht für jedes Paket**. |
| `provides`, `requires`, `recommends` | `fs:provides` ... | Liste von Fähigkeiten `"name"` oder `"name major.minor"` (auch `name>=1.2`). Namen NUR aus `capabilities.txt` von fs-interfaces; unbekannter Name = Fehler mit „meintest du“. Ein `planned`-Name ist eine Warnung. Ohne Stufe = beliebig. Getrennt von Rechten. |
| `[[package.feature]]` | `fs:features`, `fs:feature.<key>.provides/requires/recommends/name` | ein Merkmal: `key` (Pflicht), `name` und eigene `provides`/`requires`/`recommends`. Darf leer bleiben (nur `key`). |
| `mediatypes` | `<provides><mediatype>` | Liste wie `["text/calendar"]` (wie AppStream). |
| `installed_size` | `<size type="installed">` | Tabelle `{ "0.0.7" = Bytes }`; nur der Eintrag der angebotenen Version wird geschrieben (der Tag wandert von selbst, die Zahl darf nicht veralten). |
| (von GitHub) | `<size type="download">` | Größe der Release-Datei aus dem Release; auch bei rpm/deb/exe. |
| `[[package.history]]` | `<release version date><description xml:lang>` | je Release: `version`, `changes` (Text oder Sprachtabelle, `en` Pflicht), `date` `JJJJ-MM-TT` (bei älteren Releases Pflicht). Der Eintrag der angebotenen Version ist der Text des aktuellen Releases (Datum von GitHub). Ältere werden Releases ohne Dateien (nur Änderungsliste). Kein Eintrag zur aktuellen Version = Warnung (nie Fehler: `bump` hebt Tags allein an). |
| `upstream` | `fs:upstream` | https-Adresse, unter der der Macher es veröffentlicht (Quelle der Spiegelung). |
| `upstream_signature` | `fs:upstream-signature` | Signatur des Machers: Schlüssel-Fingerabdruck (hex) oder https-Adresse; braucht `upstream`. |
| `source_code` | `fs:source-code` | https-Adresse des Quellcodes dieser Version. Format 2: Pflicht, wenn `upstream` gesetzt ist (ADR 0068, mit dem Paket gespiegelt). |
| `maker` | `fs:maker` | Name des Machers. |
| `[package.description_wiki]` | `fs:description-wiki` (Block-Id), `-lang`, `-source-rev` | ADR 0072: `block` UUIDv7, `lang`, `source_rev` (Zahl; Pflicht, wenn `lang` nicht `en` ist, damit der Store eine Übersetzung als veraltet zeigen kann). Die Textbeschreibung bleibt Rückfall. |
| `[[package.screenshot]]` | `<screenshots><screenshot><image type="source" fs-sha256 fs-license fs-source><caption xml:lang>` | `url` https, `license` klar (SPDX-Id; `unknown`, `none`, `proprietary`, `all rights reserved` und seltsame Zeichen werden abgelehnt: **ohne klare Lizenz kein Bild**), `source` (Adresse oder Macher), `caption` (Text oder Sprachtabelle), `sha256` optional (wird geladen und verglichen; der berechnete Hash wird geschrieben). Das erste Bild ist das Standardbild. |

Je Art (Format 2): `program` und `server` brauchen `provides`; `frontend` braucht `requires`; `theme`, `icon-theme`, `component` nichts Zusätzliches.

## Was der Store liest (siehe `fs_store_catalog::Details`)
`<size type="download">` des Artefakts, `<release date>`, die erste `<description>` des Releases (Englisch), `fs:provides/requires/recommends`
(Kommaliste, `name major.minor`), `fs:upstream*`, `fs:source-code`, `fs:description-wiki` (der ganze Wert ist die Block-Id), `<icon>`, `<screenshot>`
(https + `fs-sha256` + klare `fs-license`, sonst zurückgehalten). Noch nicht vom Store gelesen (siehe CHANGES-FOR-STORE.md): Wahl nach `xml:lang`,
`<size type="installed">`, `fs:maker`, `fs-source`, `fs:feature.*`, `<provides><mediatype>`, `fs:description-wiki-lang`/`-source-rev`, Arten `server`/`icon-theme`.

## Beispiele und Tests
`examples/packages.example.toml` zeigt jedes Feld; `examples/catalog.example.xml` ist, was der Generator daraus macht (offline, von den Tests geprüft);
`examples/make_images.py` erzeugt die Bilder (für dieses Repo erzeugt, CC0-1.0). Tests: `python3 -I -m unittest discover -s tests`.
Goldene Datei nach gewollter Änderung erneuern: `python3 -I tests/test_schema.py --write-golden`.
