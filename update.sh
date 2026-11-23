#!/usr/bin/env sh
# Updates Probant, in one command: ./update.sh
#   1. backs up each space with the version installed now ("before-update" archives in /data/backups, and
#      /data/backups/spaces/<code> for the other spaces);
#   2. new version: published image (IMAGE= in .env) or the repository code (git pull), rebuilt;
#   3. restart: the database migrations apply on their own; waits until the tool responds.
# If something goes wrong: docs/installation.md, "Going back to the previous version".
set -eu
cd "$(dirname "$0")"
[ -f .env ] || { echo "No .env file: run ./install.sh first"; exit 1; }
chmod 600 .env 2>/dev/null || true  # passwords inside (SMTP, PostgreSQL): readable by its owner only

set_value() {
  if grep -q "^$1=" .env; then sed "s|^$1=.*|$1=$2|" .env > .env.tmp && chmod 600 .env.tmp && mv .env.tmp .env; else echo "$1=$2" >> .env; fi
}

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
if grep -q "^IMAGE=..*" .env; then
  docker compose pull web
else
  if [ -d .git ]; then git pull --ff-only; fi
  set_value VERSION_COMMIT "$(git rev-parse HEAD 2>/dev/null || echo '')"
  docker compose build web
fi

echo "3. Restart (automatic migrations)…"
docker compose up -d
i=0
until docker compose exec -T web python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/sante/', timeout=3)" >/dev/null 2>&1; do
  i=$((i + 1))
  if [ "$i" -gt 90 ]; then echo "The tool is not responding after 3 minutes. Log: docker compose logs web"; exit 1; fi
  sleep 2
done
echo "Update complete: version $(docker compose exec -T web cat /app/VERSION)."
