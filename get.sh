#!/bin/sh
# Installs Probant on a Linux server in one command, with the published Docker image: no Git, no image build.
#
#   curl -fsSL https://github.com/Probant-Reporting/probant/raw/main/get.sh | sudo sh
#   curl -fsSL https://github.com/Probant-Reporting/probant/raw/main/get.sh | sudo sh -s -- --domain reporting.example.com
#
# To read it before you run it: download it (curl -fsSLO <same address>), read it, then run "sudo sh get.sh". Its
# SHA-256 sum is in the list of the release of each version (docs/installation.md, "Read the script before you run it").
#
# Options:
#   --version X.Y.Z    version to install (default: the latest published version)
#   --dir FOLDER       folder of the installation (default: probant, in the current folder)
#   --domain NAME      HTTPS with an automatic certificate (option of install.sh)
#   --port PORT        another HTTP port (option of install.sh)
#   --yes              if Docker is missing, install it without asking first (option of install.sh)
#   --check            only checks the server for this installation (check.sh of the version), installs nothing
#   --skip-check       installs without the check of the server (option of install.sh)
#   --cert FILE --key FILE   HTTPS with the certificate of your company, with --domain (options of install.sh)
#   --ca-cert FILE     certificate authority of your company for the outgoing connections (option of install.sh)
#   --auto-update off  no automatic updates (default: on, a timer of the server installs each new version at night;
#                      option of install.sh, docs/installation.md "Automatic updates")
#
# What it does, in this order: finds the version; downloads into FOLDER only the files that run the tool
# (docker-compose.yml, .env.example, install.sh, update.sh, check.sh, docker/Caddyfile, auto-update.sh), from the tag of
# that version in the public repository; checks each one against the list of the SHA-256 sums of the release of that
# version, and the signature of this list with cosign (of this server, or its official container if Docker responds)
# when that is possible: no list, a refused signature or one file that does not match, and nothing is installed; then
# runs FOLDER/install.sh with IMAGE= set to the published image of that version, and with --auto-update on (unless
# --auto-update off).
# install.sh checks the server (check.sh), offers to install Docker if it is missing, creates .env, downloads the image
# and starts the tool. Nothing changes outside FOLDER, except Docker if you accept.
# With --check: the files go to a temporary folder, deleted at the end; nothing else is written. Guide: docs/installation.md
set -eu

# Public repository and image. The two PROBANT_TEST_ variables are reserved for the tests of this script (local copy
# of the repository, local image registry): leave them unset.
SOURCE="${PROBANT_TEST_SOURCE:-https://github.com/Probant-Reporting/probant}"
IMAGE_NAME="${PROBANT_TEST_IMAGE:-ghcr.io/probant-reporting/probant}"
# files of a version that run the tool (the same list in update.sh)
FILES="docker-compose.yml .env.example install.sh update.sh check.sh docker/Caddyfile"
# files of a version since the automatic updates (the versions before do not have them)
OPTIONAL_FILES="auto-update.sh"
# authorities of the company for cosign in its container (update.sh: certificates/ca of the installation; none here yet)
CA_DIR=""

VERSION="" ; DIR="probant" ; DOMAIN="" ; PORT="" ; YES=0 ; CHECK=0 ; SKIP_CHECK=0 ; AUTO_UPDATE=on
# options of the certificates, given as they are to install.sh and check.sh: one word per line
CERTIFICATE_OPTIONS="" ; NL='
'
need_value() { [ $# -ge 2 ] || { echo "The option $1 needs a value (see sh get.sh --help)."; exit 2; }; }
while [ $# -gt 0 ]; do
  case "$1" in
    --version) need_value "$@"; VERSION="${2#[vV]}"; shift 2 ;;
    --dir) need_value "$@"; DIR="$2"; shift 2 ;;
    --domain) need_value "$@"; DOMAIN="$2"; shift 2 ;;
    --port) need_value "$@"; PORT="$2"; shift 2 ;;
    --yes) YES=1; shift ;;
    --check) CHECK=1; shift ;;
    --skip-check) SKIP_CHECK=1; shift ;;
    --cert|--key|--ca-cert) need_value "$@"; CERTIFICATE_OPTIONS="$CERTIFICATE_OPTIONS$1$NL$2$NL"; shift 2 ;;
    --auto-update)
      need_value "$@"
      case "$2" in on|off) AUTO_UPDATE="$2" ;; *) echo "--auto-update: on or off."; exit 2 ;; esac; shift 2 ;;
    -h|--help) sed -n '2,32p' "$0" 2>/dev/null || echo "Options: --version X.Y.Z --dir FOLDER --domain NAME --port PORT --yes --check --skip-check --cert FILE --key FILE --ca-cert FILE --auto-update on|off"; exit 0 ;;
    *) echo "Unknown option: $1 (see sh get.sh --help)"; exit 2 ;;
  esac
done

# ---- Download of the files of a version (the same functions in update.sh)
# HTTPS only, also after a redirection (github.com sends the files from raw.githubusercontent.com)
PROTO="=https"
if [ -n "${PROBANT_TEST_SOURCE:-}" ]; then PROTO="=http,https"; fi
is_version() { printf '%s\n' "$1" | grep -Eqx '[0-9]+\.[0-9]+\.[0-9]+'; }
fetch() { curl -fsSL --connect-timeout 20 --retry 3 --retry-max-time 60 --proto "$PROTO" --proto-redir "$PROTO" -o "$2" "$1"; }
# latest published version: the address of the latest release leads to .../releases/tag/vX.Y.Z
latest_version() {
  url=$(curl -fsSL --connect-timeout 20 --retry 3 --retry-max-time 60 --proto "$PROTO" --proto-redir "$PROTO" -o /dev/null -w '%{url_effective}' "$SOURCE/releases/latest") || return 1
  v="${url##*/tag/}"; v="${v#[vV]}"
  is_version "$v" && echo "$v"
}
# download_files VERSION FOLDER: the files of that version, from its tag (vX.Y.Z, or VX.Y.Z as some tags are written);
# the VERSION file of the tag must give the same version (it stays in FOLDER: its sum is checked with the others)
download_files() {
  for tag in "v$1" "V$1"; do
    if fetch "$SOURCE/raw/refs/tags/$tag/VERSION" "$2/VERSION" 2>/dev/null && [ "$(cat "$2/VERSION")" = "$1" ]; then
      for f in $FILES; do
        mkdir -p "$2/$(dirname "$f")"
        fetch "$SOURCE/raw/refs/tags/$tag/$f" "$2/$f" || return 1
      done
      TAG_FOUND="$tag"
      return 0
    fi
  done
  return 1
}
# download_optional FOLDER: the optional files of the tag found by download_files, when the tag has them
download_optional() {
  [ -n "${TAG_FOUND:-}" ] || return 1
  for f in $OPTIONAL_FILES; do
    fetch "$SOURCE/raw/refs/tags/$TAG_FOUND/$f" "$1/$f" 2>/dev/null || rm -f "$1/$f"
  done
}

# ---- SHA-256 sums of the files of a version (the same values and functions in get.sh and update.sh). The release of
# each version has the list of the SHA-256 sums of its files (probant-X.Y.Z-files.sha256) and the signature of this list
# (cosign bundle, probant-X.Y.Z-files.sha256.sigstore.json), made by the workflow image.yml of the public repository.
# Each version that this script downloads must have them: no list, or one file that does not match it, and nothing
# changes.
# The PROBANT_TEST_COSIGN_ variables are reserved for the tests of the scripts (test key and test image of cosign): they
# are read only with PROBANT_TEST_SOURCE, so the list of the public repository is always verified against its identity.
REPOSITORY="Probant-Reporting/probant"
ISSUER="https://token.actions.githubusercontent.com"
# official image of cosign (Sigstore), the one of auto-update.sh, pinned by the digest of its multi-platform index
COSIGN_IMAGE="ghcr.io/sigstore/cosign/cosign:v3.1.5@sha256:191099139868a6cd02abae63f2919e0915dcaa7bcc22bda6fbd11fd0dd5599e7"
TEST_KEY=""
if [ -n "${PROBANT_TEST_SOURCE:-}" ]; then
  COSIGN_IMAGE="${PROBANT_TEST_COSIGN_IMAGE:-$COSIGN_IMAGE}"
  TEST_KEY="${PROBANT_TEST_COSIGN_KEY:-}"
fi
# download_sums VERSION FOLDER: the list and its signature, into FOLDER/sums, from the release of the tag found by
# download_files
download_sums() {
  mkdir -p "$2/sums"
  for s in "probant-$1-files.sha256" "probant-$1-files.sha256.sigstore.json"; do
    fetch "$SOURCE/releases/download/$TAG_FOUND/$s" "$2/sums/$s" 2>/dev/null || return 1
  done
}
# check_sums VERSION FOLDER: each file downloaded into FOLDER has the sum that the list gives for it, and each file of
# the version that the list names is there; the first file that does not match is named
check_sums() {
  list="$2/sums/probant-$1-files.sha256"
  command -v sha256sum >/dev/null 2>&1 || { echo "sha256sum is missing (package coreutils): the files cannot be checked."; return 1; }
  for f in VERSION $FILES $OPTIONAL_FILES; do
    want=$(awk -v f="$f" '{ n = $2; sub(/^[*]/, "", n) } n == f { s = $1; c++ } END { if (c == 1) print s }' "$list")
    if [ -f "$2/$f" ]; then
      printf '%s\n' "$want" | grep -Eqx '[0-9a-f]{64}' || { echo "$f is not in the list of sums $(basename "$list")."; return 1; }
      got=$(sha256sum < "$2/$f"); got="${got%% *}"
      [ "$got" = "$want" ] || { echo "$f does not match its SHA-256 sum in $(basename "$list"): it was changed or damaged on the way."; return 1; }
    elif [ -n "$want" ]; then
      echo "$f is in the list of sums $(basename "$list"), but it could not be downloaded."; return 1
    fi
  done
}
# cosign_in FOLDER ARGUMENTS…: cosign of this machine (COSIGN_MODE=host), or its official container (read only, no
# capability, the user of this script, FOLDER read only as /work, the authorities of the company if CA_DIR has them)
cosign_in() {
  d="$1"; shift
  if [ "$COSIGN_MODE" = host ]; then cosign "$@"; return; fi
  ca=""; key=""
  if [ -n "$CA_DIR" ] && [ -d "$CA_DIR" ]; then ca="-v $CA_DIR:/etc/probant/ca:ro"; fi
  if [ -n "$TEST_KEY" ]; then key="-v $TEST_KEY:/run/probant-test.pub:ro"; fi
  # shellcheck disable=SC2086 # $ca and $key: options without spaces
  docker run --rm --network host --read-only --tmpfs /tmp --cap-drop ALL --security-opt no-new-privileges \
    --user "$(id -u):$(id -g)" -e HOME=/tmp -e SSL_CERT_DIR=/etc/probant/ca \
    -e HTTPS_PROXY -e HTTP_PROXY -e NO_PROXY -e https_proxy -e http_proxy -e no_proxy \
    -v "$d:/work:ro" $ca $key "$COSIGN_IMAGE" "$@"
}
# verify_sums VERSION FOLDER: signature of the list (FOLDER/sums) by the workflow image.yml of the public repository,
# for the tag of VERSION, with cosign of this machine, or else with its official container if Docker responds.
# Status 0: verified; 1: refused; 2: not verified, the reason in NOT_VERIFIED (no cosign and no Docker, no container of
# cosign, or cosign cannot read the trusted root of Sigstore). The output of cosign: FOLDER/cosign.log
verify_sums() {
  dir=$(cd "$2/sums" && pwd) || return 1
  list="probant-$1-files.sha256" ; log="$2/cosign.log"
  re=$(printf '%s' "$1" | sed 's/\./\\./g')
  if command -v cosign >/dev/null 2>&1; then
    COSIGN_MODE=host; at="$dir"; key="$TEST_KEY"
  elif command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
    COSIGN_MODE=container; at=/work; key=/run/probant-test.pub
    if ! docker image inspect "$COSIGN_IMAGE" >/dev/null 2>&1 && ! docker pull -q "$COSIGN_IMAGE" > "$log" 2>&1; then
      NOT_VERIFIED="the container of cosign could not be downloaded ($COSIGN_IMAGE)"; return 2
    fi
  else
    NOT_VERIFIED="no cosign and no Docker on this server"; return 2
  fi
  if [ -n "$TEST_KEY" ]; then
    set -- --key "$key" --insecure-ignore-tlog=true
  else
    set -- --certificate-identity-regexp "^https://github\\.com/$REPOSITORY/\\.github/workflows/image\\.yml@refs/tags/[vV]$re\$" \
      --certificate-oidc-issuer "$ISSUER"
    # cosign reads the trusted root of Sigstore first: if it cannot, the signature is not verified (it is not refused)
    if ! cosign_in "$dir" initialize > "$log" 2>&1; then
      NOT_VERIFIED="cosign could not read the trusted root of Sigstore (tuf-repo-cdn.sigstore.dev)"; return 2
    fi
  fi
  status=0
  cosign_in "$dir" verify-blob --bundle "$at/$list.sigstore.json" "$@" "$at/$list" >> "$log" 2>&1 || status=$?
  case "$status" in
    0) return 0 ;;
    125|126|127) NOT_VERIFIED="the container of cosign could not run"; return 2 ;;
    *) return 1 ;;
  esac
}
# verify_download VERSION FOLDER: the list of the release and its signature, then each file of FOLDER; says what was
# verified. Status 1, with the reason: nothing may be put in place
verify_download() {
  if ! download_sums "$1" "$2"; then
    echo "The release of version $1 has no list of the SHA-256 sums of its files, or no signature of this list"
    echo "($SOURCE/releases/tag/$TAG_FOUND). A version published before these lists cannot be installed this way."
    echo "A version published in the last hour may not have them yet: try again later."
    return 1
  fi
  status=0
  verify_sums "$1" "$2" || status=$?
  case "$status" in
    0) signature="verified (workflow image.yml of $REPOSITORY, tag $TAG_FOUND)" ;;
    2) signature="not verified: $NOT_VERIFIED" ;;
    *) echo "The signature of the list of the SHA-256 sums of version $1 was refused by cosign:"
       tail -5 "$2/cosign.log" 2>/dev/null || true
       return 1 ;;
  esac
  check_sums "$1" "$2" || return 1
  echo "Files checked: each one matches its SHA-256 sum in the list of the release; signature of the list $signature."
}

# before_check FOLDER: the download stopped at check.sh only: a version published before check.sh (its other files came)
before_check() { [ -f "$1/update.sh" ] && [ ! -f "$1/check.sh" ]; }

# ---- Checks before any change
if [ "$(uname -s)" != Linux ]; then
  echo "This script installs Probant on a Linux server. On another system, see docs/installation.md."; exit 1
fi
command -v curl >/dev/null 2>&1 || { echo "curl is missing: install it (apt-get install -y curl), then run this script again."; exit 1; }
if [ "$CHECK" = 0 ] && { [ -e "$DIR/.env" ] || [ -e "$DIR/.git" ]; }; then
  echo "The folder $DIR already holds an installation: nothing was changed. To update it: cd $DIR && ./update.sh"
  echo "To install a second time, choose another folder with --dir."; exit 1
fi

if [ -z "$VERSION" ]; then
  echo "Finding the latest version…"
  VERSION=$(latest_version) || { echo "The latest version could not be found ($SOURCE/releases): give it with --version X.Y.Z."; exit 1; }
fi
is_version "$VERSION" || { echo "Version \"$VERSION\" not valid: write it as X.Y.Z (for example 1.0.1)."; exit 2; }

# --check: check.sh of the version, from a temporary folder outside FOLDER, with the options of this installation
if [ "$CHECK" = 1 ]; then
  TMP=$(mktemp -d)
  trap 'rm -rf "$TMP"' EXIT
  trap 'rm -rf "$TMP"; exit 1' HUP INT TERM
  if ! download_files "$VERSION" "$TMP" || [ ! -f "$TMP/check.sh" ]; then
    if before_check "$TMP"; then
      echo "Version $VERSION came before the check of the server (check.sh): give a later version with --version, or"
      echo "check the server by hand (docs/installation.md, section 1)."; exit 1
    fi
    echo "The check of version $VERSION could not be downloaded from $SOURCE: check the version and the network"
    echo "(outgoing HTTPS to github.com and raw.githubusercontent.com, or HTTPS_PROXY)."; exit 1
  fi
  verify_download "$VERSION" "$TMP" || { echo "The check of the server was not run."; exit 1; }
  set -- --image "$IMAGE_NAME:$VERSION"
  if [ -n "$DOMAIN" ]; then set -- "$@" --domain "$DOMAIN"; fi
  if [ -n "$PORT" ]; then set -- "$@" --port "$PORT"; fi
  old_ifs="$IFS"; IFS="$NL"
  for a in $CERTIFICATE_OPTIONS; do set -- "$@" "$a"; done
  IFS="$old_ifs"
  status=0
  sh "$TMP/check.sh" "$@" || status=$?
  exit "$status"
fi

echo "Downloading the files of Probant $VERSION into $DIR…"
mkdir -p "$DIR"
TMP=$(mktemp -d "$DIR/.download.XXXXXX")
trap 'rm -rf "$TMP"' EXIT
trap 'rm -rf "$TMP"; exit 1' HUP INT TERM
download_files "$VERSION" "$TMP" || before_check "$TMP" \
  || { echo "The files of version $VERSION could not be downloaded from $SOURCE: check the version and the network."; exit 1; }
# the versions published before this script cannot install a published image this way (no --image option, no check.sh)
if [ ! -f "$TMP/check.sh" ] || ! grep -q -- '--image)' "$TMP/install.sh"; then
  echo "Version $VERSION came before this way of installing: nothing was installed. Install it with Git"
  echo "(docs/installation.md, \"Install with Git\"), or install a later version."; exit 1
fi
if [ -n "$CERTIFICATE_OPTIONS" ] && ! grep -q -- '--cert)' "$TMP/install.sh"; then
  echo "Version $VERSION came before --cert, --key and --ca-cert: nothing was installed. Install a later version."; exit 1
fi
download_optional "$TMP" || true
# every file checked against the list of the release before any of them is put in place
verify_download "$VERSION" "$TMP" || { echo "Nothing was installed."; exit 1; }
for f in $FILES $OPTIONAL_FILES; do
  if [ -f "$TMP/$f" ]; then
    mkdir -p "$DIR/$(dirname "$f")"
    mv -f "$TMP/$f" "$DIR/$f"
  fi
done
chmod 755 "$DIR/install.sh" "$DIR/update.sh" "$DIR/check.sh"
if [ -f "$DIR/auto-update.sh" ]; then chmod 755 "$DIR/auto-update.sh"; fi

# install.sh, with the published image of this version and the options given
set -- --image "$IMAGE_NAME:$VERSION"
if [ -n "$DOMAIN" ]; then set -- "$@" --domain "$DOMAIN"; fi
if [ -n "$PORT" ]; then set -- "$@" --port "$PORT"; fi
if [ "$YES" = 1 ]; then set -- "$@" --yes; fi
if [ "$SKIP_CHECK" = 1 ]; then set -- "$@" --skip-check; fi
# automatic updates: versions since auto-update.sh only (install.sh with --auto-update)
if [ -f "$DIR/auto-update.sh" ] && grep -q -- '--auto-update)' "$DIR/install.sh"; then set -- "$@" --auto-update "$AUTO_UPDATE"; fi
old_ifs="$IFS"; IFS="$NL"
for a in $CERTIFICATE_OPTIONS; do set -- "$@" "$a"; done
IFS="$old_ifs"
echo "Running $DIR/install.sh…"
rm -rf "$TMP"
trap - EXIT HUP INT TERM
exec sh "$DIR/install.sh" "$@"
