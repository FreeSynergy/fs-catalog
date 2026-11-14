#!/usr/bin/env bash
# Checks the PUBLISHED catalog the way a client sees it: fresh clone, catalog.xml.asc verified against the project key
# (release-signing-key.asc, pinned primary fingerprint), and every tag in packages.toml is a release in catalog.xml.
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
primary="$(printf '%s\n' "$status" | awk '$2 == "VALIDSIG" { print $12 }')"
if [ "$primary" != "$PINNED" ]; then
  echo "::error::signature is not from the pinned project key (primary: ${primary:-none})"; exit 1
fi
python3 -I - catalog.xml packages.toml <<'PY'
import sys, tomllib
xml = open(sys.argv[1], encoding="utf-8").read()
with open(sys.argv[2], "rb") as f:
    packages = tomllib.load(f)["package"]
missing = [f"{p['id']} {p['tag']}" for p in packages if f'<release version="{p["tag"].lstrip("v")}"' not in xml]
if missing:
    print("::error::tag(s) in packages.toml missing from the signed catalog: " + ", ".join(missing))
    sys.exit(1)
print(f"{len(packages)} packages: all tags present in the signed catalog")
PY
echo "catalog verified: signature valid for $PINNED, tags present"
