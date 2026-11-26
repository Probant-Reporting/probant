#!/bin/sh
# Automatic update of Probant, run by a timer of the server (systemd, otherwise cron) that install.sh sets up:
#   ./install.sh --auto-update on [--auto-update-time HH:MM]   every night at about HH:MM (default 04:00), random delay
#   ./install.sh --auto-update off                             removes the timer
# By hand, in the folder of the tool:
#   ./auto-update.sh            one run now (the same as the timer)
#   ./auto-update.sh --retry    one run now, and tries again a version whose automatic update failed before
#   ./auto-update.sh --status   shows the last result
#
# One run, in this order (log: auto-update.log in this folder, and the journal of the timer):
#  1. Stops if another update runs (lock .update.lock, shared with update.sh), if this installation does not use a
#     published version (Git, offline package, other image), if the tool is stopped, or if the administrator chose
#     "off" (Settings > Hosting, "Automatic updates"; file auto-update/choice of the data volume).
#  2. Finds the latest published version (as update.sh does) and downloads its image. Same image digest as the one that
#     runs: nothing to do. Version numbers are never compared here: only image digests.
#  3. Verifies the signature of the new image with cosign, in the official cosign container pinned by its digest: the
#     image must be signed by the workflow image.yml of the public repository, for the tag of this version, with the
#     GitHub OIDC issuer. No verified signature (absent, wrong, or verification impossible): nothing is installed.
#  4. "Notify only", a version published less than N days ago (choice of the administrator), a version that already
#     failed, or a version that changes the shared registry (accounts) in a way that cannot be undone: stops here; the
#     tool shows the new version.
#  5. Never during a restore, a backup, a large import or a large export of the tool: tries again the next night.
#  6. Downloads the list of the SHA-256 sums of the files of the new version (release of its tag) and verifies its
#     signature, with the same container and the same identity. No list, or no verified signature: nothing is installed.
#  7. Runs ./update.sh with this list (backup "before-update" of each space; files of the new version, each one checked
#     against the list before any is put in place; image pinned by its digest), then checks /sante/ twice, 30 seconds
#     apart.
#  8. On failure: back to the files and the image of before; if the new version changed the structure of a database
#     (fingerprint of its migrations), restore of the "before-update" backup of each changed space; then checks /sante/.
# The result goes to the file auto-update/result of the data volume (read by the tool: Settings > Hosting, Health,
# email alerts). The container of the tool never calls outside and never reaches Docker: only this script, on the
# server, does. Guide: docs/installation.md, "Automatic updates".
set -u
cd "$(dirname "$0")" || exit 1
HERE="$(pwd)"

# Public repository, image and verifier. The PROBANT_TEST_ variables are reserved for the tests of the scripts (local
# copy of the repository, local registry, test key of cosign): leave them unset. The two cosign variables are read only
# with PROBANT_TEST_IMAGE: the published image is always verified against the identity of the public repository.
SOURCE="${PROBANT_TEST_SOURCE:-https://github.com/Probant-Reporting/probant}"
IMAGE_NAME="${PROBANT_TEST_IMAGE:-ghcr.io/probant-reporting/probant}"
REPOSITORY="Probant-Reporting/probant"
ISSUER="https://token.actions.githubusercontent.com"
# official image of cosign (Sigstore), version 3.1.5, pinned by the digest of its multi-platform index
COSIGN_IMAGE="ghcr.io/sigstore/cosign/cosign:v3.1.5@sha256:191099139868a6cd02abae63f2919e0915dcaa7bcc22bda6fbd11fd0dd5599e7"
TEST_KEY=""
if [ -n "${PROBANT_TEST_IMAGE:-}" ]; then
  COSIGN_IMAGE="${PROBANT_TEST_COSIGN_IMAGE:-$COSIGN_IMAGE}"
  TEST_KEY="${PROBANT_TEST_COSIGN_KEY:-}"
fi
PROTO="=https"
if [ -n "${PROBANT_TEST_SOURCE:-}" ]; then PROTO="=http,https"; fi
STATE=.auto-update   # this script's own files: files of before the update, failed digest, state, task
LOG=auto-update.log
LOCK=.update.lock
HEALTH_TRIES="${PROBANT_TEST_HEALTH_TRIES:-90}"   # 2 seconds each: 3 minutes
STABLE_WAIT="${PROBANT_TEST_STABLE_WAIT:-30}"
FILES="docker-compose.yml .env.example install.sh update.sh check.sh docker/Caddyfile auto-update.sh"

RETRY=0 ; RECORD=""
case "${1:-}" in
  "") ;;
  --retry) RETRY=1 ;;
  --status)
    if [ -f "$STATE/last" ]; then cat "$STATE/last"; else echo "No result yet."; fi
    exit 0 ;;
  --record) [ $# -ge 2 ] || exit 2; RECORD="$2" ;;  # used by install.sh: "installed" or "task_removed"
  -h|--help) sed -n '2,32p' "$0"; exit 0 ;;
  *) echo "Unknown option: $1 (see ./auto-update.sh --help)"; exit 2 ;;
esac

umask 077
mkdir -p "$STATE"
now() { date -u +%Y-%m-%dT%H:%M:%SZ; }
log() {
  line="$(now) $*"
  printf '%s\n' "$line"
  printf '%s\n' "$line" >> "$LOG"
}
# log kept under about 1 MB: the last 4000 lines
if [ -f "$LOG" ] && [ "$(wc -c < "$LOG")" -gt 1000000 ]; then
  tail -n 4000 "$LOG" > "$LOG.tmp" && mv -f "$LOG.tmp" "$LOG"
fi

is_version() { printf '%s\n' "$1" | grep -Eqx '[0-9]+\.[0-9]+\.[0-9]+'; }
is_digest() { printf '%s\n' "$1" | grep -Eqx 'sha256:[0-9a-f]{64}'; }
latest_version() {
  url=$(curl -fsSL --connect-timeout 20 --retry 3 --retry-max-time 60 --proto "$PROTO" --proto-redir "$PROTO" -o /dev/null -w '%{url_effective}' "$SOURCE/releases/latest") || return 1
  v="${url##*/tag/}"; v="${v#[vV]}"
  is_version "$v" && echo "$v"
}

# ---- Lock shared with update.sh (the same functions there): one update at a time. A lock whose process is gone is
# taken again; a lock without a process number yet is respected for 10 minutes.
alive() { case "$1" in ''|*[!0-9]*) return 1 ;; esac; kill -0 "$1" 2>/dev/null || [ -d "/proc/$1" ]; }
take_lock() {
  if mkdir "$LOCK" 2>/dev/null; then echo "$$" > "$LOCK/pid"; return 0; fi
  holder=$(cat "$LOCK/pid" 2>/dev/null || true)
  if alive "$holder"; then return 1; fi
  if [ -z "$holder" ] && [ -n "$(find "$LOCK" -maxdepth 0 -mmin -10 2>/dev/null)" ]; then return 1; fi
  rm -rf "$LOCK" && mkdir "$LOCK" 2>/dev/null && echo "$$" > "$LOCK/pid"
}
# shellcheck disable=SC2329 # called by the trap below
release_lock() { if [ "$(cat "$LOCK/pid" 2>/dev/null || true)" = "$$" ]; then rm -rf "$LOCK"; fi; }

# ---- The tool, through Docker Compose (only this script reaches Docker, never the container)
web_running() { docker compose ps --status running --services 2>/dev/null | grep -qx web; }
# tool_sh COMMAND: a fixed shell command (never built from data) in the container of the tool, or in its image if the
# tool is stopped (no database started); the input goes to the command
tool_sh() {
  if web_running; then docker compose exec -T web sh -c "$1"
  else docker compose run --rm -T --no-deps --entrypoint sh web -c "$1"; fi
}
# manage COMMAND…: a command of the tool, in the running service or in its image (database started if needed)
manage() {
  if web_running; then docker compose exec -T web python manage.py "$@"
  else docker compose run --rm -T web python manage.py "$@"; fi
}
manage_space() {  # manage_space CODE COMMAND…: the same in the space CODE (main space: principal)
  code="$1"; shift
  if [ "$code" = principal ]; then manage "$@"; return; fi
  if web_running; then docker compose exec -T -e SPACE="$code" web python manage.py "$@"
  else docker compose run --rm -T -e SPACE="$code" web python manage.py "$@"; fi
}
healthy() {  # healthy TRIES: /sante/ answers 200 (2 seconds between tries)
  n=0
  until docker compose exec -T web python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/sante/', timeout=5)" >/dev/null 2>&1; do
    n=$((n + 1))
    if [ "$n" -ge "$1" ]; then return 1; fi
    sleep 2
  done
}
running_image() { c=$(docker compose ps -q web 2>/dev/null | head -1); [ -n "$c" ] && docker inspect -f '{{.Image}}' "$c" 2>/dev/null; }

# ---- Choice of the administrator (written by the tool: untrusted input, closed values only, nothing evaluated)
read_choice() {
  MODE=off ; DELAY=3
  text=$(tool_sh 'cat /data/auto-update/choice 2>/dev/null || true' 2>/dev/null | head -c 2048) || text=""
  old_ifs="$IFS"; IFS='
'
  for line in $text; do
    case "$line" in
      mode=automatic|mode=notify|mode=off) MODE="${line#mode=}" ;;
      delay=0|delay=1|delay=3|delay=7|delay=14) DELAY="${line#delay=}" ;;
    esac
  done
  IFS="$old_ifs"
}

# ---- Result for the tool (file auto-update/result of the data volume, at most 4 KB, one key=value per line)
TASK=manual ; TASK_TIME=""
if [ -f "$STATE/task" ]; then
  read -r t tt < "$STATE/task" || true
  case "$t" in systemd|cron|none) TASK="$t" ;; esac
  case "${tt:-}" in [0-2][0-9]:[0-5][0-9]) TASK_TIME="$tt" ;; esac
fi
INSTALLED="" ; INSTALLED_DIGEST="" ; AVAILABLE="" ; AVAILABLE_DIGEST="" ; AFTER="" ; PREVIOUS="" ; RESTORED=""
finish() {  # finish STATE [REASON]: writes the result, logs it, stops
  state="$1"; reason="${2:-}"
  since=$(now)
  if [ -f "$STATE/since" ]; then
    read -r s_state s_since < "$STATE/since" || true
    if [ "${s_state:-}" = "$state" ] && printf '%s\n' "${s_since:-}" | grep -Eqx '[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:]{8}Z'; then since="$s_since"; fi
  fi
  echo "$state $since" > "$STATE/since"
  {
    echo "format=1"
    echo "task=$TASK"
    if [ -n "$TASK_TIME" ]; then echo "time=$TASK_TIME"; fi
    echo "checked=$(now)"
    echo "since=$since"
    echo "state=$state"
    if [ -n "$reason" ]; then echo "reason=$reason"; fi
    if is_version "$INSTALLED"; then echo "installed=$INSTALLED"; fi
    if is_digest "$INSTALLED_DIGEST"; then echo "installed_digest=$INSTALLED_DIGEST"; fi
    if is_version "$AVAILABLE"; then echo "available=$AVAILABLE"; fi
    if is_digest "$AVAILABLE_DIGEST"; then echo "available_digest=$AVAILABLE_DIGEST"; fi
    if [ -n "$AFTER" ]; then echo "install_after=$AFTER"; fi
    if is_version "$PREVIOUS"; then echo "previous=$PREVIOUS"; fi
    if [ -n "$RESTORED" ]; then echo "restored=$RESTORED"; fi
  } > "$STATE/last"
  if head -c 4096 "$STATE/last" | tool_sh 'umask 077 && mkdir -p /data/auto-update && cat > /data/auto-update/.result.new && mv -f /data/auto-update/.result.new /data/auto-update/result' >/dev/null 2>&1; then
    log "Result: $state${reason:+ ($reason)}"
  else
    log "Result: $state${reason:+ ($reason)} (could not be written into the data volume: the tool does not show it)"
  fi
  exit 0
}

# ---- Dates (the window of N days): days since 1970-01-01 of a date YYYY-MM-DD, and back
days_of() { printf '%s\n' "$1" | awk -F- '{ y = $1 + 0; m = $2 + 0; d = $3 + 0; a = int((14 - m) / 12); y = y + 4800 - a; m = m + 12 * a - 3;
  print d + int((153 * m + 2) / 5) + 365 * y + int(y / 4) - int(y / 100) + int(y / 400) - 32045 - 2440588 }'; }
date_of() { echo "$1" | awk '{ j = $1 + 2440588 + 32044; g = int(j / 146097); dg = j % 146097; c = int((int(dg / 36524) + 1) * 3 / 4);
  dc = dg - c * 36524; b = int(dc / 1461); db = dc % 1461; a = int((int(db / 365) + 1) * 3 / 4); da = db - a * 365;
  y = g * 400 + c * 100 + b * 4 + a; m = int((da * 5 + 308) / 153) - 2; d = da - int((m + 4) * 153 / 5) + 122;
  y = y - 4800 + int((m + 2) / 12); m = (m + 2) % 12 + 1; d = d + 1; printf "%04d-%02d-%02d\n", y, m, d }'; }

# ---- Signature of the new image: cosign in its official container (pinned by digest), read only, no capability
verify_signature() {  # verify_signature IMAGE@DIGEST VERSION
  if ! docker image inspect "$COSIGN_IMAGE" >/dev/null 2>&1 && ! docker pull -q "$COSIGN_IMAGE" >> "$LOG" 2>&1; then
    log "The image of cosign could not be downloaded ($COSIGN_IMAGE)."
    return 2
  fi
  v_re=$(printf '%s' "$2" | sed 's/\./\\./g')
  if [ -n "$TEST_KEY" ]; then
    # tests only (PROBANT_TEST_IMAGE): a test key instead of the identity of the workflow; local registry over HTTP
    set -- verify --key /run/probant-test.pub --insecure-ignore-tlog=true --allow-http-registry "$1"
    mount_key="-v $TEST_KEY:/run/probant-test.pub:ro"
  else
    set -- verify "$1" \
      --certificate-identity-regexp "^https://github\\.com/$REPOSITORY/\\.github/workflows/image\\.yml@refs/tags/[vV]$v_re\$" \
      --certificate-oidc-issuer "$ISSUER"
    mount_key=""
  fi
  ca=""
  if [ -d "$HERE/certificates/ca" ]; then ca="-v $HERE/certificates/ca:/etc/probant/ca:ro"; fi
  # shellcheck disable=SC2086 # $mount_key and $ca: options without spaces (paths checked by install.sh)
  docker run --rm --network host --read-only --tmpfs /tmp --cap-drop ALL --security-opt no-new-privileges \
    -e HOME=/tmp -e SSL_CERT_DIR=/etc/probant/ca -e HTTPS_PROXY -e HTTP_PROXY -e NO_PROXY -e https_proxy -e http_proxy -e no_proxy \
    $mount_key $ca "$COSIGN_IMAGE" "$@" >> "$LOG" 2>&1
}

# ---- List of the SHA-256 sums of the files of the new version (release of its tag, made and signed by image.yml):
# downloaded into .auto-update/sums, its signature verified with the same container and the same identity as the image;
# update.sh then checks each file that it downloads against it (--sums). The test key is read only with a test image
# and a test copy of the repository.
SUMS_DIR="$STATE/sums"
download_sums() {  # download_sums VERSION: the list and its signature, from the release of the tag vX.Y.Z (or VX.Y.Z)
  rm -rf "$SUMS_DIR" && mkdir -p "$SUMS_DIR" || return 1
  for tag in "v$1" "V$1"; do
    got=0
    for s in "probant-$1-files.sha256" "probant-$1-files.sha256.sigstore.json"; do
      curl -fsSL --connect-timeout 20 --retry 3 --retry-max-time 60 --proto "$PROTO" --proto-redir "$PROTO" \
        -o "$SUMS_DIR/$s" "$SOURCE/releases/download/$tag/$s" 2>/dev/null && got=$((got + 1))
    done
    if [ "$got" = 2 ]; then return 0; fi
  done
  return 1
}
verify_sums() {  # verify_sums VERSION: 0 verified, 1 refused, 2 the verification could not run
  if ! docker image inspect "$COSIGN_IMAGE" >/dev/null 2>&1 && ! docker pull -q "$COSIGN_IMAGE" >> "$LOG" 2>&1; then
    log "The image of cosign could not be downloaded ($COSIGN_IMAGE)."
    return 2
  fi
  list="probant-$1-files.sha256"
  v_re=$(printf '%s' "$1" | sed 's/\./\\./g')
  if [ -n "$TEST_KEY" ] && [ -n "${PROBANT_TEST_SOURCE:-}" ]; then
    set -- verify-blob --key /run/probant-test.pub --insecure-ignore-tlog=true
    mount_key="-v $TEST_KEY:/run/probant-test.pub:ro"
  else
    set -- verify-blob \
      --certificate-identity-regexp "^https://github\\.com/$REPOSITORY/\\.github/workflows/image\\.yml@refs/tags/[vV]$v_re\$" \
      --certificate-oidc-issuer "$ISSUER"
    mount_key=""
  fi
  ca=""
  if [ -d "$HERE/certificates/ca" ]; then ca="-v $HERE/certificates/ca:/etc/probant/ca:ro"; fi
  # the folder of the list is readable by this user only: cosign runs as this user (its image runs as another one)
  # shellcheck disable=SC2086 # $mount_key and $ca: options without spaces (paths checked by install.sh)
  docker run --rm --network host --read-only --tmpfs /tmp --cap-drop ALL --security-opt no-new-privileges \
    --user "$(id -u):$(id -g)" -e HOME=/tmp -e SSL_CERT_DIR=/etc/probant/ca \
    -e HTTPS_PROXY -e HTTP_PROXY -e NO_PROXY -e https_proxy -e http_proxy -e no_proxy \
    -v "$HERE/$SUMS_DIR:/work:ro" $mount_key $ca "$COSIGN_IMAGE" "$@" \
    --bundle "/work/$list.sigstore.json" "/work/$list" >> "$LOG" 2>&1
}

# ---- Migrations of the shared registry of an image (accounts, spaces, sessions): the registry is restored by its
# content only, never by its structure, so a version that adds one cannot be undone automatically
registry_migrations() {
  docker run --rm --network none --entrypoint sh "$1" -c 'cd /app && find espaces/migrations connexion_entreprise/migrations -name "[0-9]*.py" 2>/dev/null; python -c "import os, django.contrib.sessions.migrations as m; print(chr(10).join(\"sessions/\" + f for f in os.listdir(os.path.dirname(m.__file__))))"' 2>/dev/null \
    | grep -E '^[a-z_/]+/[0-9]{4}_[A-Za-z0-9_]+\.py$' | sort
}

# ---- Files of before the update: kept in .auto-update/previous, put back by a rename (a running script keeps its copy)
save_files() {
  rm -rf "$STATE/previous" && mkdir -p "$STATE/previous/docker" || return 1
  cp -p .env "$STATE/previous/.env" || return 1
  for f in $FILES; do
    if [ -f "$f" ]; then cp -p "$f" "$STATE/previous/$f" || return 1; fi
  done
}
restore_files() {
  for f in .env $FILES; do
    if [ -f "$STATE/previous/$f" ]; then
      mkdir -p "$(dirname "$f")"
      cp -p "$STATE/previous/$f" "$f.restore" && mv -f "$f.restore" "$f"
    fi
  done
}

# before-update archives of a space, oldest first (names checked)
archives_of() { manage_space "$1" backup --list 2>/dev/null | awk '{ print $1 }' | grep -E '^backup-[0-9]{8}-[0-9]{6}-before-update\.zip$' | sort; }

# ---- Going back did not work completely: nothing more is done automatically (not even the next nights) until IT has
# looked (./auto-update.sh --retry); the result stays "failed"
stop_failed() {  # stop_failed REASON
  echo "$AVAILABLE_DIGEST" > "$STATE/failed"
  echo "$AVAILABLE_DIGEST" > "$STATE/blocked"
  finish failed "$1"
}

# ---- Back to the version of before (files, image, and the data if the new version changed a database)
roll_back() {  # roll_back REASON
  why="$1"
  log "Going back to version $INSTALLED (reason: $why)."
  docker compose stop web >> "$LOG" 2>&1
  restore_files
  after=$(manage auto_update --fingerprint 2>>"$LOG" | grep -E '^(registry|space [a-z][a-z0-9]{1,19}) ([0-9a-f]{64}|empty)$') || after=""
  RESTORED=no
  if [ "$after" != "$FINGERPRINT" ]; then
    if [ -z "$after" ] || [ "$(echo "$after" | grep '^registry ')" != "$(echo "$FINGERPRINT" | grep '^registry ')" ]; then
      log "The new version changed the shared registry, or its state cannot be read: going back stops here."
      docker compose up -d >> "$LOG" 2>&1
      stop_failed restore_failed
    fi
    for code in $(echo "$FINGERPRINT" | sed -n 's/^space \([a-z0-9]*\) .*/\1/p'); do
      if [ "$(echo "$after" | grep "^space $code ")" = "$(echo "$FINGERPRINT" | grep "^space $code ")" ]; then continue; fi
      archive=$(archives_of "$code" | grep -vxF -f "$STATE/archives-$code" | head -1)
      if [ -z "$archive" ]; then
        log "Space \"$code\": changed by the new version, and no before-update backup of this update: going back stops here."
        docker compose up -d >> "$LOG" 2>&1
        stop_failed restore_failed
      fi
      log "Space \"$code\": restore of $archive (made just before the update)."
      if ! manage_space "$code" restore "$archive" --yes --rebuild --no-backup-before >> "$LOG" 2>&1; then
        log "Space \"$code\": the restore failed."
        docker compose up -d >> "$LOG" 2>&1
        stop_failed restore_failed
      fi
    done
    after=$(manage auto_update --fingerprint 2>>"$LOG" | grep -E '^(registry|space [a-z][a-z0-9]{1,19}) ([0-9a-f]{64}|empty)$') || after=""
    if [ "$after" != "$FINGERPRINT" ]; then
      log "After the restore, the databases still differ from before the update."
      docker compose up -d >> "$LOG" 2>&1
      stop_failed restore_failed
    fi
    RESTORED=yes
  fi
  docker compose up -d >> "$LOG" 2>&1
  if ! healthy "$HEALTH_TRIES"; then
    log "Version $INSTALLED does not respond after going back. Log: docker compose logs web"
    stop_failed rollback_health
  fi
  echo "$AVAILABLE_DIGEST" > "$STATE/failed"
  log "Back to version $INSTALLED: the tool responds (data restored: $RESTORED)."
  finish rolled_back "$why"
}

# ---- Main
[ -f .env ] || { log "No .env file in $HERE: nothing to do."; exit 1; }
if ! take_lock; then
  log "Another update is running (lock $LOCK): nothing was done."
  exit 0
fi
trap 'release_lock' EXIT
trap 'release_lock; exit 1' HUP INT TERM

IMAGE_NOW=$(grep "^IMAGE=" .env | tail -1 | cut -d= -f2- || true)
case "$IMAGE_NOW" in
  "$IMAGE_NAME":*) rest="${IMAGE_NOW#"$IMAGE_NAME":}"; INSTALLED="${rest%%@*}" ;;
esac
if [ -n "$RECORD" ]; then  # install.sh: the timer was set up or removed
  case "$RECORD" in installed|task_removed) finish "$RECORD" ;; *) exit 2 ;; esac
fi
if [ -d .git ]; then finish not_available git; fi
is_version "$INSTALLED" || finish not_available image
web_running || finish check_failed tool_stopped
read_choice
log "Choice of the administrator: $MODE (wait $DELAY day(s) after a publication)."
if [ "$RETRY" = 1 ]; then rm -f "$STATE/blocked"; fi
if [ -f "$STATE/blocked" ]; then
  log "An automatic update failed and going back was not complete: nothing is done until IT has checked the tool and"
  log "runs ./auto-update.sh --retry (docs/installation.md, \"Automatic updates\")."
  if [ -f "$STATE/last" ]; then
    grep -E '^(installed|previous|available)=[0-9]+\.[0-9]+\.[0-9]+$' "$STATE/last" | tr '=' ' ' > "$STATE/blocked.values"
    while read -r k v; do
      case "$k" in installed) INSTALLED="$v" ;; previous) PREVIOUS="$v" ;; available) AVAILABLE="$v" ;; esac
    done < "$STATE/blocked.values"
    rm -f "$STATE/blocked.values"
  fi
  finish failed "$(sed -n 's/^reason=\([a-z_]*\)$/\1/p' "$STATE/last" 2>/dev/null | head -1)"
fi
if [ "$MODE" = off ]; then finish off; fi

command -v curl >/dev/null 2>&1 || finish check_failed network
VERSION=$(latest_version) || { log "The latest version could not be found ($SOURCE/releases)."; finish check_failed network; }
pulled=$(docker pull "$IMAGE_NAME:$VERSION" 2>>"$LOG") || { log "The image $IMAGE_NAME:$VERSION could not be downloaded."; finish check_failed registry; }
DIGEST=$(printf '%s\n' "$pulled" | sed -n 's/^Digest: //p' | tail -1)
is_digest "$DIGEST" || { log "No digest for $IMAGE_NAME:$VERSION."; finish check_failed registry; }
NEW_ID=$(docker image inspect -f '{{.Id}}' "$IMAGE_NAME@$DIGEST" 2>/dev/null) || finish check_failed registry
RUN_ID=$(running_image) || RUN_ID=""
INSTALLED_DIGEST=$(printf '%s\n' "$IMAGE_NOW" | sed -n 's/.*@\(sha256:[0-9a-f]*\)$/\1/p')
if [ "$NEW_ID" = "$RUN_ID" ]; then
  INSTALLED_DIGEST="$DIGEST"
  log "The image that runs is the latest one ($IMAGE_NAME@$DIGEST): nothing to do."
  finish up_to_date
fi
AVAILABLE="$VERSION" ; AVAILABLE_DIGEST="$DIGEST"
log "New image: $IMAGE_NAME:$VERSION ($DIGEST); installed: $IMAGE_NOW."

status=0
verify_signature "$IMAGE_NAME@$DIGEST" "$VERSION" || status=$?
if [ "$status" != 0 ]; then
  docker image rm "$IMAGE_NAME:$VERSION" >/dev/null 2>&1 || true
  if [ "$status" = 2 ]; then log "Nothing was installed: the signature could not be verified."; finish refused verifier; fi
  log "Nothing was installed: no valid signature of $REPOSITORY (workflow image.yml, tag v$VERSION) for this image."
  finish refused signature
fi
log "Signature verified: $IMAGE_NAME@$DIGEST comes from $REPOSITORY (image.yml, tag v$VERSION)."

if [ "$RETRY" = 1 ]; then rm -f "$STATE/failed"; fi
if [ "$(cat "$STATE/failed" 2>/dev/null || true)" = "$DIGEST" ]; then
  log "The automatic update to this image failed before: not tried again (./auto-update.sh --retry to try again)."
  finish available already_failed
fi
if [ "$MODE" = notify ]; then finish available; fi

old_list=$(mktemp) ; new_list=$(mktemp)
registry_migrations "$RUN_ID" > "$old_list"
registry_migrations "$IMAGE_NAME@$DIGEST" > "$new_list"
if [ ! -s "$old_list" ] || [ ! -s "$new_list" ] || [ -n "$(comm -13 "$old_list" "$new_list")" ]; then
  log "This version changes the shared registry (accounts, spaces) or its migrations cannot be read: install it by hand with ./update.sh."
  rm -f "$old_list" "$new_list"
  finish available registry_migrations
fi
rm -f "$old_list" "$new_list"

if [ "$DELAY" != 0 ]; then
  created=$(docker image inspect -f '{{.Created}}' "$IMAGE_NAME@$DIGEST" 2>/dev/null | cut -c1-10)
  printf '%s\n' "$created" | grep -Eqx '[0-9]{4}-[0-9]{2}-[0-9]{2}' || finish check_failed registry
  first=$(( $(days_of "$created") + DELAY ))
  if [ "$(days_of "$(date -u +%Y-%m-%d)")" -lt "$first" ]; then
    AFTER=$(date_of "$first")
    log "Published on $created: installed from $AFTER (wait of $DELAY day(s))."
    finish waiting
  fi
fi

busy=$(manage auto_update --busy 2>>"$LOG" | tail -1) || true
case "$busy" in
  idle) ;;
  busy_restore|busy_backup|busy_import|busy_export) log "The tool is busy ($busy): next try the next night."; finish postponed "$busy" ;;
  *) log "The tool could not say whether it is busy."; finish postponed busy_unknown ;;
esac
if ! download_sums "$VERSION"; then
  log "Nothing was installed: the release of version $VERSION has no list of the SHA-256 sums of its files, or no signature"
  log "of this list (a version published in the last hour may not have them yet: next try the next night)."
  finish refused signature
fi
status=0
verify_sums "$VERSION" || status=$?
if [ "$status" != 0 ]; then
  if [ "$status" = 2 ]; then log "Nothing was installed: the signature of the list of sums could not be verified."; finish refused verifier; fi
  log "Nothing was installed: no valid signature of $REPOSITORY (workflow image.yml, tag v$VERSION) for the list of sums."
  finish refused signature
fi
log "Signature verified: the list of the SHA-256 sums of the files of version $VERSION comes from $REPOSITORY (image.yml)."

FINGERPRINT=$(manage auto_update --fingerprint 2>>"$LOG" | grep -E '^(registry|space [a-z][a-z0-9]{1,19}) ([0-9a-f]{64}|empty)$') || FINGERPRINT=""
[ -n "$FINGERPRINT" ] || finish check_failed tool_check
for code in $(echo "$FINGERPRINT" | sed -n 's/^space \([a-z0-9]*\) .*/\1/p'); do
  archives_of "$code" > "$STATE/archives-$code"
done
save_files || { log "The files of before could not be kept in $STATE/previous: nothing was changed."; finish check_failed tool_check; }

log "Update to $VERSION ($DIGEST)…"
PREVIOUS="$INSTALLED"
status=0
PROBANT_UPDATE_LOCK_OWNER=$$ sh ./update.sh --version "$VERSION" --digest "$DIGEST" --sums "$HERE/$SUMS_DIR/probant-$VERSION-files.sha256" \
  >> "$LOG" 2>&1 || status=$?
if [ "$status" != 0 ]; then
  # stopped before the new image (failed backup, failed download…): nothing changed, tried again the next night
  if [ "$(grep "^IMAGE=" .env | tail -1 | cut -d= -f2- || true)" = "$IMAGE_NOW" ] && [ "$(running_image)" = "$RUN_ID" ]; then
    restore_files
    if [ "$status" = 3 ]; then
      # a downloaded file does not match the verified list (update.sh: exit code 3)
      log "Nothing was installed: a file of version $VERSION does not match the verified list of sums (see the lines above)."
      finish refused signature
    fi
    log "The update stopped before the new version: nothing was changed (see the lines above)."
    finish check_failed update_script
  fi
  # the new image runs but does not respond (update.sh waited for it): the version itself is the cause
  if [ "$(running_image)" = "$NEW_ID" ] && ! healthy 3; then roll_back health; fi
  roll_back update_script
fi
if [ "$(running_image)" != "$NEW_ID" ] || ! healthy "$HEALTH_TRIES"; then roll_back health; fi
sleep "$STABLE_WAIT"
if [ "$(running_image)" != "$NEW_ID" ] || ! healthy 3; then roll_back health; fi
rm -f "$STATE/failed"
INSTALLED="$VERSION" ; INSTALLED_DIGEST="$DIGEST"
log "Update complete: version $VERSION responds."
finish updated
