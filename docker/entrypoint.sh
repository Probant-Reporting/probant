#!/bin/sh
# Image entry point. "server" (the default; "serveur" still accepted): preparation (folders, backup before migrating,
# migrations), automatic backups, reminders, data check and large imports in the background, then the gunicorn
# server. Any other command is run as is, e.g. "docker compose exec web python manage.py backup".
set -e
# files created by the tool: readable by its user only (also set by the tool itself, config/settings.py)
umask 077
cd /app
case "${1:-server}" in
  server|serveur) ;;
  *) exec "$@" ;;
esac
python manage.py startup
# automatic backups: enabling, frequency, time and number kept are set in the tool (Settings › Hosting)
python manage.py backup --schedule &
# e-mail reminders: sent only if the responsible team has enabled them (Dashboard › Reminders)
python manage.py send_reminders --schedule &
# data check: consistency of each space's database every night at DATA_CHECK_TIME (read only; Settings › Hosting, /sante/)
python manage.py check_data --schedule &
# large value imports (above BACKGROUND_IMPORT_ROWS rows) started in the tool: run here, with a progress bar in the tool
python manage.py run_imports --schedule &
# gunicorn: English names, otherwise the former French names (GUNICORN_PROCESSUS, GUNICORN_FILS, GUNICORN_DELAI).
# Workers: one per processor, from 2 to 4, unless GUNICORN_WORKERS is set (a worker uses one processor at a time;
# about 170 MB of memory each). Keep-alive above the proxy's idle timeout (Caddy: 60 s), see docs/installation.md.
CPUS=$(nproc 2>/dev/null || echo 2)
WORKERS=$(( CPUS < 2 ? 2 : (CPUS > 4 ? 4 : CPUS) ))
exec gunicorn config.wsgi:application \
  --bind 0.0.0.0:8000 \
  --workers "${GUNICORN_WORKERS:-${GUNICORN_PROCESSUS:-$WORKERS}}" \
  --threads "${GUNICORN_THREADS:-${GUNICORN_FILS:-4}}" \
  --timeout "${GUNICORN_TIMEOUT:-${GUNICORN_DELAI:-120}}" \
  --keep-alive "${GUNICORN_KEEPALIVE:-75}" \
  --forwarded-allow-ips "*" \
  --access-logfile - --error-logfile - \
  --access-logformat '%(t)s %(h)s "%(r)s" %(s)s %(b)s %(M)sms'
