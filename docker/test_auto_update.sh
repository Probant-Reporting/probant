#!/usr/bin/env bash
# Real test of the automatic updates (auto-update.sh, docs/installation.md "Automatic updates"), with Docker, a local
# image registry, a local copy of the public repository (HTTP server with /releases/latest, and the release of each
# version with its list of SHA-256 sums) and a test key of cosign instead of the identity of the workflow
# (PROBANT_TEST_COSIGN_KEY, read only with a test image name). Played in this order on one installation made by get.sh
# (timer set up in a test folder, choice "automatic" by default):
#   off · nothing to do · signature absent · signature of another key · notify only · window of 3 days ·
#   no list of sums · a file of the tag changed · the list changed after its signature ·
#   new image that does not start (going back, data kept, nothing restored) · the same image the next night (not tried
#   again) · migration applied then failure (going back with the restore of the before-update backup of each space) ·
#   two runs at the same time and a manual ./update.sh during a run (lock) · successful update · nothing to do after.
# After each run: the result written into the data volume is read by the parser of the tool, the image and .env are
# checked, /sante/ is green, and the accounts made before are still there. Everything is removed at the end.
#
#   COSIGN_BINARY=/path/to/cosign bash docker/test_auto_update.sh          (Docker and cosign 3 required)
#   IMAGE_UNDER_TEST=probant:local TEST_DATABASE=postgresql bash docker/test_auto_update.sh
#   TEST_PREFIX (default probant-auto): prefix of the containers, volumes, network and images of this test
#   REGISTRY_IMAGE=registry:2, POSTGRES_IMAGE=postgres:16: images of the local registry and of PostgreSQL
# What only GitHub can check (keyless signature of the workflow, pinned image of cosign, Sigstore network): the step
# "Verify the signature as auto-update.sh does" of .github/workflows/image.yml, at each published version.
set -euo pipefail
SOURCE="$(cd "$(dirname "$0")/.." && pwd)"
WORKDIR="$(mktemp -d)"
PREFIX="${TEST_PREFIX:-probant-auto}"
PROJECT="$PREFIX-$$"
PORT="${TEST_PORT:-18$(( $$ % 900 + 100 ))}"
REGISTRY_PORT="${REGISTRY_PORT:-19$(( $$ % 900 + 100 ))}"
SERVER_PORT="${SERVER_PORT:-20$(( $$ % 900 + 100 ))}"
DATABASE="${TEST_DATABASE:-sqlite}"
VERSION="$(cat "$SOURCE/VERSION")"
NEXT="${VERSION%.*}.$(( ${VERSION##*.} + 1 ))"
REGISTRY="127.0.0.1:$REGISTRY_PORT"
export COMPOSE_PROJECT_NAME="$PROJECT"
export PROBANT_TEST_SOURCE="http://127.0.0.1:$SERVER_PORT"
export PROBANT_TEST_IMAGE="$REGISTRY/probant"
export PROBANT_TEST_COSIGN_IMAGE="$PREFIX-cosign:$$"
export PROBANT_TEST_COSIGN_KEY="$WORKDIR/keys/good.pub"
export PROBANT_TEST_STABLE_WAIT=5 PROBANT_TEST_HEALTH_TRIES=45
# timer of the installation: systemd units written into a test folder, systemctl replaced by a recorder
export PROBANT_TEST_UID=0 PROBANT_TEST_SYSTEMD_DIR="$WORKDIR/systemd" PROBANT_TEST_SYSTEMD_RUN="$WORKDIR/run-systemd"
export PATH="$WORKDIR/bin:$PATH"
export COSIGN_PASSWORD=""
BUILT="" ; SERVER_PID=""
VARIANTS=()

cleanup() {
  (cd "$WORKDIR/server/probant" 2>/dev/null && docker compose down -v --remove-orphans >/dev/null 2>&1) || true
  docker rm -f -v "$PREFIX-registry-$$" >/dev/null 2>&1 || true
  docker image rm "$PROBANT_TEST_IMAGE:$VERSION" "$PROBANT_TEST_IMAGE:$NEXT" "$PROBANT_TEST_COSIGN_IMAGE" ${BUILT:+"$BUILT"} \
    ${VARIANTS[@]+"${VARIANTS[@]}"} >/dev/null 2>&1 || true
  [ -n "$SERVER_PID" ] && kill "$SERVER_PID" 2>/dev/null || true
  rm -rf "$WORKDIR"
}
trap cleanup EXIT
fail() {
  echo "FAILED: $*"
  (cd "$WORKDIR/server/probant" 2>/dev/null && tail -40 auto-update.log && docker compose logs --tail 40 web) || true
  exit 1
}
ok() { echo "  ok  $*"; }

COSIGN="${COSIGN_BINARY:-$(command -v cosign || true)}"
[ -x "$COSIGN" ] || { echo "cosign is needed (COSIGN_BINARY=/path/to/cosign)"; exit 1; }
mkdir -p "$WORKDIR/bin" "$WORKDIR/systemd" "$WORKDIR/run-systemd" "$WORKDIR/keys" "$WORKDIR/cosign"
printf '#!/bin/sh\necho "$*" >> "%s/systemctl.log"\n' "$WORKDIR" > "$WORKDIR/bin/systemctl"
chmod 755 "$WORKDIR/bin/systemctl"

IMAGE="${IMAGE_UNDER_TEST:-}"
if [ -z "$IMAGE" ]; then
  IMAGE="$PREFIX:built-$$"; BUILT="$IMAGE"
  echo "Building the image of this folder ($IMAGE)"
  docker build -q -t "$IMAGE" "$SOURCE" >/dev/null
fi

echo "cosign in a container (test image of $COSIGN), two key pairs"
cp "$COSIGN" "$WORKDIR/cosign/cosign"
# user 65532, as the official image of cosign (distroless "nonroot")
printf 'FROM scratch\nCOPY cosign /cosign\nUSER 65532:65532\nENTRYPOINT ["/cosign"]\n' > "$WORKDIR/cosign/Dockerfile"
docker build -q -t "$PROBANT_TEST_COSIGN_IMAGE" "$WORKDIR/cosign" >/dev/null
(cd "$WORKDIR/keys" && "$COSIGN" generate-key-pair --output-key-prefix good >/dev/null 2>&1 \
  && "$COSIGN" generate-key-pair --output-key-prefix other >/dev/null 2>&1)
sign_tag() {  # sign_tag KEY TAG: signs what TAG names now
  digest=$(curl -fsSI -H 'Accept: application/vnd.oci.image.index.v1+json, application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.v2+json, application/vnd.docker.distribution.manifest.list.v2+json' \
    "http://$REGISTRY/v2/probant/manifests/$2" | tr -d '\r' | sed -n 's/^[Dd]ocker-[Cc]ontent-[Dd]igest: //p')
  [ -n "$digest" ] || fail "no digest for the tag $2"
  "$COSIGN" sign --yes --key "$WORKDIR/keys/$1.key" --use-signing-config=false --tlog-upload=false --allow-http-registry \
    "$PROBANT_TEST_IMAGE@$digest" >/dev/null 2>&1 || fail "signature of $2"
}

echo "Local registry ($REGISTRY) with the image as version $VERSION (signed)"
docker run -d --name "$PREFIX-registry-$$" -p "$REGISTRY:5000" "${REGISTRY_IMAGE:-registry:2}" >/dev/null
for _ in $(seq 30); do curl -fs "http://$REGISTRY/v2/" >/dev/null && break; sleep 1; done
docker tag "$IMAGE" "$PROBANT_TEST_IMAGE:$VERSION"
docker push -q "$PROBANT_TEST_IMAGE:$VERSION" >/dev/null
docker image rm "$PROBANT_TEST_IMAGE:$VERSION" >/dev/null
sign_tag good "$VERSION"

# images of version NEXT, made from the image under test: they differ by one layer (their own digest)
LAST_MIGRATION="$(find "$SOURCE/parametres/migrations" -name '[0-9]*.py' -exec basename {} .py \; | sort | tail -1)"
variant() {  # variant NAME DOCKERFILE-LINES: an image $PREFIX-variant:NAME
  mkdir -p "$WORKDIR/variant-$1"
  printf 'FROM %s\n%s\n' "$IMAGE" "$2" > "$WORKDIR/variant-$1/Dockerfile"
  cp "$WORKDIR/migration.py" "$WORKDIR/variant-$1/"
  docker build -q -t "$PREFIX-variant:$1-$$" "$WORKDIR/variant-$1" >/dev/null || fail "build of the variant $1"
  VARIANTS+=("$PREFIX-variant:$1-$$")
}
cat > "$WORKDIR/migration.py" <<EOF
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("parametres", "$LAST_MIGRATION")]
    operations = [migrations.RunSQL("CREATE TABLE auto_update_test (id integer)", "DROP TABLE auto_update_test")]
EOF
variant ok 'LABEL org.probant.test="ok"'
variant broken 'USER root
RUN printf "#!/bin/sh\nexit 1\n" > /app/docker/entrypoint.sh && chmod 755 /app/docker/entrypoint.sh
USER probant'
variant migration 'USER root
COPY migration.py /app/parametres/migrations/9001_auto_update_test.py
RUN printf "#!/bin/sh\ncd /app\npython manage.py startup\nexit 1\n" > /app/docker/entrypoint.sh && chmod -R a+rX /app && chmod 755 /app/docker/entrypoint.sh
USER probant'
publish_next() {  # publish_next VARIANT [KEY]: the variant as version NEXT in the registry, signed with KEY (none: unsigned)
  docker tag "$PREFIX-variant:$1-$$" "$PROBANT_TEST_IMAGE:$NEXT"
  docker push -q "$PROBANT_TEST_IMAGE:$NEXT" >/dev/null
  docker image rm "$PROBANT_TEST_IMAGE:$NEXT" >/dev/null 2>&1 || true
  if [ -n "${2:-}" ]; then sign_tag "$2" "$NEXT"; fi
}

echo "Local copy of the public repository (tags v$VERSION and v$NEXT, /releases/latest)"
for v in "$VERSION" "$NEXT"; do
  TAG="$WORKDIR/repository/raw/refs/tags/v$v"
  mkdir -p "$TAG/docker"
  (cd "$SOURCE" && cp get.sh docker-compose.yml .env.example install.sh update.sh check.sh auto-update.sh "$TAG/" && cp docker/Caddyfile "$TAG/docker/")
  echo "$v" > "$TAG/VERSION"
done
echo "# files of version $NEXT" >> "$WORKDIR/repository/raw/refs/tags/v$NEXT/docker-compose.yml"
# release_of VERSION: the list of sums of the files of its tag (docker/make_file_sums.sh), signed with the good test key
release_of() {
  out="$WORKDIR/repository/releases/download/v$1"
  bash "$SOURCE/docker/make_file_sums.sh" "$out" "$WORKDIR/repository/raw/refs/tags/v$1" >/dev/null || fail "list of $1"
  "$COSIGN" sign-blob --yes --key "$WORKDIR/keys/good.key" --use-signing-config=false --tlog-upload=false \
    --bundle "$out/probant-$1-files.sha256.sigstore.json" "$out/probant-$1-files.sha256" >/dev/null 2>&1 || fail "signature of the list $1"
}
for v in "$VERSION" "$NEXT"; do release_of "$v"; done
latest() { echo "$1" > "$WORKDIR/latest"; }
latest "$VERSION"
cat > "$WORKDIR/server.py" <<'EOF'
import functools, http.server, sys
latest, root, port = sys.argv[1], sys.argv[2], int(sys.argv[3])
class Handler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path.split("?")[0] == "/releases/latest":
            self.send_response(302)
            self.send_header("Location", "/releases/tag/v" + open(latest).read().strip())
            self.end_headers()
        elif self.path.startswith("/releases/tag/"):
            self.send_response(200); self.end_headers(); self.wfile.write(b"release")
        else:
            super().do_GET()
    def log_message(self, *a): pass
http.server.ThreadingHTTPServer(("127.0.0.1", port), functools.partial(Handler, directory=root)).serve_forever()
EOF
python3 "$WORKDIR/server.py" "$WORKDIR/latest" "$WORKDIR/repository" "$SERVER_PORT" &
SERVER_PID=$!
for _ in $(seq 30); do curl -fs "$PROBANT_TEST_SOURCE/raw/refs/tags/v$VERSION/VERSION" >/dev/null && break; sleep 1; done

echo "Installation: get.sh --version $VERSION --port $PORT (automatic updates: default)"
mkdir -p "$WORKDIR/server"
cd "$WORKDIR/server"
curl -fsSL "$PROBANT_TEST_SOURCE/raw/refs/tags/v$VERSION/get.sh" | sh -s -- --version "$VERSION" --port "$PORT" --skip-check || fail "get.sh"
cd probant
URL="http://127.0.0.1:$PORT"
[ -x auto-update.sh ] || fail "auto-update.sh not downloaded"
UNIT="$(find "$WORKDIR/systemd" -name '*.timer' -exec basename {} .timer \;)"
[ -n "$UNIT" ] || fail "no systemd timer"
grep -qx 'OnCalendar=\*-\*-\* 04:00:00' "$WORKDIR/systemd/$UNIT.timer" || fail "time of the timer"
grep -qx 'RandomizedDelaySec=3600' "$WORKDIR/systemd/$UNIT.timer" || fail "random delay"
grep -qx "ExecStart=/bin/sh $(pwd)/auto-update.sh" "$WORKDIR/systemd/$UNIT.service" || fail "command of the timer"
grep -qx "enable --now $UNIT.timer" "$WORKDIR/systemctl.log" || fail "timer not enabled"
ok "timer set up by get.sh: $UNIT (04:00, random delay of 1 hour)"
choice() { docker compose exec -T web cat /data/auto-update/choice | grep -E '^(mode|delay)=' | tr '\n' ' '; }
[ "$(choice)" = "mode=automatic delay=3 " ] || fail "choice of a new installation: $(choice)"
ok "new installation made with one command: choice \"automatic\" (wait 3 days)"

if [ "$DATABASE" = postgresql ]; then
  echo "PostgreSQL: the installation moves to the \"postgres\" profile (empty database)"
  PG_PASSWORD="$(LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c 24 || true)"
  sed -i -e "s|^COMPOSE_PROFILES=.*|COMPOSE_PROFILES=postgres|" -e "s|^POSTGRES_PASSWORD=.*|POSTGRES_PASSWORD=$PG_PASSWORD|" \
         -e "s|^DATABASE_URL=.*|DATABASE_URL=postgres://probant:$PG_PASSWORD@db:5432/probant|" .env
  if [ -n "${POSTGRES_IMAGE:-}" ]; then docker tag "$POSTGRES_IMAGE" postgres:16; fi
  docker compose up -d >/dev/null 2>&1 || fail "start with PostgreSQL"
  for _ in $(seq 90); do curl -fs "$URL/sante/" >/dev/null && break; sleep 2; done
  [ "$(docker compose exec -T web python manage.py shell --no-imports -c 'from django.db import connection; print(connection.vendor)')" = postgresql ] || fail "PostgreSQL"
  docker compose exec -T web python manage.py auto_update --set-choice automatic >/dev/null
  ok "PostgreSQL in its container"
fi

docker compose exec -T web python manage.py shell -c "
from espaces.creation import creer
from referentiel.models import Utilisateur
u = Utilisateur(username='admin@example.test', email='admin@example.test', first_name='Test', role='admin', is_staff=True, is_superuser=True)
u.set_password('Essai-mise-a-jour-2026'); u.save()
creer('Second space', 'second', u)" >/dev/null || fail "data of the test"
ok "an account and a second space"

set_choice() { docker compose exec -T web python manage.py auto_update --set-choice "$1" --delay "${2:-0}" >/dev/null; }
run() {  # run: one run of auto-update.sh, by hand as the timer would
  sh ./auto-update.sh > "$WORKDIR/run.log" 2>&1 || fail "auto-update.sh stopped with an error: $(tail -5 "$WORKDIR/run.log")"
}
# result STATE [REASON]: the result in the data volume, read by the tool's own parser
result() {
  got="$(docker compose exec -T web python manage.py shell --no-imports -c "
from parametres import mise_a_jour_auto as MA
r, invalide = MA.lire_resultat()
print('invalid' if invalide else (r['state'] + ' ' + r.get('reason', '-') + ' ' + r.get('restored', '-')) if r else 'none')" | tail -1)"
  [ "$got" = "$1 ${2:--} ${3:--}" ] || fail "result: expected \"$1 ${2:--} ${3:--}\", got \"$got\""
}
image_is() { grep -qx "IMAGE=$1" .env || fail "IMAGE in .env: $(grep '^IMAGE=' .env)"; }
healthy() {
  for _ in $(seq 90); do curl -fs "$URL/sante/" >/dev/null && break; sleep 2; done
  curl -fsS "$URL/sante/" | grep -q '"etat": "ok"' || fail "health"
}
data_kept() {
  docker compose exec -T web python manage.py shell --no-imports -c "
from referentiel.models import Utilisateur
from espaces.models import Espace
assert Utilisateur.objects.filter(email='admin@example.test').exists(), 'account lost'
assert Espace.objects.filter(code='second').exists(), 'space lost'" || fail "data lost"
}
migrations_of() {  # migrations_of SPACE: the test migration is applied in this space (yes / no)
  docker compose exec -T ${1:+-e SPACE=$1} web python manage.py shell --no-imports -c "
from django.db.migrations.recorder import MigrationRecorder
from espaces import contexte as E
print('yes' if ('parametres', '9001_auto_update_test') in MigrationRecorder(E.connexion()).applied_migrations() else 'no')" | tail -1
}
FIRST_IMAGE="$(grep '^IMAGE=' .env | cut -d= -f2-)"

echo "1. Choice \"off\": nothing is checked"
set_choice off
run; result off; image_is "$FIRST_IMAGE"
ok "off"

echo "2. The image that runs is the latest one: nothing to do"
set_choice automatic 0
run; result up_to_date; image_is "$FIRST_IMAGE"
ok "nothing to do"

echo "3. Version $NEXT without a signature: nothing is installed"
publish_next ok; latest "$NEXT"
run; result refused signature; image_is "$FIRST_IMAGE"
healthy
ok "unsigned image refused"

echo "4. Version $NEXT signed with another key: nothing is installed"
publish_next ok other
run; result refused signature; image_is "$FIRST_IMAGE"
ok "signature of another key refused"

echo "5. \"Notify only\": the new version is shown, nothing is installed"
publish_next ok good
set_choice notify 0
run; result available; image_is "$FIRST_IMAGE"
ok "notify only"

echo "6. Window of 3 days after the publication: not yet"
set_choice automatic 3
run; result waiting; image_is "$FIRST_IMAGE"
docker compose exec -T web cat /data/auto-update/result | grep -q "^install_after=$(date -u -d '+3 days' +%Y-%m-%d)$" || fail "date of the window"
ok "window of 3 days"

echo "6b. Version $NEXT without a list of sums in its release: nothing is installed"
set_choice automatic 0
NEXT_TAG="$WORKDIR/repository/raw/refs/tags/v$NEXT"
NEXT_LIST="$WORKDIR/repository/releases/download/v$NEXT/probant-$NEXT-files.sha256"
mv "$NEXT_LIST" "$WORKDIR/list.good"
run; result refused signature; image_is "$FIRST_IMAGE"
grep -q "has no list of the SHA-256 sums" auto-update.log || fail "no list: $(tail -5 auto-update.log)"
mv "$WORKDIR/list.good" "$NEXT_LIST"
ok "no list: refused"

echo "6c. A file of the tag of $NEXT changed after the release: nothing is installed, the files stay"
cp "$NEXT_TAG/docker/Caddyfile" "$WORKDIR/Caddyfile.good"
echo "# changed" >> "$NEXT_TAG/docker/Caddyfile"
run; result refused signature; image_is "$FIRST_IMAGE"
grep -q "docker/Caddyfile does not match its SHA-256 sum" auto-update.log || fail "file not named: $(tail -5 auto-update.log)"
grep -q "files of version $NEXT" docker-compose.yml && fail "files of the new version put in place"
cmp -s docker/Caddyfile "$WORKDIR/repository/raw/refs/tags/v$VERSION/docker/Caddyfile" || fail "docker/Caddyfile changed"
healthy
ok "a changed file: refused before any file is replaced"

echo "6d. The list changed after its signature, to match the changed file: nothing is installed"
cp "$NEXT_LIST" "$WORKDIR/list.good"
bash "$SOURCE/docker/make_file_sums.sh" "$(dirname "$NEXT_LIST")" "$NEXT_TAG" >/dev/null
run; result refused signature; image_is "$FIRST_IMAGE"
grep -q "for the list of sums" auto-update.log || fail "signature of the list not refused: $(tail -5 auto-update.log)"
cp "$WORKDIR/list.good" "$NEXT_LIST"; cp "$WORKDIR/Caddyfile.good" "$NEXT_TAG/docker/Caddyfile"
ok "a list changed after its signature: refused"

echo "7. New image that does not start: going back, nothing restored, data kept"
publish_next broken good
set_choice automatic 0
run; result rolled_back health no; image_is "$FIRST_IMAGE"
grep -q "files of version $NEXT" docker-compose.yml && fail "files of the new version left in place"
healthy; data_kept
ok "going back without restore"

echo "8. The same image the next night: not tried again"
run; result available already_failed; image_is "$FIRST_IMAGE"
ok "a failed image is not tried again"

echo "9. Migration applied, then failure: going back with the restore of each space"
publish_next migration good
run; result rolled_back health yes; image_is "$FIRST_IMAGE"
healthy; data_kept
[ "$(migrations_of '')" = no ] && [ "$(migrations_of second)" = no ] || fail "migration left in a database"
grep -q "restore of backup-.*-before-update.zip" auto-update.log || fail "no restore in the log"
ok "migration undone in both spaces, data kept, /sante/ green"

echo "10. Two runs at the same time, and ./update.sh during a run"
publish_next ok good
sh ./auto-update.sh > "$WORKDIR/first.log" 2>&1 &
FIRST=$!
for _ in $(seq 100); do [ -f .update.lock/pid ] && break; sleep 0.1; done
[ -f .update.lock/pid ] || fail "no lock"
sh ./auto-update.sh > "$WORKDIR/second.log" 2>&1 || fail "second run"
grep -q "Another update is running" "$WORKDIR/second.log" || fail "second run not stopped: $(cat "$WORKDIR/second.log")"
if ./update.sh > "$WORKDIR/manual.log" 2>&1; then fail "update.sh ran during the automatic update"; fi
grep -q "Another update is running" "$WORKDIR/manual.log" || fail "update.sh: $(cat "$WORKDIR/manual.log")"
ok "one run at a time (lock shared with update.sh)"
wait "$FIRST" || fail "first run"

echo "11. Successful update"
result updated
grep -Eqx "IMAGE=$PROBANT_TEST_IMAGE:$NEXT@sha256:[0-9a-f]{64}" .env || fail "IMAGE after the update: $(grep '^IMAGE=' .env)"
grep -q "files of version $NEXT" docker-compose.yml || fail "files of version $NEXT"
docker compose exec -T web sh -c 'ls /data/backups/*before-update.zip /data/backups/spaces/second/*before-update.zip' >/dev/null || fail "backups before the update"
[ "$(docker inspect -f '{{index .Config.Labels "org.probant.test"}}' "$(docker compose ps -q web)")" = ok ] || fail "image of the service"
healthy; data_kept
ok "version $NEXT installed, pinned by its digest; data kept"

echo "12. The next night: nothing to do"
run; result up_to_date
ok "nothing to do after the update"
[ -z "$(ls -A .update.lock 2>/dev/null)" ] || fail "lock left"
echo "PASSED: automatic updates ($DATABASE): signature, window, notify, list of sums, going back with and without restore, lock, update."
