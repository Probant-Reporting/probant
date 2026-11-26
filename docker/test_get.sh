#!/usr/bin/env bash
# "One command" test: get.sh on a blank folder, as an IT team would run it ("curl … | sh"), but from a local copy of
# the public repository (HTTP server, with the release of each version: its list of SHA-256 sums, signed with a test
# key of cosign instead of the identity of the workflow) and a local image registry instead of github.com and ghcr.io.
# First the refusals, where nothing may be installed: a file of the tag changed, the list changed after its signature,
# no list. Then checks: only the files that run the tool are downloaded, each one checked against the list, the image
# is downloaded (never built), health page, wizard, commit of the image shown; update to a newer version
# (./update.sh --version), with the files checked, the backup before and the data kept; then going back to the previous
# version as docs/installation.md describes it (SQLite). Everything is removed at the end (containers, volumes,
# registry, images, folder).
#
#   COSIGN_BINARY=/path/to/cosign bash docker/test_get.sh    (Docker and cosign 3 required; builds the image of this folder)
#   IMAGE_UNDER_TEST=probant:local bash docker/test_get.sh   (an image already built from this folder)
#   REGISTRY_IMAGE=registry:2 (default): image of the local registry
#   TEST_PREFIX (default probant-get): prefix of the containers, Compose project and images of this test
# cosign: the one of the machine if it is on the PATH (the scripts use it), otherwise the test image of COSIGN_BINARY
# (FROM scratch, user 65532 as the official image), which the scripts run in a container.
set -euo pipefail
SOURCE="$(cd "$(dirname "$0")/.." && pwd)"
WORKDIR="$(mktemp -d)"
PREFIX="${TEST_PREFIX:-probant-get}"
PROJECT="$PREFIX-$$"
PORT="${TEST_PORT:-17$(( $$ % 900 + 100 ))}"
REGISTRY_PORT="${REGISTRY_PORT:-15$(( $$ % 900 + 100 ))}"
SERVER_PORT="${SERVER_PORT:-16$(( $$ % 900 + 100 ))}"
VERSION="$(cat "$SOURCE/VERSION")"
NEXT="${VERSION%.*}.$(( ${VERSION##*.} + 1 ))"
REGISTRY="127.0.0.1:$REGISTRY_PORT"
export COMPOSE_PROJECT_NAME="$PROJECT"
export PROBANT_TEST_SOURCE="http://127.0.0.1:$SERVER_PORT"
export PROBANT_TEST_IMAGE="$REGISTRY/probant"
export PROBANT_TEST_COSIGN_IMAGE="$PREFIX-cosign:$$"
export PROBANT_TEST_COSIGN_KEY="$WORKDIR/keys/good.pub"
export COSIGN_PASSWORD=""
BAD="${VERSION%.*}.$(( ${VERSION##*.} + 7 ))"
BUILT=""
SERVER_PID=""

cleanup() {
  (cd "$WORKDIR/server/probant" 2>/dev/null && docker compose down -v --remove-orphans >/dev/null 2>&1) || true
  docker rm -f -v "$PREFIX-registry-$$" >/dev/null 2>&1 || true
  docker image rm "$PROBANT_TEST_IMAGE:$VERSION" "$PROBANT_TEST_IMAGE:$NEXT" "$PROBANT_TEST_COSIGN_IMAGE" ${BUILT:+"$BUILT"} \
    >/dev/null 2>&1 || true
  [ -n "$SERVER_PID" ] && kill "$SERVER_PID" 2>/dev/null || true
  rm -rf "$WORKDIR"
}
trap cleanup EXIT
fail() { echo "FAILED: $*"; (cd "$WORKDIR/server/probant" 2>/dev/null && docker compose logs --tail 60 web) || true; exit 1; }
ok() { echo "  ok  $*"; }

COSIGN="${COSIGN_BINARY:-$(command -v cosign || true)}"
[ -x "$COSIGN" ] || { echo "cosign is needed (COSIGN_BINARY=/path/to/cosign)"; exit 1; }
mkdir -p "$WORKDIR/keys" "$WORKDIR/cosign"
cp "$COSIGN" "$WORKDIR/cosign/cosign"
printf 'FROM scratch\nCOPY cosign /cosign\nUSER 65532:65532\nENTRYPOINT ["/cosign"]\n' > "$WORKDIR/cosign/Dockerfile"
docker build -q -t "$PROBANT_TEST_COSIGN_IMAGE" "$WORKDIR/cosign" >/dev/null
(cd "$WORKDIR/keys" && "$COSIGN" generate-key-pair --output-key-prefix good >/dev/null 2>&1)
if command -v cosign >/dev/null 2>&1; then echo "cosign of the machine: $(command -v cosign)"; else echo "cosign in its test container ($PROBANT_TEST_COSIGN_IMAGE)"; fi

IMAGE="${IMAGE_UNDER_TEST:-}"
if [ -z "$IMAGE" ]; then
  IMAGE="$PREFIX:built-$$"; BUILT="$IMAGE"
  echo "Building the image of this folder ($IMAGE)"
  docker build -q --build-arg VERSION_COMMIT="$(git -C "$SOURCE" rev-parse HEAD 2>/dev/null || echo 0123456789abcdef)" -t "$IMAGE" "$SOURCE" >/dev/null
fi
COMMIT="$(docker image inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$IMAGE" | sed -n 's/^VERSION_COMMIT=//p')"

echo "Local registry ($REGISTRY) with the image as versions $VERSION and $NEXT"
docker run -d --name "$PREFIX-registry-$$" -p "$REGISTRY:5000" "${REGISTRY_IMAGE:-registry:2}" >/dev/null
for _ in $(seq 30); do curl -fs "http://$REGISTRY/v2/" >/dev/null && break; sleep 1; done
for v in "$VERSION" "$NEXT"; do
  docker tag "$IMAGE" "$PROBANT_TEST_IMAGE:$v"
  docker push -q "$PROBANT_TEST_IMAGE:$v" >/dev/null
  docker image rm "$PROBANT_TEST_IMAGE:$v" >/dev/null  # get.sh and update.sh must download it
done

echo "Local copy of the public repository (tags v$VERSION, v$NEXT and v$BAD, their releases with the lists of sums)"
for v in "$VERSION" "$NEXT" "$BAD"; do
  TAG="$WORKDIR/repository/raw/refs/tags/v$v"
  mkdir -p "$TAG/docker"
  (cd "$SOURCE" && cp get.sh docker-compose.yml .env.example install.sh update.sh check.sh "$TAG/" && cp docker/Caddyfile "$TAG/docker/")
  echo "$v" > "$TAG/VERSION"
done
echo "# files of version $NEXT" >> "$WORKDIR/repository/raw/refs/tags/v$NEXT/docker-compose.yml"
# release_of VERSION: the list of sums of the files of its tag (these tags have no auto-update.sh: the list of
# docker/make_file_sums.sh without it), signed with the test key
release_of() {
  out="$WORKDIR/repository/releases/download/v$1"
  mkdir -p "$out"
  (cd "$WORKDIR/repository/raw/refs/tags/v$1" && sha256sum VERSION get.sh docker-compose.yml .env.example install.sh update.sh \
    check.sh docker/Caddyfile) > "$out/probant-$1-files.sha256"
  "$COSIGN" sign-blob --yes --key "$WORKDIR/keys/good.key" --use-signing-config=false --tlog-upload=false \
    --bundle "$out/probant-$1-files.sha256.sigstore.json" "$out/probant-$1-files.sha256" >/dev/null 2>&1 || fail "signature of the list $1"
}
for v in "$VERSION" "$NEXT" "$BAD"; do release_of "$v"; done
python3 -m http.server "$SERVER_PORT" --bind 127.0.0.1 --directory "$WORKDIR/repository" >/dev/null 2>&1 &
SERVER_PID=$!
for _ in $(seq 30); do curl -fs "$PROBANT_TEST_SOURCE/raw/refs/tags/v$VERSION/VERSION" >/dev/null && break; sleep 1; done

# refused: get_refused CASE: get.sh of version BAD stops, with a message that names the cause, and installs nothing
get_refused() {
  mkdir -p "$WORKDIR/refused-$1"
  if (cd "$WORKDIR/refused-$1" && sh "$SOURCE/get.sh" --version "$BAD" --port "$PORT" > "$WORKDIR/refused-$1.log" 2>&1); then
    fail "get.sh installed version $BAD ($1)"
  fi
  [ -z "$(ls -A "$WORKDIR/refused-$1/probant" 2>/dev/null)" ] || fail "files left by a refused installation ($1)"
  grep -q "Nothing was installed." "$WORKDIR/refused-$1.log" || fail "message of the refusal ($1): $(cat "$WORKDIR/refused-$1.log")"
}
BAD_TAG="$WORKDIR/repository/raw/refs/tags/v$BAD"
BAD_RELEASE="$WORKDIR/repository/releases/download/v$BAD"
echo "Refused: a file of the tag changed after the release (version $BAD)"
cp "$BAD_TAG/install.sh" "$WORKDIR/install.sh.good"
echo "echo changed" >> "$BAD_TAG/install.sh"
get_refused file
grep -q "install.sh does not match its SHA-256 sum" "$WORKDIR/refused-file.log" || fail "file not named: $(cat "$WORKDIR/refused-file.log")"
ok "a changed file is refused, nothing is installed"
echo "Refused: the list changed after its signature, to match the changed file"
cp "$BAD_RELEASE/probant-$BAD-files.sha256" "$WORKDIR/list.good"
(cd "$BAD_TAG" && sha256sum VERSION get.sh docker-compose.yml .env.example install.sh update.sh check.sh docker/Caddyfile) \
  > "$BAD_RELEASE/probant-$BAD-files.sha256"
get_refused list
grep -q "was refused by cosign" "$WORKDIR/refused-list.log" || fail "signature not refused: $(cat "$WORKDIR/refused-list.log")"
ok "a list changed after its signature is refused by cosign"
echo "Refused: no list in the release"
rm -f "$BAD_RELEASE/probant-$BAD-files.sha256"
get_refused none
grep -q "has no list of the SHA-256 sums" "$WORKDIR/refused-none.log" || fail "no list: $(cat "$WORKDIR/refused-none.log")"
ok "a version without a list is refused"
[ -z "$(docker ps -q --filter "label=com.docker.compose.project=$PROJECT")" ] || fail "a container started"

echo "Installation: curl … get.sh | sh -s -- --version $VERSION --port $PORT"
mkdir -p "$WORKDIR/server"
cd "$WORKDIR/server"
curl -fsSL "$PROBANT_TEST_SOURCE/raw/refs/tags/v$VERSION/get.sh" | sh -s -- --version "$VERSION" --port "$PORT" > "$WORKDIR/get.log" 2>&1 \
  || fail "get.sh: $(tail -20 "$WORKDIR/get.log")"
grep -q "Files checked: each one matches its SHA-256 sum in the list of the release; signature of the list verified" "$WORKDIR/get.log" \
  || fail "files not checked: $(cat "$WORKDIR/get.log")"
ok "files checked against the list of the release, signature of the list verified"
cd probant
FILES="$(find . -type f | sort | tr '\n' ' ')"
[ "$FILES" = "./.env ./.env.example ./check.sh ./docker-compose.yml ./docker/Caddyfile ./install.sh ./update.sh " ] || fail "files: $FILES"
ok "only the files that run the tool: $FILES"
grep -qx "IMAGE=$PROBANT_TEST_IMAGE:$VERSION" .env || fail "IMAGE in .env"
grep -q '^VERSION_COMMIT=' .env && fail "VERSION_COMMIT written in .env"
[ "$(docker inspect -f '{{.Config.Image}}' "$(docker compose ps -q web)")" = "$PROBANT_TEST_IMAGE:$VERSION" ] || fail "image of the service"
ok "image of version $VERSION downloaded, not built"

URL="http://127.0.0.1:$PORT"
curl -fsS "$URL/sante/" | grep -q '"etat": "ok"' || fail "health"; ok "health page"
[[ "$(curl -s -o /dev/null -w '%{redirect_url}' "$URL/")" == */mise-en-place/ ]] || fail "wizard"; ok "empty database: the wizard opens"
[ "$(docker compose exec -T web printenv VERSION_COMMIT || true)" = "$COMMIT" ] || fail "commit of the image hidden"
ok "commit of the image kept (${COMMIT:-none})"

docker compose exec -T web python manage.py shell -c "
from referentiel.models import Utilisateur
u = Utilisateur(username='admin@example.test', email='admin@example.test', first_name='Test', role='admin', is_staff=True, is_superuser=True)
u.set_password('Essai-installation-2026'); u.save()" >/dev/null || fail "account creation"
cp .env "$WORKDIR/env-before"

echo "Update: ./update.sh --version $NEXT"
./update.sh --version "$NEXT" > "$WORKDIR/update.log" 2>&1 || fail "update.sh: $(tail -20 "$WORKDIR/update.log")"
grep -q "Files checked: each one matches its SHA-256 sum in the list of the release; signature of the list verified" "$WORKDIR/update.log" \
  || fail "files of the update not checked: $(cat "$WORKDIR/update.log")"
grep -qx "IMAGE=$PROBANT_TEST_IMAGE:$NEXT" .env || fail "IMAGE after the update"
diff <(grep -v '^IMAGE=' "$WORKDIR/env-before") <(grep -v '^IMAGE=' .env) >/dev/null || fail ".env changed"
tail -1 docker-compose.yml | grep -q "files of version $NEXT" || fail "files of the new version"
ok "files and image of version $NEXT; .env kept"
docker compose exec -T web sh -c 'ls /data/backups/*before-update.zip' >/dev/null || fail "no backup before the update"
ok "backup before the update"
curl -fsS "$URL/sante/" | grep -q '"etat": "ok"' || fail "health after the update"
docker compose exec -T web python manage.py shell -c "
from referentiel.models import Utilisateur; assert Utilisateur.objects.filter(email='admin@example.test').exists()" || fail "data lost"
ok "data kept, the tool responds"

echo "Going back to version $VERSION (docs/installation.md, \"Going back to the previous version\", SQLite)"
ARCHIVE="$(docker compose exec -T web sh -c 'cd /data/backups && ls -t *before-update.zip | tail -1')"
docker compose exec -T web python manage.py shell -c "
from referentiel.models import Utilisateur
Utilisateur.objects.create(username='after-update@example.test', email='after-update@example.test', role='lecteur')" >/dev/null
docker compose stop web
sed -i "s|^IMAGE=.*|IMAGE=$PROBANT_TEST_IMAGE:$VERSION|" .env
docker compose pull web
docker compose run --rm web python manage.py restore "$ARCHIVE" --yes >/dev/null || fail "restore"
docker compose up -d
for _ in $(seq 90); do curl -fs "$URL/sante/" >/dev/null && break; sleep 2; done
curl -fsS "$URL/sante/" | grep -q '"etat": "ok"' || fail "health after going back"
docker compose exec -T web python manage.py shell -c "
from referentiel.models import Utilisateur
assert Utilisateur.objects.filter(email='admin@example.test').exists()
assert not Utilisateur.objects.filter(email='after-update@example.test').exists()" || fail "state after going back"
ok "previous image and before-update archive: the tool responds with the data of before the update"
echo "PASSED: installation in one command (files checked, refusals), update and going back, with the published image."
