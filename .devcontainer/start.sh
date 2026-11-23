#!/usr/bin/env bash
# Starts the site on port 8000. Run this script again after "git pull" (Ctrl+C to stop the site).
set -euo pipefail
cd "$(dirname "$0")/.."
if (exec 3<>/dev/tcp/127.0.0.1/8000) 2>/dev/null; then
  echo "The site is already running on port 8000 (\"Ports\" tab)."
  exit 0
fi
pip install --disable-pip-version-check -q -r requirements.txt  # in case a dependency was added
python manage.py migrate --noinput
# The demo command refuses a database that it does not recognise as a demo (for example, the admin password was
# changed before the update). Never block the start for that: say it and continue with the database as it is.
if ! python manage.py load_demo; then
  echo
  echo "Note: the demo data was not loaded (see the message above). The site starts with the current database."
  echo "To start again from the demo: python3 manage.py load_demo --reset (this deletes the data of this Codespace)."
fi
echo
echo "Site: \"Ports\" tab, row 8000, globe icon. Accounts: admin / validateur / contributeur, password demo-probant-2026."
echo
exec python manage.py runserver 0.0.0.0:8000
