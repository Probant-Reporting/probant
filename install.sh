#!/usr/bin/env sh
# Installs Probant on a Linux server, in one command:
#
#   ./install.sh                                  http://SERVER-ADDRESS:8000
#   ./install.sh --domain reporting.example.com   https://reporting.example.com (Caddy, automatic certificate)
#   ./install.sh --domain NAME --cert FILE --key FILE
#                                                 HTTPS with the certificate of your company (with its intermediate
#                                                 certificates) and its private key: never Let's Encrypt. Again on an
#                                                 installation: renews them (Caddy reloads them)
#   ./install.sh --ca-cert FILE                   certificate authority of your company (PEM), trusted by the outgoing
#                                                 connections of the tool (email server, HTTPS through a proxy that
#                                                 inspects the traffic); several: repeat. Again on an installation: adds it
#   ./install.sh --port 8080                      another HTTP port
#   ./install.sh --image IMAGE                    published image instead of a local build (IMAGE= in .env)
#   ./install.sh --yes                            if Docker is missing, install it without asking first
#   ./install.sh --offline ARCHIVE                without Internet access: the image comes from the archive of the
#                                                 offline package (probant-image-X.Y.Z.tar.gz), nothing is downloaded;
#                                                 HTTPS only with --cert and --key (Caddy image of the package)
#   ./install.sh --check                          only checks the server (check.sh) with the same options: changes nothing
#   ./install.sh --skip-check                     installs without the check of the server
#   ./install.sh --auto-update on|off             automatic updates (auto-update.sh): sets up, or removes, a timer of
#                [--auto-update-time HH:MM]       the server (systemd, otherwise cron) that runs auto-update.sh every
#                                                 night at about HH:MM (default 04:00, time of the server, random delay
#                                                 of up to 1 hour). For an installation with a published image only.
#                                                 A new installation made by get.sh gets "on", and the choice
#                                                 "automatic" in the tool (Settings > Hosting); on an installation, the
#                                                 choice of the tool does not change
#
# A new installation (no .env yet) starts with the check of the server (check.sh) and stops if something is missing.
# Then it creates the .env file, gets the image (from the archive with --offline, download if IMAGE= is set, otherwise
# build), starts the tool and waits until it responds. The tool then opens on the "Setup" wizard. Running the script
# again does not replace an existing .env. If Docker is missing, it offers to install it (Debian, Ubuntu; not with
# --offline). The certificates go into the folder certificates/ (ca/ for the authorities, https/ for the certificate
# and its key, in 0600), never into a backup of the tool. Guide: docs/installation.md, "Company network".
# Automatic updates: docs/installation.md, "Automatic updates".
set -eu
START="$(pwd)"
cd "$(dirname "$0")"

DOMAIN="" ; PORT="8000" ; IMAGE_OPTION="" ; YES=0 ; CHECK_ONLY=0 ; SKIP_CHECK=0 ; OFFLINE_ARCHIVE=""
CERT="" ; KEY="" ; CA_CERTS="" ; AUTO_UPDATE="" ; AUTO_TIME="04:00"
NL='
'
need_value() { [ $# -ge 2 ] || { echo "The option $1 needs a value (see ./install.sh --help)."; exit 2; }; }
# absolute FILE: a file given on the command line, from the folder where the command was run
absolute() { case "$1" in /*) printf '%s\n' "$1" ;; *) printf '%s\n' "$START/$1" ;; esac; }
while [ $# -gt 0 ]; do
  case "$1" in
    --domain|--domaine) DOMAIN="$2"; shift 2 ;;  # --domaine: former French name, still accepted
    --port) PORT="$2"; shift 2 ;;
    --image) IMAGE_OPTION="$2"; shift 2 ;;
    --yes) YES=1; shift ;;
    --offline) need_value "$@"; case "$2" in /*) OFFLINE_ARCHIVE="$2" ;; *) OFFLINE_ARCHIVE="$START/$2" ;; esac; shift 2 ;;
    --check) CHECK_ONLY=1; shift ;;
    --skip-check) SKIP_CHECK=1; shift ;;
    --cert) need_value "$@"; CERT=$(absolute "$2"); shift 2 ;;
    --key) need_value "$@"; KEY=$(absolute "$2"); shift 2 ;;
    --ca-cert) need_value "$@"; CA_CERTS="$CA_CERTS$(absolute "$2")$NL"; shift 2 ;;
    --auto-update)
      need_value "$@"
      case "$2" in on|off) AUTO_UPDATE="$2" ;; *) echo "--auto-update: on or off."; exit 2 ;; esac; shift 2 ;;
    --auto-update-time)
      need_value "$@"
      printf '%s\n' "$2" | grep -Eqx '([01][0-9]|2[0-3]):[0-5][0-9]' || { echo "--auto-update-time: write it as HH:MM (for example 04:00)."; exit 2; }
      AUTO_TIME="$2"; shift 2 ;;
    -h|--help) sed -n '2,35p' "$0"; exit 0 ;;
    *) echo "Unknown option: $1 (see ./install.sh --help)"; exit 2 ;;
  esac
done

# ---- Automatic updates: the timer of the server that runs auto-update.sh (never the container of the tool, which never
# reaches Docker nor the Internet). systemd if this script runs as root on a server with systemd, otherwise the cron of
# the system (root) or of the user. The PROBANT_TEST_ variables are reserved for the tests of this script: leave them
# unset.
IMAGE_NAME="${PROBANT_TEST_IMAGE:-ghcr.io/probant-reporting/probant}"
UNIT_DIR="${PROBANT_TEST_SYSTEMD_DIR:-/etc/systemd/system}"
SYSTEMD_RUN="${PROBANT_TEST_SYSTEMD_RUN:-/run/systemd/system}"
CRON_DIR="${PROBANT_TEST_CRON_DIR:-/etc/cron.d}"
UID_NOW="${PROBANT_TEST_UID:-$(id -u)}"
# name of the timer of this folder (several installations on one server: one timer each)
timer_name() { echo "probant-auto-update-$(pwd | cksum | cut -d' ' -f1)"; }
timer_method() {
  if [ "$UID_NOW" = 0 ] && [ -d "$SYSTEMD_RUN" ] && command -v systemctl >/dev/null 2>&1; then echo systemd
  elif [ "$UID_NOW" = 0 ] && [ -d "$CRON_DIR" ]; then echo cron-system
  elif command -v crontab >/dev/null 2>&1; then echo cron-user
  else return 1; fi
}
# published_image IMAGE: a version X.Y.Z of the published image (pinned digest or not)
published_image() {
  case "$1" in "$IMAGE_NAME":*) v="${1#"$IMAGE_NAME":}"; v="${v%%@*}"; printf '%s\n' "$v" | grep -Eqx '[0-9]+\.[0-9]+\.[0-9]+' ;; *) return 1 ;; esac
}
# check_auto_update IMAGE: automatic updates possible here (nothing changes); the reason otherwise
check_auto_update() {
  if [ ! -f auto-update.sh ]; then echo "auto-update.sh is missing next to install.sh: get the files of the version again."; return 1; fi
  if [ -d .git ]; then
    echo "Automatic updates are for an installation made with one command (published image). With Git, update with ./update.sh."; return 1
  fi
  if [ -n "$OFFLINE_ARCHIVE" ] || ! published_image "$1"; then
    echo "Automatic updates need a published version of the image (IMAGE=$IMAGE_NAME:X.Y.Z in .env) and Internet access."
    echo "Without Internet access, update with ./update.sh --offline."; return 1
  fi
  if ! pwd | grep -Eqx '/[A-Za-z0-9._/-]+'; then
    echo "The path of this folder has characters that a timer cannot run safely ($(pwd)): move the folder, or update with ./update.sh."; return 1
  fi
  if ! timer_method >/dev/null; then
    echo "No timer can be set up here: run this command as root (systemd or cron), or install cron."; return 1
  fi
}
remove_timer() {
  name=$(timer_name)
  if [ -f "$UNIT_DIR/$name.timer" ] || [ -f "$UNIT_DIR/$name.service" ]; then
    systemctl disable --now "$name.timer" >/dev/null 2>&1 || true
    rm -f "$UNIT_DIR/$name.timer" "$UNIT_DIR/$name.service"
    systemctl daemon-reload >/dev/null 2>&1 || true
  fi
  rm -f "$CRON_DIR/$name" 2>/dev/null || true
  if command -v crontab >/dev/null 2>&1 && crontab -l 2>/dev/null | grep -q "# $name\$"; then
    crontab -l 2>/dev/null | grep -v "# $name\$" | crontab -
  fi
}
auto_update_on() {
  name=$(timer_name); here=$(pwd); method=$(timer_method)
  remove_timer
  mkdir -p .auto-update
  case "$method" in
    systemd)
      cat > "$UNIT_DIR/$name.service" <<EOF
[Unit]
Description=Probant automatic update ($here)
Documentation=https://github.com/Probant-Reporting/probant/blob/main/docs/installation.md
After=docker.service network-online.target
Wants=network-online.target

[Service]
Type=oneshot
WorkingDirectory=$here
ExecStart=/bin/sh $here/auto-update.sh
TimeoutStartSec=2h
EOF
      cat > "$UNIT_DIR/$name.timer" <<EOF
[Unit]
Description=Probant automatic update, every night ($here)

[Timer]
OnCalendar=*-*-* $AUTO_TIME:00
RandomizedDelaySec=3600

[Install]
WantedBy=timers.target
EOF
      chmod 644 "$UNIT_DIR/$name.service" "$UNIT_DIR/$name.timer"
      systemctl daemon-reload && systemctl enable --now "$name.timer" >/dev/null
      echo "systemd $AUTO_TIME" > .auto-update/task
      echo "Automatic updates: systemd timer $name.timer, every night at about $AUTO_TIME (time of the server)." ;;
    cron-system|cron-user)
      # cron has no random delay: a random minute within the hour after HH:MM, chosen now
      total=$(( (${AUTO_TIME%:*} * 60 + ${AUTO_TIME#*:} + $(awk 'BEGIN { srand(); print int(rand() * 60) }')) % 1440 ))
      line="$((total % 60)) $((total / 60)) * * *"
      if [ "$method" = cron-system ]; then
        printf '%s\n' "# Probant automatic update ($here), set up by ./install.sh --auto-update on" \
          "SHELL=/bin/sh" "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin" \
          "$line root /bin/sh $here/auto-update.sh >/dev/null 2>&1" > "$CRON_DIR/$name"
        chmod 644 "$CRON_DIR/$name"
      else
        { crontab -l 2>/dev/null || true; echo "$line /bin/sh $here/auto-update.sh >/dev/null 2>&1 # $name"; } | crontab -
      fi
      echo "cron $AUTO_TIME" > .auto-update/task
      echo "Automatic updates: cron ($([ "$method" = cron-system ] && echo "$CRON_DIR/$name" || echo "crontab of $(id -un)")), every night at $((total / 60)):$(printf '%02d' $((total % 60)))." ;;
  esac
  sh ./auto-update.sh --record installed >/dev/null 2>&1 || true
  echo "Log of each run: $here/auto-update.log. To remove the timer: ./install.sh --auto-update off"
}
auto_update_off() {
  remove_timer
  mkdir -p .auto-update
  echo "none" > .auto-update/task
  if [ -f auto-update.sh ] && [ -f .env ]; then sh ./auto-update.sh --record task_removed >/dev/null 2>&1 || true; fi
  echo "Automatic updates: the timer of this folder is removed (nothing else changed)."
}
# existing installation, only --auto-update (and its time): only the timer changes
if [ -n "$AUTO_UPDATE" ] && [ -f .env ] && [ -z "$DOMAIN$IMAGE_OPTION$OFFLINE_ARCHIVE$CERT$KEY$CA_CERTS" ] && [ "$CHECK_ONLY" = 0 ]; then
  if [ "$AUTO_UPDATE" = off ]; then auto_update_off; exit 0; fi
  check_auto_update "$(grep "^IMAGE=" .env | tail -1 | cut -d= -f2- || true)" || { echo "Nothing was changed."; exit 1; }
  auto_update_on
  echo "The choice of the administrator (Settings > Hosting, \"Automatic updates\") did not change: automatic, notify only, or off."
  exit 0
fi
NEW_INSTALL=0
if [ ! -f .env ]; then NEW_INSTALL=1; fi
if [ "$AUTO_UPDATE" = on ] && [ "$CHECK_ONLY" = 0 ]; then
  image_after="$IMAGE_OPTION"
  if [ -z "$image_after" ] && [ -f .env ]; then image_after=$(grep "^IMAGE=" .env | tail -1 | cut -d= -f2- || true); fi
  check_auto_update "$image_after" || { echo "Nothing was changed. Add --auto-update off to install without automatic updates."; exit 1; }
fi

# ---- Certificates of the company: checked before anything changes
if { [ -n "$CERT" ] && [ -z "$KEY" ]; } || { [ -z "$CERT" ] && [ -n "$KEY" ]; }; then
  echo "--cert and --key go together: the certificate and its private key."; exit 2
fi
if [ -n "$CERT" ]; then
  if [ -f .env ]; then
    if ! grep -q '^DJANGO_HTTPS=1' .env || ! grep -q '^COMPOSE_PROFILES=.*https' .env; then
      echo "This installation has no HTTPS address with Caddy: --cert and --key are for an installation made with --domain"
      echo "(docs/installation.md, \"Company network\"). Nothing was changed."; exit 2
    fi
  elif [ -z "$DOMAIN" ]; then
    echo "--cert and --key need --domain: the name of the HTTPS address that the certificate covers."; exit 2
  fi
  for f in "$CERT" "$KEY"; do
    [ -f "$f" ] && [ -r "$f" ] || { echo "File not found or not readable: $f. Nothing was changed."; exit 1; }
  done
fi
old_ifs="$IFS"; IFS="$NL"
for f in $CA_CERTS; do
  [ -f "$f" ] && [ -r "$f" ] || { echo "File not found or not readable: $f. Nothing was changed."; exit 1; }
done
IFS="$old_ifs"

# ---- Offline package: archive of the image, files of the version, VERSION and SHA256SUMS in one folder (the same
# function in update.sh). Checks every file against SHA256SUMS before anything changes.
check_package() {
  dir=$(dirname "$1")
  if [ ! -f "$1" ]; then echo "Archive not found: $1. Nothing was changed."; return 1; fi
  if [ ! -f "$dir/SHA256SUMS" ] || ! awk -v f="$(basename "$1")" '{ n = $2; sub(/^[*]/, "", n) } n == f { found = 1 } END { exit !found }' "$dir/SHA256SUMS"; then
    echo "$(basename "$1") is not listed in $dir/SHA256SUMS: this is not the archive of an offline package. Nothing was changed."; return 1
  fi
  command -v sha256sum >/dev/null 2>&1 || { echo "sha256sum is missing (package coreutils): the package cannot be checked. Nothing was changed."; return 1; }
  if ! (cd "$dir" && sha256sum -c --quiet SHA256SUMS); then
    echo "The files of the package do not match SHA256SUMS (damaged or changed copy). Nothing was changed: copy the package again."; return 1
  fi
}
# load_image ARCHIVE: loads the image into Docker and gives its name (name:tag), from the output of "docker load"
load_image() {
  out=$(docker load -i "$1") || { echo "docker load failed for $1." >&2; return 1; }
  name=$(printf '%s\n' "$out" | sed -n 's/^Loaded image: //p')
  if [ "$(printf '%s\n' "$name" | grep -c .)" != 1 ]; then
    echo "The archive must hold exactly one named image (docker load gave: $out)." >&2; return 1
  fi
  printf '%s\n' "$name"
}
CADDY_ARCHIVE=""
if [ -n "$OFFLINE_ARCHIVE" ]; then
  if [ -n "$DOMAIN" ] && [ -z "$CERT" ]; then
    echo "--domain alone needs Internet access (automatic certificate). Without it, give the certificate of your company"
    echo "with --cert and --key, or install over HTTP and put the HTTPS proxy of your company in front"
    echo "(docs/installation.md, \"Install without Internet access\"). Nothing was changed."; exit 2
  fi
  if [ -n "$IMAGE_OPTION" ]; then echo "--offline and --image do not go together: the image comes from the archive."; exit 2; fi
  check_package "$OFFLINE_ARCHIVE" || exit 1
  if [ -n "$DOMAIN" ] || { [ -f .env ] && grep -q '^COMPOSE_PROFILES=.*https' .env; }; then
    CADDY_ARCHIVE="$(dirname "$OFFLINE_ARCHIVE")/caddy-image.tar.gz"
    if [ ! -f "$CADDY_ARCHIVE" ]; then
      echo "This offline package has no image of Caddy (HTTPS): use the package of a later version. Nothing was changed."; exit 1
    fi
  fi
fi

# ---- Check of the server (check.sh), with the options of this installation
run_check() {
  set -- "$@" --port "$PORT"
  if [ -n "$DOMAIN" ]; then set -- "$@" --domain "$DOMAIN"; fi
  image="$IMAGE_OPTION"
  if [ -z "$image" ] && [ -f .env ]; then image=$(grep "^IMAGE=" .env | tail -1 | cut -d= -f2- || true); fi
  if [ -n "$OFFLINE_ARCHIVE" ]; then set -- "$@" --offline; elif [ -n "$image" ]; then set -- "$@" --image "$image"; fi
  if [ -n "$CERT" ]; then set -- "$@" --cert "$CERT" --key "$KEY"; fi
  old_ifs="$IFS"; IFS="$NL"
  for f in $CA_CERTS; do set -- "$@" --ca-cert "$f"; done
  IFS="$old_ifs"
  sh ./check.sh "$@"
}
if [ "$CHECK_ONLY" = 1 ]; then
  [ -f check.sh ] || { echo "check.sh is missing next to install.sh: get the files of the version again."; exit 1; }
  status=0
  run_check || status=$?
  exit "$status"
fi
# new installation only (an existing .env: the tool already runs, and uses its port). PROBANT_TEST_SKIP_CHECK is
# reserved for the tests of the scripts: leave it unset.
if [ ! -f .env ] && [ "$SKIP_CHECK" = 0 ] && [ -z "${PROBANT_TEST_SKIP_CHECK:-}" ]; then
  [ -f check.sh ] || { echo "check.sh is missing next to install.sh: get the files of the version again, or add --skip-check."; exit 1; }
  if ! run_check --installing; then
    echo
    echo "Nothing was installed. Fix the points above, then run ./install.sh again."
    echo "To install anyway, add --skip-check (docs/installation.md, \"Check the server before you install\")."
    exit 1
  fi
  echo
fi
# existing installation, new certificates: only their check (the tool already runs on this server)
EXISTING=0
if [ -f .env ]; then EXISTING=1; fi
if [ "$EXISTING" = 1 ] && { [ -n "$CERT" ] || [ -n "$CA_CERTS" ]; } && [ "$SKIP_CHECK" = 0 ] && [ -z "${PROBANT_TEST_SKIP_CHECK:-}" ]; then
  [ -f check.sh ] || { echo "check.sh is missing next to install.sh: get the files of the version again, or add --skip-check."; exit 1; }
  domain_now=$(grep "^DOMAIN=" .env | tail -1 | cut -d= -f2- || true)
  if ! run_check --certificate-only --domain "${DOMAIN:-$domain_now}"; then
    echo
    echo "Nothing was changed. Fix the points above, then run the command again."; exit 1
  fi
  echo
fi

# Docker is missing: offers to install it with Docker's official procedure for Debian and Ubuntu
# (https://docs.docker.com/engine/install/debian/ and .../ubuntu/): Docker's apt repository, checked with Docker's key.
# Never without a "yes" (the question, or --yes); nothing on another system or without administrator rights.
install_docker() {
  echo "Docker is not installed."
  # system of the server (PROBANT_TEST_OS_RELEASE: reserved for the tests of this script, leave it unset)
  release="${PROBANT_TEST_OS_RELEASE:-/etc/os-release}"
  # shellcheck source=/dev/null
  os=$( (. "$release" && echo "${ID:-}") 2>/dev/null || true)
  # shellcheck source=/dev/null
  codename=$( (. "$release" && echo "${UBUNTU_CODENAME:-${VERSION_CODENAME:-}}") 2>/dev/null || true)
  if { [ "$os" != debian ] && [ "$os" != ubuntu ]; } || [ -z "$codename" ]; then
    echo "This script installs Docker on Debian and Ubuntu only. Install Docker Engine and its Compose plugin"
    echo "(https://docs.docker.com/engine/install/), then run ./install.sh again."; exit 1
  fi
  if [ "$(id -u)" = 0 ]; then
    SUDO=""
  elif command -v sudo >/dev/null 2>&1; then
    SUDO="sudo"  # asks for the password of your account
  else
    echo "Installing Docker needs administrator rights: run this script as root, or install Docker yourself"
    echo "(https://docs.docker.com/engine/install/), then run ./install.sh again."; exit 1
  fi
  if [ "$YES" != 1 ]; then
    # the question goes to the terminal, also when this script comes through a pipe ("curl … | sh")
    if ! (: </dev/tty) 2>/dev/null; then
      echo "No terminal to ask the question: run the command again with --yes to install Docker, or install it"
      echo "yourself (https://docs.docker.com/engine/install/)."; exit 1
    fi
    printf "Install Docker now, from Docker's apt repository (download.docker.com)? [y/N] "
    read -r answer </dev/tty || answer=""
    case "$answer" in
      y|Y|yes|Yes|YES) ;;
      *) echo "Docker not installed. Install it (https://docs.docker.com/engine/install/), then run ./install.sh again."; exit 1 ;;
    esac
  fi
  echo "Installing Docker (official procedure, $os $codename)…"
  keys=$(mktemp -d)
  $SUDO apt-get update
  $SUDO apt-get install -y ca-certificates curl
  curl -fsSL --proto '=https' "https://download.docker.com/linux/$os/gpg" -o "$keys/docker.asc"
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/$os $codename stable" > "$keys/docker.list"
  $SUDO install -m 0755 -d /etc/apt/keyrings
  $SUDO install -m 0644 "$keys/docker.asc" /etc/apt/keyrings/docker.asc
  $SUDO install -m 0644 "$keys/docker.list" /etc/apt/sources.list.d/docker.list
  rm -rf "$keys"
  $SUDO apt-get update
  $SUDO apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  echo "Docker installed."
}

if ! command -v docker >/dev/null 2>&1; then
  if [ -n "$OFFLINE_ARCHIVE" ]; then
    echo "Docker is not installed. Without Internet access, install Docker Engine and its Compose plugin from the package"
    echo "mirror of your company, then run ./install.sh again."; exit 1
  fi
  install_docker
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
if [ -n "$IMAGE_OPTION" ]; then set_value IMAGE "$IMAGE_OPTION"; fi

# Folder certificates/ of the installation (docker-compose.yml mounts it; made here, so that Docker does not make it
# owned by root): ca/ for the authorities (readable by the tool), https/ for the certificate and its key (Caddy only).
# A folder already there with other rights (made by Docker, owned by root, when an installation by Git was updated
# from a version before this folder) is kept as it is: only a certificate to put there needs to write in it.
make_folder() {  # make_folder FOLDER MODE
  if [ -d "$1" ]; then
    chmod "$2" "$1" 2>/dev/null || true  # owned by another user (root): kept as it is
  else
    (umask 077 && mkdir "$1" 2>/dev/null) && chmod "$2" "$1" || true
  fi
}
writable() {  # writable FOLDER: or one sentence that says what to do, and stop
  if [ ! -d "$1" ] || [ ! -w "$1" ]; then
    echo "The folder $1 cannot be written by this user (made by Docker as root during an update?): run this command again with sudo, or first run: sudo chown -R $(id -u):$(id -g) certificates"
    exit 1
  fi
}
make_folder certificates 755
make_folder certificates/ca 755
make_folder certificates/https 700
if [ -n "$CA_CERTS" ]; then writable certificates/ca; fi
if [ -n "$CERT" ]; then writable certificates/https; fi
old_ifs="$IFS"; IFS="$NL"
for f in $CA_CERTS; do
  name=$(basename "$f")
  case "$name" in *.pem|*.crt|*.cer) ;; *) name="$name.pem" ;; esac
  cp "$f" "certificates/ca/$name.new" && chmod 644 "certificates/ca/$name.new" && mv -f "certificates/ca/$name.new" "certificates/ca/$name"
  echo "Certificate authority added: certificates/ca/$name"
done
IFS="$old_ifs"
if [ -n "$CERT" ]; then
  cp "$CERT" certificates/https/certificate.pem.new && chmod 644 certificates/https/certificate.pem.new
  # the private key: readable by its owner only, never shown, never in a backup of the tool
  (umask 077 && cp "$KEY" certificates/https/key.pem.new) && chmod 600 certificates/https/key.pem.new
  mv -f certificates/https/certificate.pem.new certificates/https/certificate.pem
  mv -f certificates/https/key.pem.new certificates/https/key.pem
  set_value HTTPS_CERTIFICATE files
  echo "HTTPS certificate of your company in place: certificates/https/ (Caddy never asks Let's Encrypt)."
fi
# commit of the code, shown with the version: only from a Git folder. Without Git (folder made by get.sh), the published
# image carries its own commit, and an empty VERSION_COMMIT= line in .env would hide it.
COMMIT=$(git rev-parse HEAD 2>/dev/null || true)
if [ -n "$COMMIT" ]; then set_value VERSION_COMMIT "$COMMIT"; fi

if [ -n "$OFFLINE_ARCHIVE" ]; then
  echo "Loading the image from $(basename "$OFFLINE_ARCHIVE") (nothing is downloaded)…"
  LOADED=$(load_image "$OFFLINE_ARCHIVE")
  set_value IMAGE "$LOADED"
  if [ -n "$CADDY_ARCHIVE" ]; then
    echo "Loading the image of Caddy (HTTPS) from $(basename "$CADDY_ARCHIVE")…"
    load_image "$CADDY_ARCHIVE" >/dev/null
  fi
  echo "Starting $LOADED…"
  docker compose up -d --pull never
elif [ "$EXISTING" = 1 ] && { [ -n "$CERT" ] || [ -n "$CA_CERTS" ]; } && [ -z "$IMAGE_OPTION" ]; then
  # new certificates on an installation: the same version, nothing downloaded (also without Internet access); a
  # service whose settings changed (first certificate of the company) is created again
  docker compose up -d --pull never
else
  if grep -q "^IMAGE=..*" .env; then
    echo "Downloading the image and starting…"
    docker compose pull web
  else
    echo "Building the image and starting (a few minutes the first time)…"
    docker compose build web
  fi
  docker compose up -d
fi

# existing installation: the authorities are read at the start of the tool, the certificate by Caddy
if [ "$EXISTING" = 1 ] && [ -n "$CA_CERTS" ]; then
  echo "Restarting the tool (new certificate authorities)…"
  docker compose restart web
fi
if [ "$EXISTING" = 1 ] && [ -n "$CERT" ]; then
  echo "Reloading the certificate in Caddy…"
  docker compose exec -T caddy caddy reload --config /etc/caddy/Caddyfile --adapter caddyfile --force \
    || docker compose restart caddy
fi

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
echo "Folder of the installation: $(pwd) (run the commands below there)"
if [ -n "$OFFLINE_ARCHIVE" ]; then UPDATE="./update.sh --offline <archive of the new version>"; else UPDATE="./update.sh"; fi
# automatic updates: the timer of the server; a new installation made with one command also gets the choice
# "automatic" in the tool (an installation that already exists keeps its choice)
if [ "$AUTO_UPDATE" = on ]; then
  echo
  auto_update_on
  if [ "$NEW_INSTALL" = 1 ]; then
    docker compose exec -T web python manage.py auto_update --set-choice automatic --if-unset \
      || echo "The choice \"automatic\" could not be saved in the tool: set it in Settings > Hosting."
  fi
  UPDATE="$UPDATE (automatic every night: Settings > Hosting)"
elif [ "$AUTO_UPDATE" = off ] && [ "$NEW_INSTALL" = 0 ]; then
  auto_update_off >/dev/null
fi
echo "Log: docker compose logs -f web   ·   Update: $UPDATE   ·   Guide: docs/installation.md"
if grep -q '^HTTPS_CERTIFICATE=..*' .env; then
  echo "Certificate of your company: to renew it, ./install.sh --cert <new certificate> --key <new key>"
fi
