#!/usr/bin/env bash
# Makes the list of the SHA-256 sums of the files of a version that get.sh, update.sh and auto-update.sh download from
# the tag of the version (docs/installation.md, "Install with one command"): probant-X.Y.Z-files.sha256. The workflow
# .github/workflows/image.yml signs it (cosign sign-blob, Sigstore bundle) and attaches both to the release of the tag.
#
#   bash docker/make_file_sums.sh FOLDER [CODE]
#
# CODE: the folder of the files (default: the folder of the code of this script, the commit of the version); X.Y.Z is
# its VERSION file. Result: FOLDER/probant-X.Y.Z-files.sha256, one line "<sum>  <path>" for each file, in the format of
# sha256sum (in a folder with these files: sha256sum -c --ignore-missing probant-X.Y.Z-files.sha256).
set -euo pipefail
[ $# -ge 1 ] && [ $# -le 2 ] || { echo "Usage: bash docker/make_file_sums.sh FOLDER [CODE]"; exit 2; }
CODE="$(cd "${2:-$(dirname "$0")/..}" && pwd)"
# VERSION and get.sh, then the files of a version (FILES and OPTIONAL_FILES of get.sh and update.sh, FILES of
# auto-update.sh)
FILES="VERSION get.sh docker-compose.yml .env.example install.sh update.sh check.sh docker/Caddyfile auto-update.sh"

VERSION="$(tr -d '[:space:]' < "$CODE/VERSION")"
[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "No version X.Y.Z in $CODE/VERSION (\"$VERSION\")."; exit 1; }
mkdir -p "$1"
OUT="$(cd "$1" && pwd)/probant-$VERSION-files.sha256"
# shellcheck disable=SC2086  # FILES: a list of names without spaces
(cd "$CODE" && sha256sum $FILES) > "$OUT"
echo "List of sums: $OUT ($(wc -l < "$OUT") files of version $VERSION)"
