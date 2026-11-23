#!/usr/bin/env bash
# Codespace creation: dependencies, migrations, fictitious demo data.
set -euo pipefail
cd "$(dirname "$0")/.."
pip install --disable-pip-version-check -q -r requirements.txt
python manage.py migrate --noinput
# The demo command refuses a database that it does not recognise as a demo (for example, the admin password was
# changed before the update). Never block the start for that: say it and continue with the database as it is.
if ! python manage.py load_demo; then
  echo
  echo "Note: the demo data was not loaded (see the message above). The site starts with the current database."
  echo "To start again from the demo: python3 manage.py load_demo --reset (this deletes the data of this Codespace)."
fi
