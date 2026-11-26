#!/usr/bin/env sh
# Updates Probant, in one command: ./update.sh
#   1. backs up each space with the version installed now ("before-update" archives in /data/backups, and
#      /data/backups/spaces/<code> for the other spaces);
#   2. new version: published image (IMAGE= in .env) or the repository code (git pull), rebuilt;
#   3. restart: the database migrations apply on their own; waits until the tool responds.
# Installation made by get.sh (no Git folder, IMAGE= set to a version X.Y.Z of the published image): step 2 downloads
# the files of the latest version (or of the version given with --version X.Y.Z), checks each one against the list of
# the SHA-256 sums of the release of that version (and the signature of the list, with cosign of the server or its
# official container, when that is possible), keeps .env and the data, and sets IMAGE= to the image of that version.
# No list, a refused signature, or one file that does not match: nothing is put in place (exit code 3).
# Without Internet access: ./update.sh --offline ARCHIVE, with the archive of the image of the new offline package
# (probant-image-X.Y.Z.tar.gz, in the extracted folder of the package): step 2 checks the package against its
# SHA256SUMS, puts its files in place, loads the image (docker load) and sets IMAGE=; nothing is downloaded.
# --digest sha256:… (with --version, used by auto-update.sh): IMAGE= pinned to that digest of the image, the one whose
# signature was verified. --sums FILE (with --version, used by auto-update.sh): the list of sums of that version, whose
# signature auto-update.sh verified; the files are checked against it. One update at a time: lock .update.lock, shared
# with auto-update.sh.
# If something goes wrong: docs/installation.md, "Going back to the previous version".
set -eu
START="$(pwd)"
cd "$(dirname "$0")"

TARGET="" ; OFFLINE_ARCHIVE="" ; DIGEST="" ; SUMS_FILE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --version) [ $# -ge 2 ] || { echo "The option --version needs a value (X.Y.Z)."; exit 2; }; TARGET="${2#[vV]}"; shift 2 ;;
    --offline)
      [ $# -ge 2 ] || { echo "The option --offline needs the archive of the image (probant-image-X.Y.Z.tar.gz)."; exit 2; }
      case "$2" in /*) OFFLINE_ARCHIVE="$2" ;; *) OFFLINE_ARCHIVE="$START/$2" ;; esac; shift 2 ;;
    --digest)
      [ $# -ge 2 ] || { echo "The option --digest needs a value (sha256:…)."; exit 2; }
      printf '%s\n' "$2" | grep -Eqx 'sha256:[0-9a-f]{64}' || { echo "--digest: write it as sha256: and 64 hexadecimal digits."; exit 2; }
      DIGEST="$2"; shift 2 ;;
    --sums)
      [ $# -ge 2 ] || { echo "The option --sums needs the list of the SHA-256 sums of the version."; exit 2; }
      case "$2" in /*) SUMS_FILE="$2" ;; *) SUMS_FILE="$START/$2" ;; esac; shift 2 ;;
    -h|--help) sed -n '2,19p' "$0"; exit 0 ;;
    *) echo "Unknown option: $1 (see ./update.sh --help)"; exit 2 ;;
  esac
done

[ -f .env ] || { echo "No .env file: run ./install.sh first"; exit 1; }

# ---- Lock shared with auto-update.sh (the same functions there): one update at a time. A lock whose process is gone is
# taken again; a lock without a process number yet is respected for 10 minutes. auto-update.sh, which holds the lock,
# runs this script with PROBANT_UPDATE_LOCK_OWNER set to its process number.
LOCK=.update.lock
alive() { case "$1" in ''|*[!0-9]*) return 1 ;; esac; kill -0 "$1" 2>/dev/null || [ -d "/proc/$1" ]; }
take_lock() {
  if mkdir "$LOCK" 2>/dev/null; then echo "$$" > "$LOCK/pid"; return 0; fi
  holder=$(cat "$LOCK/pid" 2>/dev/null || true)
  if alive "$holder"; then return 1; fi
  if [ -z "$holder" ] && [ -n "$(find "$LOCK" -maxdepth 0 -mmin -10 2>/dev/null)" ]; then return 1; fi
  rm -rf "$LOCK" && mkdir "$LOCK" 2>/dev/null && echo "$$" > "$LOCK/pid"
}
release_lock() { if [ "$(cat "$LOCK/pid" 2>/dev/null || true)" = "$$" ]; then rm -rf "$LOCK"; fi; }
TMP=""
# shellcheck disable=SC2329 # called by the traps below
cleanup() { if [ -n "$TMP" ]; then rm -rf "$TMP"; fi; release_lock; }
if [ -n "${PROBANT_UPDATE_LOCK_OWNER:-}" ] && [ "$(cat "$LOCK/pid" 2>/dev/null || true)" = "$PROBANT_UPDATE_LOCK_OWNER" ]; then
  trap 'if [ -n "$TMP" ]; then rm -rf "$TMP"; fi' EXIT  # run by auto-update.sh, which holds the lock
elif take_lock; then
  trap cleanup EXIT
  trap 'cleanup; exit 1' HUP INT TERM
else
  echo "Another update is running (lock $LOCK, process $(cat "$LOCK/pid" 2>/dev/null || echo '?'), for example the automatic"
  echo "update of the night). Nothing was changed: try again when it ends (log: auto-update.log)."; exit 1
fi
chmod 600 .env 2>/dev/null || true  # passwords inside (SMTP, PostgreSQL): readable by its owner only

# owner_of FILE: its owner and group (numbers), to give them back to a file that replaces it when this script runs as
# root (automatic update of the night, for an installation made by a member of the group docker); empty otherwise
# shellcheck disable=SC2012 # one file named by this script; only the numbers of its owner and group are read (POSIX ls)
owner_of() { if [ "$(id -u)" = 0 ] && [ -e "$1" ]; then ls -lnd "$1" | awk '{ print $3 ":" $4 }'; fi; }
# put_in_place NEW FILE MODE: NEW renamed to FILE, with MODE (the rights that get.sh gives, whatever the umask: an
# automatic update runs with umask 077) and the owner of the file it replaces (or of this folder for a new file)
put_in_place() {
  owner=$(owner_of "$2"); if [ -z "$owner" ]; then owner=$(owner_of .); fi
  chmod "$3" "$1" && mv -f "$1" "$2" || return 1
  if [ -n "$owner" ]; then chown "$owner" "$2" 2>/dev/null || true; fi
}
mode_of() { case "$1" in *.sh) echo 755 ;; *) echo 644 ;; esac; }
set_value() {
  if grep -q "^$1=" .env; then
    owner=$(owner_of .env)
    sed "s|^$1=.*|$1=$2|" .env > .env.tmp && chmod 600 .env.tmp && mv .env.tmp .env
    if [ -n "$owner" ]; then chown "$owner" .env 2>/dev/null || true; fi
  else echo "$1=$2" >> .env; fi
}

# ---- Installation made by get.sh: the version comes with the files of its tag (the same values and functions in get.sh)
# The two PROBANT_TEST_ variables are reserved for the tests of the scripts: leave them unset.
SOURCE="${PROBANT_TEST_SOURCE:-https://github.com/Probant-Reporting/probant}"
IMAGE_NAME="${PROBANT_TEST_IMAGE:-ghcr.io/probant-reporting/probant}"
FILES="docker-compose.yml .env.example install.sh update.sh check.sh docker/Caddyfile"
# files of a version since the automatic updates (the versions before do not have them)
OPTIONAL_FILES="auto-update.sh"
# authorities of the company (docs/installation.md, "Company network"), for cosign in its container
CA_DIR="$(pwd)/certificates/ca"
PROTO="=https"
if [ -n "${PROBANT_TEST_SOURCE:-}" ]; then PROTO="=http,https"; fi
is_version() { printf '%s\n' "$1" | grep -Eqx '[0-9]+\.[0-9]+\.[0-9]+'; }
fetch() { curl -fsSL --connect-timeout 20 --retry 3 --retry-max-time 60 --proto "$PROTO" --proto-redir "$PROTO" -o "$2" "$1"; }
latest_version() {
  url=$(curl -fsSL --connect-timeout 20 --retry 3 --retry-max-time 60 --proto "$PROTO" --proto-redir "$PROTO" -o /dev/null -w '%{url_effective}' "$SOURCE/releases/latest") || return 1
  v="${url##*/tag/}"; v="${v#[vV]}"
  is_version "$v" && echo "$v"
}
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
# older A B: version A comes before version B
older() { [ "$1" != "$2" ] && [ "$(printf '%s\n%s\n' "$1" "$2" | sort -t. -k1,1n -k2,2n -k3,3n | head -1)" = "$1" ]; }

# ---- Offline package (the same functions in install.sh): every file checked against SHA256SUMS before any change
check_package() {
  dir=$(dirname "$1")
  if [ ! -f "$1" ]; then echo "Archive not found: $1. Nothing was changed."; return 1; fi
  if [ ! -f "$dir/SHA256SUMS" ] || ! awk -v f="$(basename "$1")" '{ n = $2; sub(/^[*]/, "", n) } n == f { found = 1 } END { exit !found }' "$dir/SHA256SUMS"; then
    echo "$(basename "$1") is not listed in $dir/SHA256SUMS: this is not the archive of an offline package. Nothing was changed."; return 1
  fi
  command -v sha256sum >/dev/null 2>&1 || { echo "sha256sum is missing (package coreutils): the package cannot be checked. Nothing was changed."; return 1; }
  if ! (cd "$dir" && sha256sum -c --quiet SHA256SUMS); then
    echo "The files of the package do not match SHA256SUMS (damaged or changed copy). Nothing was changed: copy the package again."; return 1
  fi
}
load_image() {
  out=$(docker load -i "$1") || { echo "docker load failed for $1." >&2; return 1; }
  name=$(printf '%s\n' "$out" | sed -n 's/^Loaded image: //p')
  if [ "$(printf '%s\n' "$name" | grep -c .)" != 1 ]; then
    echo "The archive must hold exactly one named image (docker load gave: $out)." >&2; return 1
  fi
  printf '%s\n' "$name"
}

IMAGE_NOW=$(grep "^IMAGE=" .env | tail -1 | cut -d= -f2- || true)
INSTALLED=""
# tag of the image, without a pinned digest (IMAGE=name:X.Y.Z@sha256:…, set by --digest)
case "$IMAGE_NOW" in "$IMAGE_NAME":*) INSTALLED="${IMAGE_NOW#"$IMAGE_NAME":}"; INSTALLED="${INSTALLED%%@*}" ;; esac
RELEASE=0
if [ ! -d .git ] && is_version "$INSTALLED"; then RELEASE=1; fi
PACKAGE=""
if [ -n "$OFFLINE_ARCHIVE" ]; then
  RELEASE=0
  if [ -n "$TARGET" ]; then echo "--offline and --version do not go together: the version is the one of the package."; exit 2; fi
  if [ -d .git ]; then echo "This folder is a Git clone: update it with ./update.sh (git pull). Nothing was changed."; exit 2; fi
  check_package "$OFFLINE_ARCHIVE" || exit 1
  PACKAGE=$(dirname "$OFFLINE_ARCHIVE")
  TARGET=$(cat "$PACKAGE/VERSION" 2>/dev/null || true)
  is_version "$TARGET" || { echo "No version in $PACKAGE/VERSION: this is not an offline package. Nothing was changed."; exit 1; }
  # installed version: the tag of the image in .env (any image name: published, or loaded from an offline package)
  NOW_TAG="${IMAGE_NOW%%@*}"; NOW_TAG="${NOW_TAG##*:}"
  if is_version "$NOW_TAG" && older "$TARGET" "$NOW_TAG"; then
    echo "Version $TARGET is older than the installed version $NOW_TAG: nothing was changed."
    echo "To go back to an earlier version, follow docs/installation.md, \"Going back to the previous version\"."; exit 1
  fi
fi
if [ "$RELEASE" = 1 ]; then
  command -v curl >/dev/null 2>&1 || { echo "curl is missing: install it (apt-get install -y curl), then run ./update.sh again."; exit 1; }
  if [ -z "$TARGET" ]; then
    TARGET=$(latest_version) || { echo "The latest version could not be found ($SOURCE/releases): nothing was changed. Give it with --version X.Y.Z."; exit 1; }
  fi
  is_version "$TARGET" || { echo "Version \"$TARGET\" not valid: write it as X.Y.Z."; exit 2; }
  if older "$TARGET" "$INSTALLED"; then
    echo "Version $TARGET is older than the installed version $INSTALLED: nothing was changed."
    echo "To go back to an earlier version, follow docs/installation.md, \"Going back to the previous version\"."; exit 1
  fi
  if [ "$TARGET" = "$INSTALLED" ]; then echo "Version $INSTALLED is the latest: the tool restarts with the same version."; fi
elif [ -n "$DIGEST" ] || [ -n "$SUMS_FILE" ]; then
  echo "--digest and --sums are for an installation made by get.sh, with --version. Nothing was changed."; exit 2
elif [ -n "$TARGET" ] && [ -z "$PACKAGE" ]; then
  echo "--version is for an installation made by get.sh (no Git folder, IMAGE= set to a version of $IMAGE_NAME)."
  echo "Here: set IMAGE= in .env, or use git. Nothing was changed."; exit 2
fi

echo "Current version: $(docker compose exec -T web cat /app/VERSION 2>/dev/null || echo 'service stopped')"

# Commands in the version currently installed: in the running service, or, if the tool is stopped, in the image of
# that version. No --no-deps: with the "postgres" profile, the database starts too (otherwise the backup cannot reach it).
running=0
if docker compose ps --status running --services 2>/dev/null | grep -qx web; then running=1; fi
# in_tool <space code, empty for the main space> <command…>
in_tool() {
  space="$1"; shift
  if [ "$running" = 1 ]; then
    docker compose exec -T ${space:+-e SPACE=$space} web "$@"
  else
    docker compose run --rm -T ${space:+-e SPACE=$space} web "$@"
  fi
}

# backup in the version currently installed; a version from before the update only knows the French command name
echo "1. Backup before the update…"
in_tool "" python manage.py backup --reason before-update 2>/dev/null \
  || in_tool "" python manage.py sauvegarde --motif avant-mise-a-jour
# Every other space too (versions with spaces), with the same version, so that going back can restore
# every space. Codes read from "spaces --list" (lines with the address /espace/<code>/); a version without spaces has no
# such command: nothing more to back up. A failed backup stops the update before any change.
spaces=$(in_tool "" python manage.py spaces --list 2>/dev/null \
  | awk '$1 ~ /^[a-z][a-z0-9]+$/ && length($1) <= 20 && index($0, "/espace/" $1 "/") > 0 { print $1 }' || true)
for code in $spaces; do
  echo "   space \"$code\"…"
  if ! in_tool "$code" python manage.py backup --reason before-update; then
    echo "The backup of the space \"$code\" failed: the update stopped, nothing was changed."
    echo "Read the message above, fix the cause (disk space…), then run ./update.sh again. Guide: docs/installation.md, \"Troubleshooting\"."
    exit 1
  fi
done

echo "2. New version…"
if [ -n "$PACKAGE" ]; then
  # image of the package first (if it does not load, nothing else changes), then its files (unless the package is
  # this folder); nothing is downloaded
  LOADED=$(load_image "$OFFLINE_ARCHIVE")
  # image of Caddy (HTTPS) of the package, when it has one (packages of earlier versions: none)
  if [ -f "$PACKAGE/caddy-image.tar.gz" ]; then load_image "$PACKAGE/caddy-image.tar.gz" >/dev/null; fi
  if [ "$(cd "$PACKAGE" && pwd)" != "$(pwd)" ]; then
    for f in $FILES; do
      (umask 022 && mkdir -p "$(dirname "$f")")
      cp "$PACKAGE/$f" "$f.new" && put_in_place "$f.new" "$f" "$(mode_of "$f")"
    done
  fi
  set_value IMAGE "$LOADED"
  echo "   files of version $TARGET in place; image $LOADED loaded from $(basename "$OFFLINE_ARCHIVE") (before: ${IMAGE_NOW:-none})"
elif [ "$RELEASE" = 1 ] && [ "$TARGET" != "$INSTALLED" ]; then
  # files of the new version: all downloaded first, then put in place (renamed: this running script keeps its copy)
  TMP=$(mktemp -d ./.download.XXXXXX)
  download_files "$TARGET" "$TMP" || { echo "The files of version $TARGET could not be downloaded from $SOURCE: nothing was changed."; exit 1; }
  download_optional "$TMP" || true
  # every file checked against the list of the release before any of them is put in place; with --sums, against the
  # list that auto-update.sh downloaded and whose signature it verified
  if [ -n "$SUMS_FILE" ]; then
    mkdir -p "$TMP/sums"
    cp "$SUMS_FILE" "$TMP/sums/probant-$TARGET-files.sha256" 2>/dev/null || { echo "No list of sums $SUMS_FILE. Nothing was changed."; exit 3; }
    check_sums "$TARGET" "$TMP" || { echo "Nothing was changed."; exit 3; }
    echo "   files checked: each one matches its SHA-256 sum in the list verified by auto-update.sh"
  else
    verify_download "$TARGET" "$TMP" || { echo "Nothing was changed."; exit 3; }
  fi
  for f in $FILES $OPTIONAL_FILES; do
    if [ -f "$TMP/$f" ]; then
      (umask 022 && mkdir -p "$(dirname "$f")")
      put_in_place "$TMP/$f" "$f" "$(mode_of "$f")"
    fi
  done
  set_value IMAGE "$IMAGE_NAME:$TARGET${DIGEST:+@$DIGEST}"
  echo "   files of version $TARGET in place; image $IMAGE_NAME:$TARGET${DIGEST:+@$DIGEST} (before: $IMAGE_NOW)"
elif [ "$RELEASE" = 1 ] && [ -n "$DIGEST" ]; then
  set_value IMAGE "$IMAGE_NAME:$TARGET@$DIGEST"
  echo "   image $IMAGE_NAME:$TARGET@$DIGEST (before: $IMAGE_NOW)"
fi
if [ -n "$PACKAGE" ]; then
  :  # image loaded from the package: nothing to download
elif grep -q "^IMAGE=..*" .env; then
  docker compose pull web
else
  if [ -d .git ]; then git pull --ff-only; fi
  set_value VERSION_COMMIT "$(git rev-parse HEAD 2>/dev/null || echo '')"
  docker compose build web
fi

echo "3. Restart (automatic migrations)…"
# folders of the certificates given by the IT (docker-compose.yml mounts them): made here if missing, with the rights
# that install.sh gives them, so that Docker does not make them owned by root (docs/installation.md, "Company
# network"). A folder already there keeps its rights; one that cannot be made does not stop the update.
for d in certificates certificates/ca certificates/https; do
  [ ! -d "$d" ] || continue
  case "$d" in */https) m=700 ;; *) m=755 ;; esac
  owner=$(owner_of .)
  if mkdir "$d" 2>/dev/null && chmod "$m" "$d"; then
    if [ -n "$owner" ]; then chown "$owner" "$d" 2>/dev/null || true; fi
  else
    echo "   The folder $d could not be made by this user: to add a certificate there later, run ./install.sh with sudo, or first run: sudo chown -R $(id -u):$(id -g) certificates"
  fi
done
if [ -n "$PACKAGE" ]; then docker compose up -d --pull never; else docker compose up -d; fi
i=0
until docker compose exec -T web python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/sante/', timeout=3)" >/dev/null 2>&1; do
  i=$((i + 1))
  # PROBANT_TEST_HEALTH_TRIES: reserved for the tests of the scripts (a shorter wait), leave it unset
  if [ "$i" -gt "${PROBANT_TEST_HEALTH_TRIES:-90}" ]; then echo "The tool is not responding after 3 minutes. Log: docker compose logs web"; exit 1; fi
  sleep 2
done
echo "Update complete: version $(docker compose exec -T web cat /app/VERSION)."
if [ -n "$PACKAGE" ] || { [ "$RELEASE" = 1 ] && [ "$TARGET" != "$INSTALLED" ]; }; then
  echo "Image before the update: $IMAGE_NOW (to go back: docs/installation.md, \"Going back to the previous version\")."
fi
