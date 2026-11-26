#!/usr/bin/env bash
# Makes the offline package of a version, for a server without Internet access (docs/installation.md, "Install
# without Internet access"): the image of the tool (docker save, compressed) and the files that install and update it,
# with their SHA-256 sums, in one archive.
#
#   bash docker/make_offline_package.sh IMAGE FOLDER
#
# IMAGE: the image of the version, already on this machine, under the name that the server uses
# (ghcr.io/probant-reporting/probant:X.Y.Z for a published version). Its version is read in the image (/app/VERSION).
# FOLDER: where the package goes. The files come from the folder of the code of this script (the commit of the image).
# Result, in FOLDER:
#   probant-X.Y.Z-offline.tar          one folder, probant/: probant-image-X.Y.Z.tar.gz, caddy-image.tar.gz,
#                                      docker-compose.yml, .env.example, install.sh, update.sh, check.sh,
#                                      docker/Caddyfile, VERSION, SHA256SUMS
#   probant-X.Y.Z-offline.tar.sha256   SHA-256 sum of the package
# The image of Caddy (HTTPS with the certificate of the company: install.sh --offline --domain --cert --key) is the one
# named in docker-compose.yml, downloaded first if this machine does not have it. No PostgreSQL image (see the guide).
set -euo pipefail
[ $# -eq 2 ] || { echo "Usage: bash docker/make_offline_package.sh IMAGE FOLDER"; exit 2; }
IMAGE="$1"
OUT="$2"
SOURCE="$(cd "$(dirname "$0")/.." && pwd)"
# files of a version that run the tool (the list FILES of get.sh and update.sh)
FILES="docker-compose.yml .env.example install.sh update.sh check.sh docker/Caddyfile"

# image of Caddy named in docker-compose.yml (service caddy)
CADDY="$(awk '/^  caddy:/ { s = 1 } s && /^    image:/ { print $2; exit }' "$SOURCE/docker-compose.yml")"
[ -n "$CADDY" ] || { echo "No image of Caddy in $SOURCE/docker-compose.yml."; exit 1; }

VERSION="$(docker run --rm --network none --entrypoint cat "$IMAGE" /app/VERSION | tr -d '[:space:]')"
[[ "$VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || { echo "No version X.Y.Z in the image $IMAGE (/app/VERSION: \"$VERSION\")."; exit 1; }

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
mkdir -p "$STAGE/probant/docker" "$OUT"
for f in $FILES; do cp -p "$SOURCE/$f" "$STAGE/probant/$f"; done
chmod 755 "$STAGE/probant/install.sh" "$STAGE/probant/update.sh" "$STAGE/probant/check.sh"
echo "$VERSION" > "$STAGE/probant/VERSION"
ARCHIVE="probant-image-$VERSION.tar.gz"
echo "Saving the image $IMAGE (version $VERSION)…"
docker save "$IMAGE" | gzip -n -6 > "$STAGE/probant/$ARCHIVE"
echo "Saving the image $CADDY (HTTPS)…"
# not on this machine yet: downloaded first
docker save "$CADDY" 2>/dev/null | gzip -n -6 > "$STAGE/probant/caddy-image.tar.gz" \
  || { docker pull "$CADDY" && docker save "$CADDY" | gzip -n -6 > "$STAGE/probant/caddy-image.tar.gz"; }
# shellcheck disable=SC2086  # FILES: a list of names without spaces
(cd "$STAGE/probant" && sha256sum "$ARCHIVE" caddy-image.tar.gz VERSION $FILES > SHA256SUMS)

PACKAGE="probant-$VERSION-offline.tar"
tar -C "$STAGE" --owner=0 --group=0 --numeric-owner -cf "$OUT/$PACKAGE" probant
(cd "$OUT" && sha256sum "$PACKAGE" > "$PACKAGE.sha256")
echo "Package: $OUT/$PACKAGE ($(du -m "$OUT/$PACKAGE" | cut -f1) MB; image archive $(du -m "$STAGE/probant/$ARCHIVE" | cut -f1) MB, Caddy $(du -m "$STAGE/probant/caddy-image.tar.gz" | cut -f1) MB)"
