#!/usr/bin/env bash
# "Without Internet access" test: makes the offline packages of two versions from the image of this folder
# (docker/make_offline_package.sh), then plays a server without Internet access: the name of the image points to a
# registry address where nothing answers, curl and wget fail and write down any call, the Docker events must show
# no download, and, where the system allows it, the scripts run in a network namespace without any network. Checks: installation (./install.sh --offline), health page, wizard; update to the second version
# (./update.sh --offline), with the backup before and the data kept; an older package refused; then going back to the
# first version as docs/installation.md describes it (SQLite). Everything is removed at the end (containers, volumes,
# images of this test, folder).
#
#   bash docker/test_offline.sh                                  (Docker required; builds the image of this folder)
#   IMAGE_UNDER_TEST=probant:local bash docker/test_offline.sh   (an image already built from this folder)
set -euo pipefail
SOURCE="$(cd "$(dirname "$0")/.." && pwd)"
WORKDIR="$(mktemp -d)"
PROJECT="probant-offline-$$"
PORT="${TEST_PORT:-19$(( $$ % 900 + 100 ))}"
VERSION="$(cat "$SOURCE/VERSION")"
NEXT="${VERSION%.*}.$(( ${VERSION##*.} + 1 ))"
# name of the image on the server: a registry address where nothing answers (port 9, "discard"), so that any download fails
NAME="127.0.0.1:9/probant-offline-$$"
export COMPOSE_PROJECT_NAME="$PROJECT"
BUILT=""
EVENTS_PID=""

cleanup() {
  (cd "$WORKDIR/server/probant" 2>/dev/null && docker compose down -v --remove-orphans >/dev/null 2>&1) || true
  docker image rm "$NAME:$VERSION" "$NAME:$NEXT" ${BUILT:+"$BUILT"} >/dev/null 2>&1 || true
  [ -n "$EVENTS_PID" ] && kill "$EVENTS_PID" 2>/dev/null || true
  rm -rf "$WORKDIR"
}
trap cleanup EXIT
fail() { echo "FAILED: $*"; (cd "$WORKDIR/server/probant" 2>/dev/null && docker compose logs --tail 60 web) || true; exit 1; }
ok() { echo "  ok  $*"; }

IMAGE="${IMAGE_UNDER_TEST:-}"
if [ -z "$IMAGE" ]; then
  IMAGE="probant:offline-test-$$"; BUILT="$IMAGE"
  echo "Building the image of this folder ($IMAGE)"
  docker build -q -t "$IMAGE" "$SOURCE" >/dev/null
fi

echo "Images of versions $VERSION and $NEXT ($NAME), built without network"
docker tag "$IMAGE" "$NAME:$VERSION"
printf 'FROM %s\nUSER root\nRUN echo %s > /app/VERSION\nUSER probant\n' "$NAME:$VERSION" "$NEXT" \
  | docker build -q --network none -t "$NAME:$NEXT" - >/dev/null

echo "Offline packages of the two versions"
for v in "$VERSION" "$NEXT"; do
  mkdir -p "$WORKDIR/code-$v/docker"
  (cd "$SOURCE" && cp -p docker-compose.yml .env.example install.sh update.sh check.sh "$WORKDIR/code-$v/" \
    && cp -p docker/Caddyfile docker/make_offline_package.sh "$WORKDIR/code-$v/docker/")
done
echo "# files of version $NEXT" >> "$WORKDIR/code-$NEXT/docker-compose.yml"
for v in "$VERSION" "$NEXT"; do
  bash "$WORKDIR/code-$v/docker/make_offline_package.sh" "$NAME:$v" "$WORKDIR/dist" || fail "package $v"
done
(cd "$WORKDIR/dist" && sha256sum -c --quiet "probant-$VERSION-offline.tar.sha256" "probant-$NEXT-offline.tar.sha256") || fail "sums"
ok "packages: $(cd "$WORKDIR/dist" && du -m ./*.tar | tr '\n\t' '  ')(MB)"
# the server has none of these images: only the packages bring them
docker image rm "$NAME:$VERSION" "$NAME:$NEXT" >/dev/null

# "server without Internet access": curl and wget write down the call and fail; Docker downloads are written down too
mkdir -p "$WORKDIR/no-network" "$WORKDIR/server" "$WORKDIR/new"
for c in curl wget; do
  printf '#!/bin/sh\necho "%s $*" >> "%s/network.log"\nexit 7\n' "$c" "$WORKDIR" > "$WORKDIR/no-network/$c"
  chmod 755 "$WORKDIR/no-network/$c"
done
: > "$WORKDIR/network.log"
docker events --filter type=image --filter event=pull --format '{{.Actor.Attributes.name}}' > "$WORKDIR/pulls.log" 2>&1 &
EVENTS_PID=$!
# and, where the system allows it, the scripts run in a network namespace without any network (only the socket of
# Docker, a file, still answers): as root, or in a user namespace
NO_NET=()
for candidate in "unshare --net --" "unshare --net --map-root-user --"; do
  read -r -a try <<<"$candidate"
  if "${try[@]}" docker info >/dev/null 2>&1; then
    NO_NET=("${try[@]}"); break
  fi
done
if [ ${#NO_NET[@]} -gt 0 ]; then echo "  (scripts run without any network: ${NO_NET[*]})"; else echo "  (no network namespace here: curl and wget only)"; fi
offline() { PATH="$WORKDIR/no-network:$PATH" "${NO_NET[@]}" "$@"; }
no_network_used() {
  [ ! -s "$WORKDIR/network.log" ] || fail "network call: $(cat "$WORKDIR/network.log")"
  [ ! -s "$WORKDIR/pulls.log" ] || fail "image download: $(cat "$WORKDIR/pulls.log")"
}

echo "Installation: tar -xf probant-$VERSION-offline.tar; ./install.sh --offline probant-image-$VERSION.tar.gz --port $PORT"
tar -xf "$WORKDIR/dist/probant-$VERSION-offline.tar" -C "$WORKDIR/server"
cd "$WORKDIR/server/probant"
offline ./install.sh --offline "probant-image-$VERSION.tar.gz" --port "$PORT" | tee "$WORKDIR/install.log" || fail "install.sh --offline"
grep -q "Network: installation without Internet access" "$WORKDIR/install.log" || fail "offline check"
grep -qx "IMAGE=$NAME:$VERSION" .env || fail "IMAGE in .env"
no_network_used
ok "installed from the package, no network call, no image download"

URL="http://127.0.0.1:$PORT"
curl -fsS "$URL/sante/" | grep -q '"etat": "ok"' || fail "health"; ok "health page"
[[ "$(curl -s -o /dev/null -w '%{redirect_url}' "$URL/")" == */mise-en-place/ ]] || fail "wizard"; ok "empty database: the wizard opens"
docker compose exec -T web python manage.py shell -c "
from referentiel.models import Utilisateur
u = Utilisateur(username='admin@example.test', email='admin@example.test', first_name='Test', role='admin', is_staff=True, is_superuser=True)
u.set_password('Essai-installation-2026'); u.save()" >/dev/null || fail "account creation"
cp .env "$WORKDIR/env-before"

echo "Update: ./update.sh --offline (package of version $NEXT, extracted in another folder)"
tar -xf "$WORKDIR/dist/probant-$NEXT-offline.tar" -C "$WORKDIR/new"
offline ./update.sh --offline "../../new/probant/probant-image-$NEXT.tar.gz" || fail "update.sh --offline"
grep -qx "IMAGE=$NAME:$NEXT" .env || fail "IMAGE after the update"
diff <(grep -v '^IMAGE=' "$WORKDIR/env-before") <(grep -v '^IMAGE=' .env) >/dev/null || fail ".env changed"
tail -1 docker-compose.yml | grep -q "files of version $NEXT" || fail "files of the new version"
[ "$(docker compose exec -T web cat /app/VERSION)" = "$NEXT" ] || fail "version after the update"
docker compose exec -T web sh -c 'ls /data/backups/*before-update.zip' >/dev/null || fail "no backup before the update"
curl -fsS "$URL/sante/" | grep -q '"etat": "ok"' || fail "health after the update"
docker compose exec -T web python manage.py shell -c "
from referentiel.models import Utilisateur; assert Utilisateur.objects.filter(email='admin@example.test').exists()" || fail "data lost"
no_network_used
ok "version $NEXT, files of the package, .env and data kept, backup before; no network"

mkdir -p "$WORKDIR/older"
tar -xf "$WORKDIR/dist/probant-$VERSION-offline.tar" -C "$WORKDIR/older"
if offline ./update.sh --offline "$WORKDIR/older/probant/probant-image-$VERSION.tar.gz" > "$WORKDIR/older.log" 2>&1; then
  fail "older package accepted"
fi
grep -q "older than the installed version" "$WORKDIR/older.log" || fail "older package: $(cat "$WORKDIR/older.log")"
grep -qx "IMAGE=$NAME:$NEXT" .env || fail "older package changed .env"
ok "older package refused, nothing changed"

echo "Going back to version $VERSION (docs/installation.md, \"Going back to the previous version\", SQLite)"
ARCHIVE="$(docker compose exec -T web sh -c 'cd /data/backups && ls -t *before-update.zip | tail -1')"
docker compose exec -T web python manage.py shell -c "
from referentiel.models import Utilisateur
Utilisateur.objects.create(username='after-update@example.test', email='after-update@example.test', role='lecteur')" >/dev/null
docker compose stop web
sed -i "s|^IMAGE=.*|IMAGE=$NAME:$VERSION|" .env  # the image of before is still on the server
offline docker compose run --rm web python manage.py restore "$ARCHIVE" --yes >/dev/null || fail "restore"
offline docker compose up -d
for _ in $(seq 90); do curl -fs "$URL/sante/" >/dev/null && break; sleep 2; done
curl -fsS "$URL/sante/" | grep -q '"etat": "ok"' || fail "health after going back"
[ "$(docker compose exec -T web cat /app/VERSION)" = "$VERSION" ] || fail "version after going back"
docker compose exec -T web python manage.py shell -c "
from referentiel.models import Utilisateur
assert Utilisateur.objects.filter(email='admin@example.test').exists()
assert not Utilisateur.objects.filter(email='after-update@example.test').exists()" || fail "state after going back"
no_network_used
ok "image of before and before-update archive: version $VERSION with the data of before the update"
echo "PASSED: installation, update and going back without Internet access."
