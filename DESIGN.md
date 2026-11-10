# Design: fs-catalog

## Release to catalog (Q2b, 2026-11-10)

0. The Opus review of a change happens BEFORE the tag, never in a workflow.
1. A tag `vX.Y.Z` is pushed by hand in the program repo; its `release.yml` (fs-release) builds, signs and creates a draft, then
   `publish` turns it into a Pre-release (own GITHUB_TOKEN of the program repo).
2. `.github/workflows/bump.yml` (every 15 minutes + workflow_dispatch) reads the public releases of every program in
   `packages.toml` (`scripts/bump_catalog.py`, sequential, read only). When a newer published release is COMPLETE
   (SHA256SUMS.txt + .asc, the package and every listed file with its .asc) the tag is raised, committed and `sign` is started
   with `gh workflow run sign.yml` (a push with GITHUB_TOKEN starts no workflow; workflow_dispatch is the exception).
3. `sign.yml` runs `scripts/gen_catalog.py`, signs `catalog.xml` and commits it. It also runs Monday and Thursday so the
   catalog (valid 35 days) is renewed without anyone; a red run opens the issue "catalog signing failed".

Properties: no secret and nothing cross-repo (pull, only this repo's own GITHUB_TOKEN with `contents: write` and `actions: write`);
delay up to 15 minutes plus the sign run; never lowers a tag; unchanged state = no commit and no sign run, and `bump` never
watches `catalog.xml`, so there is no loop with `sign`; drafts, incomplete releases and API errors are skipped with
`::warning::`, never a red run.

Trust: `bump` accepts a release only when `SHA256SUMS.txt.asc` verifies (gpg, `release-signing-key.asc` in this repo, same key as
the README, fs-release and the store) against the pinned primary fingerprint 16A4A3EE563AEF51FCF0C55DED7B57C4A1904342, and only
for repos under `FreeSynergy/`. `gen_catalog.py` skips a NEW tag that is not available yet; a tag the last signed catalog already
offered that has vanished makes the run red. Recommended: "Immutable releases" in the program repos (owner switches it on).
Tests: `python3 -I -m unittest discover -s tests` (workflow `test`).
