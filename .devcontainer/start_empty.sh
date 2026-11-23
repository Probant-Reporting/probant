#!/usr/bin/env bash
# Starts an empty installation (no account, organisation or KPI) on port 8002, in its own database
# local-data/vide.sqlite3: the "Setup" wizard is shown instead of the login page (administrator account, structure,
# languages, organisation, frameworks, KPI sheet, team, first campaign). You can stop and resume.
# --reset (or --reinitialiser) starts again from an empty database (redo the wizard from the start). Ctrl+C to stop.
set -euo pipefail
cd "$(dirname "$0")/.."
export SQLITE_FILE=vide.sqlite3 DJANGO_DEBUG=1
if (exec 3<>/dev/tcp/127.0.0.1/8002) 2>/dev/null; then
  echo "The empty installation is already running on port 8002 (\"Ports\" tab)."
  exit 0
fi
case "${1:-}" in
  --reset|--reinitialiser) rm -f local-data/vide.sqlite3 donnees-locales/vide.sqlite3 ;;  # donnees-locales: former folder name
esac
python manage.py migrate --noinput
echo
echo "Empty installation: \"Ports\" tab, row 8002, globe icon."
echo "Without an account, the \"Setup\" wizard opens: step 1 creates the administrator account."
echo
exec python manage.py runserver 0.0.0.0:8002
