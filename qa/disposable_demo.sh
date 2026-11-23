#!/usr/bin/env bash
# Disposable demo for acceptance testing: a new database in a temporary folder, served in production mode (gunicorn,
# DJANGO_DEBUG=0), without touching the databases in local-data/ or the demos on ports 8000 and 8001.
#
#   qa/disposable_demo.sh [--client exemplia] [--smtp] [--spaces] [--port N]
#
#   --client exemplia the only demo (default): fictitious manufacturer, Voluntary Standard VS, 2024 and 2025 closed,
#                     2026 open (data entry, validation, reminders)
#   --smtp            also starts the fake e-mail server (qa/fake_smtp.py, port 1025) and connects the tool to it
#   --spaces          two spaces (docs/spaces.md): main "RSE" and "Achats" (/espace/achats/); run the acceptance
#                     tests twice: --url http://127.0.0.1:N then --url http://127.0.0.1:N/espace/achats
#                     (--espaces: former name, still accepted)
#   --port N          demo port (8013 by default); 8000 and 8001 are refused
#
# Shows at the end the folder, the database (to pass to browser_check.py --base) and the process numbers to stop
# (kill <pid>). Nothing is deleted automatically: remove the temporary folder after the acceptance tests.
set -eu

CLIENT=exemplia
PORT=8013
SMTP=0
SPACES=""
while [ $# -gt 0 ]; do
  case "$1" in
    --client) CLIENT="${2:-}"; shift 2 ;;
    --port) PORT="${2:-}"; shift 2 ;;
    --smtp) SMTP=1; shift ;;
    --spaces|--espaces) SPACES="--spaces"; shift ;;
    -h|--help) sed -n '2,16p' "$0"; exit 0 ;;
    *) echo "Unknown option: $1 (see --help)" >&2; exit 2 ;;
  esac
done

case "$CLIENT" in exemplia) ;; *) echo "--client must be exemplia (Exemplia is the only demo)" >&2; exit 2 ;; esac
case "$PORT" in ''|*[!0-9]*) echo "--port must be a number" >&2; exit 2 ;; esac
if [ "$PORT" = 8000 ] || [ "$PORT" = 8001 ]; then
  echo "Port $PORT refused: it is reserved for the reference demos (8000, 8001). Choose another port (e.g. 8013)." >&2
  exit 2
fi
if (exec 3<>"/dev/tcp/127.0.0.1/$PORT") 2>/dev/null; then
  echo "Port $PORT already in use: choose another port." >&2
  exit 2
fi

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
FOLDER="$(mktemp -d "${TMPDIR:-/tmp}/disposable_demo_${CLIENT}_XXXXXX")"
export DATA_DIR="$FOLDER"
export SQLITE_FILE="demo.sqlite3"
export DJANGO_DEBUG=0
# SMTP_HOTE: former French name of SMTP_HOST, unset too so that a value inherited from the shell cannot be used
unset DATABASE_URL POSTGRESQL_ADDON_URI SMTP_HOST SMTP_HOTE 2>/dev/null || true

cd "$ROOT"
python3 manage.py migrate --noinput >"$FOLDER/migrate.log" 2>&1
python3 manage.py load_demo --client "$CLIENT" $SPACES >"$FOLDER/load_demo.log" 2>&1

PID_SMTP=""
if [ "$SMTP" = 1 ]; then
  python3 qa/fake_smtp.py --port 1025 --file "$FOLDER/emails.json" >"$FOLDER/fake_smtp.log" 2>&1 &
  PID_SMTP=$!
  export SMTP_HOST=127.0.0.1 SMTP_PORT=1025 SMTP_SECURITY=none
fi

# Static files are served by WhiteNoise from static/ (WHITENOISE_USE_FINDERS): no collectstatic,
# nothing is written to the repository.
nohup gunicorn config.wsgi:application --bind "127.0.0.1:$PORT" --workers 2 --threads 4 --keep-alive 75 --pid "$FOLDER/gunicorn.pid" \
  >"$FOLDER/gunicorn.log" 2>&1 &
PID=$!

for _ in $(seq 1 40); do
  if (exec 3<>"/dev/tcp/127.0.0.1/$PORT") 2>/dev/null; then break; fi
  sleep 0.5
done

echo "Disposable $CLIENT demo: http://127.0.0.1:$PORT (commit $(git rev-parse --short HEAD 2>/dev/null || echo '?'))"
echo "Folder   : $FOLDER"
echo "Database : $FOLDER/$SQLITE_FILE   (browser_check.py --base ...)"
echo "Stop     : kill $PID${PID_SMTP:+ $PID_SMTP}"
[ -n "$PID_SMTP" ] && echo "E-mails  : $FOLDER/emails.json (fake server on 127.0.0.1:1025)"
exit 0
