#!/usr/bin/env bash
# "Blank machine" test: copies the repository into an empty folder, runs ./install.sh (image build, start with an
# empty database), then checks: health page, "Setup" wizard instead of the login page, static files, production
# security settings (check --deploy), backup, update (./update.sh), and that the data survives a restart.
# Everything is removed at the end (containers, volumes, folder).
#
#   bash docker/test_installation.sh          (Docker required; ~2 min the first time)
set -euo pipefail
SOURCE="$(cd "$(dirname "$0")/.." && pwd)"
WORKDIR="$(mktemp -d)"
PROJECT="probant-essai-$$"
PORT="${TEST_PORT:-${PORT_ESSAI:-18$(( $$ % 900 + 100 ))}}"
export COMPOSE_PROJECT_NAME="$PROJECT"

cleanup() {
  (cd "$WORKDIR" && docker compose down -v --remove-orphans >/dev/null 2>&1) || true
  docker image rm "probant:local-$PROJECT" >/dev/null 2>&1 || true
  rm -rf "$WORKDIR"
}
trap cleanup EXIT
fail() { echo "FAILED: $*"; (cd "$WORKDIR" && docker compose logs --tail 60 web) || true; exit 1; }
ok() { echo "  ok  $*"; }

echo "Copying the repository (tracked and new files, without database or data) into $WORKDIR"
(cd "$SOURCE" && git ls-files -co --exclude-standard -z | xargs -0 -I{} cp --parents {} "$WORKDIR" 2>/dev/null || true)
cd "$WORKDIR"
[ ! -f .env ] && [ ! -e db.sqlite3 ] || fail "the test folder is not blank"

echo "Installation: ./install.sh --port $PORT"
export IMAGE="probant:local-$PROJECT"  # image specific to this test (does not touch an existing installation)
./install.sh --port "$PORT" || fail "install.sh"
grep -q "^HTTP_PORT=$PORT" .env || fail ".env not created"

URL="http://127.0.0.1:$PORT"
code() { curl -s -o /dev/null -w '%{http_code}' "$@"; }
HEALTH=$(curl -s "$URL/sante/")
grep -q '"etat": "ok"' <<<"$HEALTH" || fail "health: $HEALTH"; ok "health page: $HEALTH"
LOCATION=$(curl -s -o /dev/null -w '%{redirect_url}' "$URL/")
[[ "$LOCATION" == */mise-en-place/ ]] || fail "the home page leads to \"$LOCATION\""; ok "empty database: the home page leads to the wizard"
[[ "$(curl -s -o /dev/null -w '%{redirect_url}' "$URL/connexion/")" == */mise-en-place/ ]] || fail "login"; ok "so does the login page"
PAGE=$(curl -s "$URL/mise-en-place/")
# default interface language of a new installation: English (DEFAULT_LANGUAGE=en)
grep -q "Administrator account" <<<"$PAGE" || fail "wizard"; ok "the wizard responds (step 1: Administrator account)"
[ "$(code "$URL/static/admin/css/base.css")" = 200 ] || fail "static files"
grep -qi "cache-control: max-age" <<<"$(curl -sI "$URL/static/admin/css/base.css")" || fail "static files without cache"
ok "static files served by WhiteNoise (browser cache)"
HEADERS=$(curl -sI "$URL/mise-en-place/")
grep -qi "x-content-type-options: nosniff" <<<"$HEADERS" && grep -qi "x-frame-options: deny" <<<"$HEADERS" || fail "security headers"
ok "security headers"
[ "$(curl -s -H 'Accept-Encoding: gzip' -o /dev/null -w '%{size_download}' "$URL/mise-en-place/")" -lt 80000 ] || fail "pages not compressed"
ok "pages compressed (gzip)"

docker compose exec -T -e DJANGO_HTTPS=1 -e DOMAIN=reporting.example.com web python manage.py check --deploy --fail-level WARNING \
  || fail "check --deploy"; ok "check --deploy without warnings (HTTPS)"
docker compose exec -T web sh -c 'test -s /data/.secret_key && test "$(id -u)" = 1000' || fail "secret key / user"
ok "secret key generated in /data, service not running as root"

echo "Setup (administrator account) then backup"
docker compose exec -T web python manage.py shell -c "
from referentiel.models import Utilisateur
u = Utilisateur(username='admin@example.test', email='admin@example.test', first_name='Test', role='admin', is_staff=True, is_superuser=True)
u.set_password('Essai-installation-2026'); u.save()" || fail "account creation"
docker compose exec -T web python manage.py backup | tail -1 || fail "backup"
docker compose exec -T web sh -c 'ls /data/backups/backup-*.zip' >/dev/null || fail "archive missing"; ok "backup in /data/backups"
# file rights: what the tool makes is readable by its user only, also through "docker compose exec"
docker compose exec -T web sh -c 'umask 000; python manage.py backup --reason rights' >/dev/null || fail "backup (umask 000)"
RIGHTS=$(docker compose exec -T web sh -c 'stat -c "%a %n" /data/backups/backup-*-rights.zip /data/backups /data/db.sqlite3 /data/.secret_key')
! grep -qv '^[67]00 ' <<<"$RIGHTS" || fail "rights: $RIGHTS"; ok "archives, database, key and folders: 600 / 700"
# code of the tool: owned by root, not writable by the user of the tool; no notes of the assistants
docker compose exec -T web sh -c 'test "$(stat -c %U /app)" = root && ! touch /app/manage.py 2>/dev/null && ! touch /app/x 2>/dev/null' \
  || fail "the code of the tool can be changed by its user"
docker compose exec -T web sh -c 'test ! -e /app/.claude && test ! -e /app/.impeccable && test -r /app/staticfiles/admin/css/base.css' \
  || fail "content of /app"
ok "code owned by root and read-only for the tool; .claude and .impeccable not in the image"

echo "Update: ./update.sh"
./update.sh || fail "update.sh"
docker compose exec -T web sh -c 'ls /data/backups/*before-update.zip' >/dev/null || fail "no backup before the update"
ok "automatic backup before the update"
[ "$(code "$URL/")" = 302 ] && [[ "$(curl -s -o /dev/null -w '%{redirect_url}' "$URL/")" == */connexion/* ]] || fail "after the update"
ok "after the update and restart: account kept, the home page leads to the login page"
docker compose exec -T web python manage.py shell -c "
from referentiel.models import Utilisateur; assert Utilisateur.objects.filter(email='admin@example.test').exists()" || fail "data lost"
ok "data kept in the volume"
echo "PASSED: installation on a blank machine in one command."
