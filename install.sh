#!/usr/bin/env sh
# Installs Probant on a server where Docker is installed, in one command:
#
#   ./install.sh                                  http://SERVER-ADDRESS:8000
#   ./install.sh --domain reporting.example.com   https://reporting.example.com (Caddy, automatic certificate)
#   ./install.sh --port 8080                      another HTTP port
#
# Creates the .env file (if it does not exist), builds the image, starts the tool and waits until it responds. The tool
# then opens on the "Setup" wizard. Running the script again does not replace an existing .env. Guide: docs/installation.md
set -eu
cd "$(dirname "$0")"

DOMAIN="" ; PORT="8000"
while [ $# -gt 0 ]; do
  case "$1" in
    --domain|--domaine) DOMAIN="$2"; shift 2 ;;  # --domaine: former French name, still accepted
    --port) PORT="$2"; shift 2 ;;
    -h|--help) sed -n '2,9p' "$0"; exit 0 ;;
    *) echo "Unknown option: $1 (see ./install.sh --help)"; exit 2 ;;
  esac
done

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is not installed: see https://docs.docker.com/engine/install/ (docs/installation.md, \"Prerequisites\")."; exit 1
fi
if ! docker compose version >/dev/null 2>&1; then
  echo "Docker Compose (v2) is missing: install the docker-compose-plugin package."; exit 1
fi
if ! docker info >/dev/null 2>&1; then
  echo "Docker is not responding (service stopped, or permissions: run with sudo or add the user to the docker group)."; exit 1
fi

# replaces "KEY=…" in .env (or adds it)
set_value() {
  if grep -q "^$1=" .env; then
    sed "s|^$1=.*|$1=$2|" .env > .env.tmp && chmod 600 .env.tmp && mv .env.tmp .env
  else
    echo "$1=$2" >> .env
  fi
}
# value of a setting in .env: English name, otherwise its former French name (.env files created before the update)
get_value() {
  v=$(grep "^$1=" .env | tail -1 | cut -d= -f2- || true)
  [ -n "$v" ] || v=$(grep "^$2=" .env | tail -1 | cut -d= -f2- || true)
  echo "$v"
}

if [ ! -f .env ]; then
  cp .env.example .env
  chmod 600 .env
  if [ -n "$DOMAIN" ]; then
    set_value DOMAIN "$DOMAIN"
    set_value DJANGO_HTTPS 1
    set_value COMPOSE_PROFILES https
    set_value HTTP_PORT "127.0.0.1:$PORT"
  else
    set_value HTTP_PORT "$PORT"
    IP=$(hostname -I 2>/dev/null | awk '{print $1}')
    [ -n "$IP" ] && set_value DOMAIN "$IP"
  fi
  set_value POSTGRES_PASSWORD "$(LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c 24)"
  if [ "${CODESPACES:-}" = "true" ]; then  # trial in GitHub Codespaces: forwarded address *.app.github.dev (HTTPS)
    set_value DJANGO_ALLOWED_HOSTS "localhost,127.0.0.1,.app.github.dev"
    set_value DJANGO_CSRF_TRUSTED_ORIGINS "https://*.app.github.dev"
  fi
  echo ".env file created (settings: docs/installation.md)."
else
  echo "Existing .env file kept."
fi
set_value VERSION_COMMIT "$(git rev-parse HEAD 2>/dev/null || echo '')"

echo "Building the image and starting (a few minutes the first time)…"
if grep -q "^IMAGE=..*" .env; then docker compose pull web; else docker compose build web; fi
docker compose up -d

echo "Waiting for the tool…"
i=0
until docker compose exec -T web python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/sante/', timeout=3)" >/dev/null 2>&1; do
  i=$((i + 1))
  if [ "$i" -gt 90 ]; then
    echo "The tool is not responding after 3 minutes. Log: docker compose logs web"; exit 1
  fi
  sleep 2
done

ADDRESS=$(get_value DOMAIN DOMAINE | cut -d, -f1)
PORT_ENV=$(get_value HTTP_PORT PORT_HTTP | awk -F: '{print $NF}')
if grep -q '^DJANGO_HTTPS=1' .env; then URL="https://$ADDRESS/"; else URL="http://${ADDRESS:-localhost}:${PORT_ENV:-8000}/"; fi
echo
if [ "${CODESPACES:-}" = "true" ]; then URL="\"Ports\" tab, row ${PORT_ENV:-8000}, globe icon"; fi
echo "Probant is running: $URL"
echo "First opening: the \"Setup\" wizard creates the administrator account. Do it now:"
echo "as long as this account does not exist, the first visitor to the address would create it."
echo "Log: docker compose logs -f web   ·   Update: ./update.sh   ·   Guide: docs/installation.md"
