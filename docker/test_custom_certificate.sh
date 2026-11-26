#!/usr/bin/env bash
# "Company network" test, with Docker: a test certificate authority, a server certificate signed by it, then
#   1. ./install.sh --image … --domain NAME --cert FILE --key FILE --ca-cert FILE (image from a local registry):
#      Caddy serves this certificate (curl --cacert, name forced to 127.0.0.1), health page green through HTTPS, Caddy
#      never asks Let's Encrypt; the tool trusts the authority for its outgoing connections (a call from the tool to
#      Caddy over HTTPS), every process of the tool has SSL_CERT_FILE, the key never enters the container of the tool;
#      renewal (./install.sh --cert --key again): Caddy serves the new certificate;
#   2. the same without Internet access: offline package (docker/make_offline_package.sh, with the image of Caddy),
#      ./install.sh --offline … --domain --cert --key, curl and wget fail and write down any call, no image download.
# Everything is removed at the end (containers, volumes, images and folders of this test).
#
#   bash docker/test_custom_certificate.sh                                  (builds the image of this folder)
#   IMAGE_UNDER_TEST=probant:local bash docker/test_custom_certificate.sh   (an image already built from this folder)
#   TEST_HTTPS_PORT=8443 TEST_HTTP_PORT=8080: other ports for Caddy than 443 and 80 (docker-compose.override.yml)
#   REGISTRY_IMAGE=registry:2 (default): image of the local registry
#   TEST_SKIP_SERVER_CHECK=1: step 1 without the network checks of check.sh (a machine whose proxy has another
#   authority); the checks of the certificates still run (check.sh --certificate-only)
set -euo pipefail
SOURCE="$(cd "$(dirname "$0")/.." && pwd)"
WORKDIR="$(mktemp -d)"
DOMAIN="reporting.probant.test"
PORT="${TEST_PORT:-18$(( $$ % 900 + 100 ))}"
REGISTRY_PORT="${REGISTRY_PORT:-14$(( $$ % 900 + 100 ))}"
HTTPS_PORT="${TEST_HTTPS_PORT:-443}"
HTTP_PORT="${TEST_HTTP_PORT:-80}"
VERSION="$(cat "$SOURCE/VERSION")"
REGISTRY="127.0.0.1:$REGISTRY_PORT"
NAME="$REGISTRY/probant-certificate-$$"
OFFLINE_NAME="127.0.0.1:9/probant-certificate-$$"  # a registry address where nothing answers
CADDY="$(awk '/^  caddy:/ { s = 1 } s && /^    image:/ { print $2; exit }' "$SOURCE/docker-compose.yml")"
BUILT=""
EVENTS_PID=""

cleanup() {
  for d in "$WORKDIR/online/probant" "$WORKDIR/offline/probant"; do
    (cd "$d" 2>/dev/null && docker compose down -v --remove-orphans >/dev/null 2>&1) || true
  done
  docker rm -f -v "probant-certificate-registry-$$" >/dev/null 2>&1 || true
  docker image rm "$NAME:$VERSION" "$OFFLINE_NAME:$VERSION" ${BUILT:+"$BUILT"} >/dev/null 2>&1 || true
  [ -n "$EVENTS_PID" ] && kill "$EVENTS_PID" 2>/dev/null || true
  rm -rf "$WORKDIR"
}
trap cleanup EXIT
fail() {
  echo "FAILED: $*"
  for d in "$WORKDIR/online/probant" "$WORKDIR/offline/probant"; do
    (cd "$d" 2>/dev/null && docker compose logs --tail 40 web caddy) || true
  done
  exit 1
}
ok() { echo "  ok  $*"; }

IMAGE="${IMAGE_UNDER_TEST:-}"
if [ -z "$IMAGE" ]; then
  IMAGE="probant:certificate-test-$$"; BUILT="$IMAGE"
  echo "Building the image of this folder ($IMAGE)"
  docker build -q -t "$IMAGE" "$SOURCE" >/dev/null
fi
# Caddy is on this machine before the checks: afterwards, no image may be downloaded from outside
docker image inspect "$CADDY" >/dev/null 2>&1 || docker pull -q "$CADDY" >/dev/null

echo "Test authority and certificates for $DOMAIN"
C="$WORKDIR/certificates"
mkdir -p "$C"
openssl req -x509 -newkey rsa:2048 -nodes -keyout "$C/ca.key" -out "$C/company-ca.pem" -days 60 \
  -subj "/CN=Probant Test Company CA" -addext "basicConstraints=critical,CA:TRUE" \
  -addext "keyUsage=critical,keyCertSign,cRLSign" 2>/dev/null
# server_certificate NAME: certificate (with the name of the Caddy service, for the call from the tool) and key
server_certificate() {
  openssl req -newkey rsa:2048 -nodes -keyout "$C/$1.key" -out "$C/$1.csr" -subj "/CN=$DOMAIN" 2>/dev/null
  printf 'subjectAltName=DNS:%s,DNS:caddy\nbasicConstraints=CA:FALSE\nextendedKeyUsage=serverAuth\nsubjectKeyIdentifier=hash\nauthorityKeyIdentifier=keyid\n' \
    "$DOMAIN" > "$C/$1.ext"
  openssl x509 -req -in "$C/$1.csr" -CA "$C/company-ca.pem" -CAkey "$C/ca.key" -CAcreateserial -out "$C/$1.pem" \
    -days 90 -extfile "$C/$1.ext" 2>/dev/null
}
server_certificate first
server_certificate second

# files of an installation; other ports for Caddy if asked (the default ones: 443 and 80)
files() {
  mkdir -p "$1/docker"
  (cd "$SOURCE" && cp -p docker-compose.yml .env.example install.sh update.sh check.sh "$1/" && cp -p docker/Caddyfile "$1/docker/")
  if [ "$HTTPS_PORT" != 443 ] || [ "$HTTP_PORT" != 80 ]; then
    printf 'services:\n  caddy:\n    ports: !override\n      - "127.0.0.1:%s:80"\n      - "127.0.0.1:%s:443"\n' \
      "$HTTP_PORT" "$HTTPS_PORT" > "$1/docker-compose.override.yml"
  fi
}
# https PATH: curl as a browser of the company would, with the authority, the name forced to this machine
https() { curl -fsS --noproxy "*" --cacert "$C/company-ca.pem" --resolve "$DOMAIN:$HTTPS_PORT:127.0.0.1" "https://$DOMAIN:$HTTPS_PORT$1"; }
served_serial() {
  openssl s_client -connect "127.0.0.1:$HTTPS_PORT" -servername "$DOMAIN" </dev/null 2>/dev/null | openssl x509 -noout -serial
}
wait_https() {
  for _ in $(seq 60); do https /sante/ >/dev/null 2>&1 && return 0; sleep 2; done
  return 1
}
# checks of a running installation (folder: the current one)
check_running() {
  wait_https || fail "HTTPS through Caddy"
  https /sante/ | grep -q '"etat": "ok"' || fail "health page through HTTPS"
  ok "Caddy serves the certificate of the company (curl --cacert), health page green"
  [ "$(served_serial)" = "$(openssl x509 -in "$C/first.pem" -noout -serial)" ] || fail "served certificate"
  if curl -fsS --noproxy "*" --resolve "$DOMAIN:$HTTPS_PORT:127.0.0.1" "https://$DOMAIN:$HTTPS_PORT/sante/" >/dev/null 2>&1; then
    fail "the certificate is trusted without the authority"
  fi
  if docker compose logs caddy 2>&1 | grep -Eiq 'acme|obtain|letsencrypt'; then
    fail "Caddy called a certificate authority: $(docker compose logs caddy 2>&1 | grep -Ei 'acme|obtain|letsencrypt' | head -3)"
  fi
  ok "Caddy never asks Let's Encrypt (no ACME in its log)"
  [ "$(stat -c %a certificates/https/key.pem)" = 600 ] || fail "rights of the key"
  if docker compose exec -T web sh -c 'grep -rl "PRIVATE KEY" /etc/probant /data 2>/dev/null' | grep -q .; then
    fail "a private key is in the container of the tool"
  fi
  ok "key in 0600, never in the container of the tool"
  # every process of the tool has the authorities (exported by the entry point)
  docker compose exec -T web sh -c 'n=0; for p in /proc/[0-9]*; do
      if tr "\0" "\n" < "$p/environ" 2>/dev/null | grep -qx "SSL_CERT_FILE=/data/ca-bundle.pem"; then n=$((n + 1)); fi
    done; [ "$n" -ge 3 ]' || fail "SSL_CERT_FILE in the processes of the tool"
  # outgoing connection from the tool to an HTTPS server signed by the authority (Caddy, by its service name)
  docker compose exec -T web python manage.py shell -c "
import urllib.request
assert urllib.request.urlopen('https://caddy/sante/', timeout=10).status == 200
from parametres import sante_installation as SI
ligne = SI._ligne_autorites()
assert ligne['etat'] == SI.BON and 'Probant Test Company CA' in ligne['constat'], ligne" || fail "outgoing HTTPS call of the tool"
  ok "outgoing HTTPS call of the tool trusts the authority; Settings › Health line: good"
}

# ---- 1. Installation with the image of a local registry
echo "Local registry ($REGISTRY)"
docker run -d --name "probant-certificate-registry-$$" -p "$REGISTRY:5000" "${REGISTRY_IMAGE:-registry:2}" >/dev/null
for _ in $(seq 30); do curl -fs "http://$REGISTRY/v2/" >/dev/null && break; sleep 1; done
docker tag "$IMAGE" "$NAME:$VERSION"
docker push -q "$NAME:$VERSION" >/dev/null
docker image rm "$NAME:$VERSION" >/dev/null
docker events --filter type=image --filter event=pull --format '{{.Actor.Attributes.name}}' > "$WORKDIR/pulls.log" 2>&1 &
EVENTS_PID=$!

echo "1. ./install.sh --image $NAME:$VERSION --domain $DOMAIN --cert --key --ca-cert"
files "$WORKDIR/online/probant"
cd "$WORKDIR/online/probant"
export COMPOSE_PROJECT_NAME="probant-certificate-$$"
SKIP=()
if [ -n "${TEST_SKIP_SERVER_CHECK:-}" ]; then
  SKIP=(--skip-check)
  sh check.sh --certificate-only --domain "$DOMAIN" --cert "$C/first.pem" --key "$C/first.key" \
    --ca-cert "$C/company-ca.pem" | tee "$WORKDIR/install.log" || fail "check.sh --certificate-only"
fi
./install.sh --image "$NAME:$VERSION" --domain "$DOMAIN" --port "$PORT" --cert "$C/first.pem" --key "$C/first.key" \
  --ca-cert "$C/company-ca.pem" "${SKIP[@]}" | tee -a "$WORKDIR/install.log" || fail "install.sh"
grep -q "Private key: matches the certificate" "$WORKDIR/install.log" || fail "check of the certificate"
grep -q "Chain of the certificate: complete" "$WORKDIR/install.log" || fail "check of the chain"
grep -qx "HTTPS_CERTIFICATE=files" .env || fail "HTTPS_CERTIFICATE in .env"
check_running

echo "   renewal: ./install.sh --cert <second> --key <second>"
./install.sh --cert "$C/second.pem" --key "$C/second.key" > "$WORKDIR/renew.log" || fail "renewal: $(cat "$WORKDIR/renew.log")"
for _ in $(seq 30); do
  [ "$(served_serial)" = "$(openssl x509 -in "$C/second.pem" -noout -serial)" ] && break; sleep 1
done
[ "$(served_serial)" = "$(openssl x509 -in "$C/second.pem" -noout -serial)" ] || fail "renewed certificate not served"
https /sante/ | grep -q '"etat": "ok"' || fail "health after the renewal"
ok "renewal: Caddy serves the new certificate"
grep -v "^$NAME" "$WORKDIR/pulls.log" | grep -q . && fail "image download from outside: $(cat "$WORKDIR/pulls.log")"
ok "images downloaded only from the local registry"
docker compose down -v --remove-orphans >/dev/null 2>&1
cd "$WORKDIR"

# ---- 2. Without Internet access
echo "2. Offline package and ./install.sh --offline … --domain --cert --key"
docker tag "$IMAGE" "$OFFLINE_NAME:$VERSION"
files "$WORKDIR/code"
cp -p "$SOURCE/docker/make_offline_package.sh" "$WORKDIR/code/docker/"
bash "$WORKDIR/code/docker/make_offline_package.sh" "$OFFLINE_NAME:$VERSION" "$WORKDIR/dist" | tee "$WORKDIR/package.log" \
  || fail "offline package"
docker image rm "$OFFLINE_NAME:$VERSION" >/dev/null  # only the package brings it
mkdir -p "$WORKDIR/offline" "$WORKDIR/no-network"
tar -xf "$WORKDIR/dist/probant-$VERSION-offline.tar" -C "$WORKDIR/offline"
echo "   $(tail -1 "$WORKDIR/package.log")"
for c in curl wget; do
  printf '#!/bin/sh\necho "%s $*" >> "%s/network.log"\nexit 7\n' "$c" "$WORKDIR" > "$WORKDIR/no-network/$c"
  chmod 755 "$WORKDIR/no-network/$c"
done
: > "$WORKDIR/network.log" ; : > "$WORKDIR/pulls.log"
cd "$WORKDIR/offline/probant"
if [ "$HTTPS_PORT" != 443 ] || [ "$HTTP_PORT" != 80 ]; then cp "$WORKDIR/code/docker-compose.override.yml" .; fi
export COMPOSE_PROJECT_NAME="probant-certificate-offline-$$"
PATH="$WORKDIR/no-network:$PATH" ./install.sh --offline "probant-image-$VERSION.tar.gz" --domain "$DOMAIN" --port "$PORT" \
  --cert "$C/first.pem" --key "$C/first.key" --ca-cert "$C/company-ca.pem" | tee "$WORKDIR/install-offline.log" \
  || fail "install.sh --offline"
grep -q "Loading the image of Caddy" "$WORKDIR/install-offline.log" || fail "image of Caddy from the package"
[ ! -s "$WORKDIR/network.log" ] || fail "network call: $(cat "$WORKDIR/network.log")"
[ ! -s "$WORKDIR/pulls.log" ] || fail "image download: $(cat "$WORKDIR/pulls.log")"
ok "installed from the package, image of Caddy loaded, no network call, no image download"
# the certificate of the first run is served again (the files were copied by install.sh)
check_running
echo "   renewal without Internet access: ./install.sh --cert <second> --key <second>"
PATH="$WORKDIR/no-network:$PATH" ./install.sh --cert "$C/second.pem" --key "$C/second.key" > "$WORKDIR/renew.log" \
  || fail "renewal offline: $(cat "$WORKDIR/renew.log")"
for _ in $(seq 30); do
  [ "$(served_serial)" = "$(openssl x509 -in "$C/second.pem" -noout -serial)" ] && break; sleep 1
done
[ "$(served_serial)" = "$(openssl x509 -in "$C/second.pem" -noout -serial)" ] || fail "renewed certificate not served (offline)"
[ ! -s "$WORKDIR/network.log" ] || fail "network call: $(cat "$WORKDIR/network.log")"
[ ! -s "$WORKDIR/pulls.log" ] || fail "image download: $(cat "$WORKDIR/pulls.log")"
ok "renewal without Internet access: new certificate served, nothing downloaded"
echo "PASSED: certificate of the company with Caddy, authority for the outgoing connections, renewal, offline."
