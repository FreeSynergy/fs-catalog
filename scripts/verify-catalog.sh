#!/usr/bin/env bash
# Checks the PUBLISHED catalog the way a client sees it: fresh clone, catalog.xml.asc verified against the project key
# (release-signing-key.asc, pinned primary fingerprint; GOODSIG required), and every tag in packages.toml is a release of its own
# component in catalog.xml (scripts/verify_tags.py; only tags listed in catalog.drafts, i.e. explicit draft releases, are tolerated).
# Any failure = non-zero exit = red run. Needs no token: the repo is public (clone over https).
# Usage: scripts/verify-catalog.sh [repo-url]   (default: this repo on GITHUB_SERVER_URL)
set -euo pipefail
PINNED=16A4A3EE563AEF51FCF0C55DED7B57C4A1904342
url="${1:-${GITHUB_SERVER_URL:-https://github.com}/${GITHUB_REPOSITORY:-FreeSynergy/fs-catalog}}"
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
git clone --quiet --depth 1 "$url" "$work/clone"
cd "$work/clone"
export GNUPGHOME="$work/gnupg"
mkdir -m 700 "$GNUPGHOME"
gpg --batch --quiet --import release-signing-key.asc
status="$(gpg --batch --status-fd 1 --verify catalog.xml.asc catalog.xml 2>/dev/null)" || {
  echo "::error::catalog.xml.asc does not verify against catalog.xml"; exit 1; }
if printf '%s\n' "$status" | grep -Eq '^\[GNUPG:\] (EXPKEYSIG|EXPSIG|REVKEYSIG|KEYREVOKED|BADSIG|ERRSIG)'; then
  echo "::error::signature made by an expired or revoked key, or bad"; exit 1
fi
printf '%s\n' "$status" | grep -q '^\[GNUPG:\] GOODSIG ' || { echo "::error::no GOODSIG for catalog.xml"; exit 1; }
primary="$(printf '%s\n' "$status" | awk '$2 == "VALIDSIG" { print $12 }')"
if [ "$primary" != "$PINNED" ]; then
  echo "::error::signature is not from the pinned project key (primary: ${primary:-none})"; exit 1
fi
python3 -I scripts/verify_tags.py catalog.xml packages.toml catalog.drafts
echo "catalog verified: signature valid for $PINNED, tags present"
