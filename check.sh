#!/bin/sh
# Checks a Linux server before the installation of Probant. It changes nothing on the machine: it only reads.
#
#   sh check.sh                                  installation over HTTP on port 8000, image built on the server
#   sh check.sh --image IMAGE                    installation with a published image (downloaded from its registry)
#   sh check.sh --port 8080                      another HTTP port
#   sh check.sh --domain reporting.example.com   HTTPS: ports 80 and 443, and the domain name must point to the server
#   sh check.sh --offline                        installation without Internet access: no check of the network
#   sh check.sh --domain NAME --cert FILE --key FILE
#                                                HTTPS with the certificate of your company: the key matches it, it
#                                                covers NAME, it has not expired, its chain is complete
#   sh check.sh --ca-cert FILE                   certificate authority of your company (a proxy that inspects the
#                                                traffic): the checks of the network trust it too (several: repeat)
#   sh check.sh --certificate-only ...           only the checks of the certificate and the authorities
#
# The same check: ./install.sh --check, or "curl … get.sh | sh -s -- --check" before an installation in one command.
# ./install.sh runs it before a new installation and stops if something is missing (--skip-check to go on anyway).
# One line per check: "OK", "To fix" (with what to do), "Warning" (does not stop the installation), or "Not checked"
# (with why). Then one conclusion: "Ready", or "Here is what is missing". Exit code: 0 ready, 1 something is missing,
# 2 wrong option. Minimums: section 1 of docs/installation.md. Company network: "Company network" in the same guide.
set -u

PORT="8000" ; DOMAIN="" ; IMAGE="" ; OFFLINE=0 ; INSTALLING=0 ; CERT="" ; KEY="" ; CA_CERTS="" ; ONLY_CERTIFICATE=0
# authorities: one file name per line (a name with a line break is not supported)
NL='
'
need_value() { [ $# -ge 2 ] || { echo "The option $1 needs a value (see sh check.sh --help)."; exit 2; }; }
while [ $# -gt 0 ]; do
  case "$1" in
    --port) need_value "$@"; PORT="$2"; shift 2 ;;
    --domain|--domaine) need_value "$@"; DOMAIN="$2"; shift 2 ;;
    --image) need_value "$@"; IMAGE="$2"; shift 2 ;;
    --offline) OFFLINE=1; shift ;;
    --installing) INSTALLING=1; shift ;;  # given by install.sh: it offers to install Docker if Docker is missing
    --cert) need_value "$@"; CERT="$2"; shift 2 ;;
    --key) need_value "$@"; KEY="$2"; shift 2 ;;
    --ca-cert) need_value "$@"; CA_CERTS="$CA_CERTS$2$NL"; shift 2 ;;
    --certificate-only) ONLY_CERTIFICATE=1; shift ;;
    -h|--help) sed -n '2,20p' "$0" 2>/dev/null || echo "Options: --image IMAGE --port PORT --domain NAME --offline --cert FILE --key FILE --ca-cert FILE"; exit 0 ;;
    *) echo "Unknown option: $1 (see sh check.sh --help)"; exit 2 ;;
  esac
done
printf '%s\n' "$PORT" | grep -Eqx '[0-9]{1,5}' || { echo "Port \"$PORT\" not valid: write a number, for example 8080."; exit 2; }
if { [ -n "$CERT" ] && [ -z "$KEY" ]; } || { [ -z "$CERT" ] && [ -n "$KEY" ]; }; then
  echo "--cert and --key go together: the certificate and its private key."; exit 2
fi
# authorities already given to this installation (folder certificates/ca next to the files of the tool), if none given
if [ -z "$CA_CERTS" ] && [ -d certificates/ca ]; then
  for f in certificates/ca/*.pem certificates/ca/*.crt certificates/ca/*.cer; do
    [ -f "$f" ] && CA_CERTS="$CA_CERTS$f$NL"
  done
fi

# Minimums of docs/installation.md, section 1
MIN_DOCKER="24.0.0" ; MIN_COMPOSE="2.24.0" ; MIN_MEMORY_MB=900 ; MIN_DISK_KB=5000000
# Earliest plausible date of the clock (1 January 2026, UTC)
MIN_CLOCK=1767225600
# Repository of the files of a version. PROBANT_TEST_SOURCE is reserved for the tests of the scripts: leave it unset.
SOURCE="${PROBANT_TEST_SOURCE:-https://github.com/Probant-Reporting/probant}"
source_host=$(printf '%s' "$SOURCE" | sed -E 's|^[a-z]+://||; s|/.*||')

MISSING="" ; NOT_CHECKED=0 ; WARNINGS=0
ok() { printf '  %-12s %s\n' "OK" "$1"; }
fix() { printf '  %-12s %s\n' "To fix" "$1"; MISSING="$MISSING
  - $1"; }
not_checked() { printf '  %-12s %s\n' "Not checked" "$1"; NOT_CHECKED=$((NOT_CHECKED + 1)); }
warn() { printf '  %-12s %s\n' "Warning" "$1"; WARNINGS=$((WARNINGS + 1)); }
has() { command -v "$1" >/dev/null 2>&1; }
# version_at_least A B: version A (X.Y.Z, with or without "v" and a suffix) is B or later
version_at_least() {
  a=$(printf '%s\n' "$1" | sed 's/^v//' | grep -Eo '^[0-9]+(\.[0-9]+){0,2}') || return 1
  case "$a" in *.*.*) ;; *.*) a="$a.0" ;; *) a="$a.0.0" ;; esac
  [ "$(printf '%s\n%s\n' "$a" "$2" | sort -t. -k1,1n -k2,2n -k3,3n | head -1)" = "$2" ]
}

# ---- Certificate authorities and HTTPS certificate of the company (docs/installation.md, "Company network")
TMP_CHECK=""
trap '[ -z "$TMP_CHECK" ] || rm -rf "$TMP_CHECK"' EXIT
# system_bundle: the file of the authorities of the system (Debian and Ubuntu, RHEL, SUSE, Alpine)
system_bundle() {
  for f in /etc/ssl/certs/ca-certificates.crt /etc/pki/tls/certs/ca-bundle.crt /etc/ssl/ca-bundle.pem /etc/ssl/cert.pem; do
    if [ -f "$f" ]; then echo "$f"; return 0; fi
  done
  return 1
}
# authorities of the system and of the company in one temporary file (removed at the end), for curl and openssl verify
CA_BUNDLE=""
check_authorities() {
  [ -n "$CA_CERTS" ] || return 0
  good="" ; old_ifs="$IFS" ; IFS="$NL"
  for f in $CA_CERTS; do
    IFS="$old_ifs"
    if [ ! -r "$f" ]; then fix "Certificate authority $f: cannot be read."; continue; fi
    if ! grep -q -- "-----BEGIN CERTIFICATE-----" "$f" 2>/dev/null; then
      fix "Certificate authority $f: no certificate in PEM format (-----BEGIN CERTIFICATE-----). Ask the network team for the authority in PEM format."
      continue
    fi
    if has openssl; then
      if ! openssl x509 -in "$f" -noout -text 2>/dev/null | grep -q "CA:TRUE"; then
        fix "Certificate authority $f: this is not the certificate of an authority (a server certificate?). Ask the network team for the certificate of the authority."
        continue
      fi
      subject=$(openssl x509 -in "$f" -noout -subject -nameopt RFC2253 2>/dev/null | sed 's/^subject= *//')
      end=$(openssl x509 -in "$f" -noout -enddate 2>/dev/null | cut -d= -f2)
      if ! openssl x509 -in "$f" -noout -checkend 0 >/dev/null 2>&1; then
        fix "Certificate authority $subject ($f): expired on $end. Ask the network team for the new one."
        continue
      elif ! openssl x509 -in "$f" -noout -checkend 2592000 >/dev/null 2>&1; then
        warn "Certificate authority $subject ($f): expires on $end, in less than 30 days. Ask the network team for the new one."
      else
        ok "Certificate authority $subject ($f): valid until $end"
      fi
    else
      ok "Certificate authority $f: PEM file (not checked further: the command openssl is missing)"
    fi
    good="$good$f$NL"
  done
  IFS="$old_ifs"
  [ -n "$good" ] || return 0
  if base=$(system_bundle); then
    TMP_CHECK=$(mktemp -d)
    CA_BUNDLE="$TMP_CHECK/ca-bundle.pem"
    cat "$base" > "$CA_BUNDLE"
    IFS="$NL"
    for f in $good; do cat "$f" >> "$CA_BUNDLE"; done
    IFS="$old_ifs"
  else
    not_checked "Authorities of the system: no file found (/etc/ssl/certs/ca-certificates.crt…): the checks of the network do not use the authority of the company."
  fi
}
# names covered by the certificate (Subject Alternative Name), for the messages
certificate_names() {
  openssl x509 -in "$CERT" -noout -text 2>/dev/null | awk '/Subject Alternative Name/ { getline; gsub(/^[ \t]+/, ""); print; exit }'
}
check_certificate() {
  [ -n "$CERT" ] || return 0
  if [ ! -r "$CERT" ]; then fix "HTTPS certificate $CERT: cannot be read."; return 0; fi
  if [ ! -r "$KEY" ]; then fix "Private key $KEY: cannot be read."; return 0; fi
  if ! has openssl; then
    not_checked "HTTPS certificate: the command openssl is missing (package openssl): the key, the name, the date and the chain are not checked."
    return 0
  fi
  if ! openssl x509 -in "$CERT" -noout 2>/dev/null; then
    fix "HTTPS certificate $CERT: not a certificate in PEM format (-----BEGIN CERTIFICATE-----)."; return 0
  fi
  if ! openssl pkey -in "$KEY" -passin pass: -noout 2>/dev/null; then
    fix "Private key $KEY: not a private key in PEM format, or protected by a password. Give the key without a password (Caddy reads it at each start)."
    return 0
  fi
  # the key matches the certificate: same public key (RSA or EC). The key itself is never shown.
  from_cert=$(openssl x509 -in "$CERT" -noout -pubkey 2>/dev/null | openssl pkey -pubin -outform DER 2>/dev/null | openssl dgst -sha256 -r)
  from_key=$(openssl pkey -in "$KEY" -passin pass: -pubout -outform DER 2>/dev/null | openssl dgst -sha256 -r)
  if [ -n "$from_key" ] && [ "$from_cert" = "$from_key" ]; then
    ok "Private key: matches the certificate"
  else
    fix "Private key $KEY: does not match the certificate $CERT. Give the key made with this certificate."
  fi
  end=$(openssl x509 -in "$CERT" -noout -enddate 2>/dev/null | cut -d= -f2)
  expired=0
  if ! openssl x509 -in "$CERT" -noout -checkend 0 >/dev/null 2>&1; then
    fix "HTTPS certificate: expired on $end. Ask the network team for a new certificate."; expired=1
  elif ! openssl x509 -in "$CERT" -noout -checkend 2592000 >/dev/null 2>&1; then
    warn "HTTPS certificate: expires on $end, in less than 30 days. Ask for the next one now (renewal: docs/installation.md, \"Company network\")."
  else
    ok "HTTPS certificate: valid until $end"
  fi
  if [ -z "$DOMAIN" ]; then
    not_checked "HTTPS certificate: no domain name given (--domain): the name is not checked."
  else
    for name in $(printf '%s' "$DOMAIN" | tr ',' ' '); do
      if openssl x509 -in "$CERT" -noout -checkhost "$name" 2>/dev/null | grep -q " does match"; then
        ok "HTTPS certificate: covers $name"
      else
        fix "HTTPS certificate: does not cover $name (names in the certificate: $(certificate_names)). Ask for a certificate for $name."
      fi
    done
  fi
  [ "$expired" = 0 ] || return 0
  # complete chain: the certificate of the server, then the intermediate certificates, up to an authority of the system
  # or of the company (--ca-cert). A warning only: the tool works, but browsers can refuse an incomplete chain.
  roots="$CA_BUNDLE"
  if [ -z "$roots" ]; then roots=$(system_bundle) || roots=""; fi
  count=$(grep -c -- "-----BEGIN CERTIFICATE-----" "$CERT")
  if [ -z "$roots" ]; then
    not_checked "Chain of the certificate: no file of authorities on this system."
  elif out=$(openssl verify -CAfile "$roots" -untrusted "$CERT" "$CERT" 2>&1); then
    ok "Chain of the certificate: complete ($count certificate(s) in the file, up to a known authority)"
  else
    reason=$(printf '%s\n' "$out" | grep -i "error" | head -1 | sed 's/.*lookup: *//')
    warn "Chain of the certificate: not complete up to a known authority (${reason:-unknown error}). $CERT must hold the certificate of the server, then the intermediate certificates; give the authority of your company with --ca-cert. Browsers that cannot complete the chain show an error."
  fi
}
conclude() {
  echo
  if [ -z "$MISSING" ]; then
    notes=""
    if [ "$WARNINGS" -gt 0 ]; then notes=" $WARNINGS warning(s): read them above."; fi
    if [ "$NOT_CHECKED" -gt 0 ]; then notes="$notes $NOT_CHECKED point(s) not checked: read them above."; fi
    echo "Ready.$notes"
    exit 0
  fi
  echo "Here is what is missing:$MISSING"
  exit 1
}

if [ "$ONLY_CERTIFICATE" = 1 ]; then
  echo "Check of the certificates of the installation (nothing is changed)"
  echo
  check_authorities
  check_certificate
  conclude
fi

echo "Check of the server before the installation of Probant (nothing is changed)"
echo
check_authorities

# ---- System and architecture
system=$(uname -s 2>/dev/null || echo unknown)
if [ "$system" = Linux ]; then
  # shellcheck source=/dev/null
  name=$( (. "${PROBANT_TEST_OS_RELEASE:-/etc/os-release}" && echo "${PRETTY_NAME:-}") 2>/dev/null || true)
  ok "System: Linux${name:+ ($name)}"
else
  fix "System: $system. The installer runs on Linux only: use a Linux server (docs/installation.md, section 1)."
fi
arch=$(uname -m 2>/dev/null || echo unknown)
case "$arch" in
  x86_64|amd64) ok "Architecture: $arch (64-bit)" ;;
  aarch64|arm64)
    if [ -n "$IMAGE" ] || [ "$OFFLINE" = 1 ]; then
      fix "Architecture: $arch. The published image is for x86_64 only: install with Git, the server then builds the image (docs/installation.md, section 2)."
    else
      ok "Architecture: $arch (64-bit, the server builds the image)"
    fi ;;
  *) fix "Architecture: $arch. The tool needs a 64-bit server (x86_64)." ;;
esac

# ---- Docker, Compose, service
DOCKER_OK=0
if ! has docker; then
  if [ "$INSTALLING" = 1 ] && [ "$OFFLINE" = 0 ]; then
    not_checked "Docker: not installed yet. The installer offers to install it next (Debian and Ubuntu)."
  elif [ "$OFFLINE" = 1 ]; then
    fix "Docker: not installed. Without Internet access, install Docker Engine and its Compose plugin from the package mirror of your company first."
  else
    fix "Docker: not installed. Run ./install.sh: it offers to install Docker on Debian and Ubuntu (or see https://docs.docker.com/engine/install/)."
  fi
else
  client=$(docker version --format '{{.Client.Version}}' 2>/dev/null || true)
  info_error=$(docker info --format '{{.ServerVersion}}' 2>&1 >/dev/null) && info_status=0 || info_status=1
  server=""
  if [ "$info_status" = 0 ]; then server=$(docker info --format '{{.ServerVersion}}' 2>/dev/null || true); fi
  docker_version="${server:-$client}"
  if [ -z "$docker_version" ]; then
    not_checked "Docker: version unknown (docker version gives none)."
  elif version_at_least "$docker_version" "$MIN_DOCKER"; then
    ok "Docker: version $docker_version"
  else
    fix "Docker: version $docker_version. Version 24 or later is needed: update Docker (https://docs.docker.com/engine/install/)."
  fi
  compose=$(docker compose version --short 2>/dev/null || true)
  if [ -z "$compose" ]; then
    fix "Docker Compose: missing. Install the package docker-compose-plugin (Compose v2.24 or later)."
  elif version_at_least "$compose" "$MIN_COMPOSE"; then
    ok "Docker Compose: version $compose"
  else
    fix "Docker Compose: version $compose. Version 2.24 or later is needed: update the package docker-compose-plugin."
  fi
  if [ "$info_status" = 0 ]; then
    ok "Docker service: responds to this account"
    DOCKER_OK=1
  else
    case "$info_error" in
      *ermission*) fix "Docker service: this account cannot use Docker. Run the command with sudo, or add the account to the docker group." ;;
      *) fix "Docker service: does not respond. Start it: sudo systemctl start docker." ;;
    esac
  fi
fi

# ---- Memory, processors, disk
if has free; then
  memory=$(free -m 2>/dev/null | awk '/^Mem:/ { print $2; exit }')
  if [ -z "$memory" ]; then
    not_checked "Memory: unknown (free gives no total)."
  elif [ "$memory" -ge "$MIN_MEMORY_MB" ]; then
    ok "Memory: $memory MB"
  else
    fix "Memory: $memory MB. The tool needs at least 1 GB: give the server more memory."
  fi
else
  not_checked "Memory: the command free is missing."
fi
cpus=$(nproc 2>/dev/null || true)
if [ -z "$cpus" ]; then
  not_checked "Processors: the command nproc is missing."
elif [ "$cpus" -ge 1 ]; then
  ok "Processors: $cpus"
else
  fix "Processors: $cpus. The tool needs at least 1 processor."
fi
# free space where Docker keeps the images and the data volume
docker_dir=""
if [ "$DOCKER_OK" = 1 ]; then docker_dir=$(docker info --format '{{.DockerRootDir}}' 2>/dev/null || true); fi
docker_dir="${docker_dir:-/var/lib/docker}"
disk_dir="$docker_dir"
while [ ! -d "$disk_dir" ] && [ "$disk_dir" != / ]; do disk_dir=$(dirname "$disk_dir"); done
free_kb=$(df -Pk "$disk_dir" 2>/dev/null | awk 'NR == 2 { print $4 }')
if [ -z "$free_kb" ]; then
  not_checked "Disk: free space of $disk_dir unknown (df gives none)."
elif [ "$free_kb" -ge "$MIN_DISK_KB" ]; then
  ok "Disk: $((free_kb / 1000000)) GB free in $disk_dir"
else
  fix "Disk: $((free_kb / 1000)) MB free in $disk_dir. The tool needs at least 5 GB free: free some space or enlarge the disk."
fi

# ---- Ports: the HTTP port, and 80 and 443 with a domain name (Caddy). A port is free if no program listens on it.
# port_in_use PORT: 0 used, 1 free, 2 unknown
port_in_use() {
  if has ss; then
    ss -Hltn 2>/dev/null | awk -v p=":$1" '{ n = length($4) - length(p); if (n >= 0 && substr($4, n + 1) == p) f = 1 } END { exit !f }' && return 0
    return 1
  fi
  if [ -r /proc/net/tcp ]; then
    hex=$(printf ':%04X' "$1")
    cat /proc/net/tcp /proc/net/tcp6 2>/dev/null | awk -v p="$hex" '$4 == "0A" && substr($2, length($2) - 4) == p { f = 1 } END { exit !f }' && return 0
    return 1
  fi
  return 2
}
ports="$PORT"
if [ -n "$DOMAIN" ]; then ports="80 443 $PORT"; fi
for p in $ports; do
  port_in_use "$p"
  case $? in
    0)
      if [ "$p" = "$PORT" ]; then
        fix "Port $p: used by another program. Stop that program, or choose another port with --port."
      else
        fix "Port $p: used by another program (another web server?). HTTPS needs ports 80 and 443: stop that program."
      fi ;;
    1) ok "Port $p: free" ;;
    *) not_checked "Port $p: the command ss is missing." ;;
  esac
done

# ---- Domain name: does it point to this server? Behind a router (NAT), the server does not know its public address.
# private ADDRESS: 0 if the address is private, loopback or link-local
private() {
  case "$1" in
    10.*|127.*|192.168.*|169.254.*|172.1[6-9].*|172.2[0-9].*|172.3[01].*) return 0 ;;
    100.6[4-9].*|100.[7-9][0-9].*|100.1[01][0-9].*|100.12[0-7].*) return 0 ;;
    ::1|[fF][cCdD]*|[fF][eE]80:*) return 0 ;;
  esac
  return 1
}
if [ -n "$DOMAIN" ]; then
  # with the certificate of the company, no automatic certificate: the DNS is needed only by the people who open the
  # tool (often a DNS of the company that this server may not use), so a wrong answer is a warning, also without Internet
  dns_fix=fix
  if [ -n "$CERT" ]; then dns_fix=warn; fi
  if [ "$OFFLINE" = 1 ] && [ -z "$CERT" ]; then
    not_checked "Domain name $DOMAIN: without Internet access, there is no automatic certificate (see docs/installation.md, \"Install without Internet access\")."
  elif ! has getent; then
    not_checked "Domain name $DOMAIN: the command getent is missing."
  else
    resolved=$(getent ahosts "$DOMAIN" 2>/dev/null | awk '{ print $1 }' | sort -u | tr '\n' ' ' | sed 's/ $//')
    mine=$(hostname -I 2>/dev/null || true)
    if [ -z "$mine" ] && has ip; then mine=$(ip -o addr show 2>/dev/null | awk '{ sub(/\/.*/, "", $4); print $4 }' | tr '\n' ' '); fi
    match="" ; public_mine=0 ; public_resolved=0
    for a in $mine; do private "$a" || public_mine=1; done
    for r in $resolved; do
      private "$r" || public_resolved=1
      for a in $mine; do [ "$r" = "$a" ] && match="$r"; done
    done
    if [ -z "$resolved" ]; then
      $dns_fix "Domain name $DOMAIN: not found in the DNS. Create a DNS record (A, or AAAA) that points to the address of this server."
    elif [ -n "$match" ]; then
      ok "Domain name $DOMAIN: points to this server ($match)"
    elif [ -z "$mine" ]; then
      not_checked "Domain name $DOMAIN: points to $resolved, and the addresses of this server are unknown."
    elif [ "$public_mine" = 0 ] && [ "$public_resolved" = 1 ]; then
      not_checked "Domain name $DOMAIN: points to $resolved. This server has only private addresses (behind a router): check that $resolved is the public address of its network, with ports 80 and 443 sent to this server."
    else
      $dns_fix "Domain name $DOMAIN: points to $resolved, but this server has $mine. Change the DNS record to the address of this server."
    fi
  fi
fi
check_certificate

# ---- Network: registry of the image, GitHub (files of the version), through the proxy if HTTPS_PROXY is set
proxy="${HTTPS_PROXY:-${https_proxy:-}}"
proxy_shown=$(printf '%s' "$proxy" | sed 's|//[^/@]*@|//|')  # never the password of a proxy
# answers [OPTION] URL: the server at this address answers (any HTTP status; a proxy that refuses the address does not count)
# curl_ca: curl, with the authorities of the system and of the company when one is given (a proxy that inspects the traffic)
curl_ca() { if [ -n "$CA_BUNDLE" ]; then curl --cacert "$CA_BUNDLE" "$@"; else curl "$@"; fi; }
answers() { curl_ca -sS -I -o /dev/null --connect-timeout 10 --max-time 20 "$@" >/dev/null 2>&1; }
# reach NAME URL WHAT: one line for an address that the installation or the updates need
# uses_proxy HOST: curl goes through the proxy for this host (HTTPS_PROXY set, and the host is not in NO_PROXY)
uses_proxy() {
  [ -n "$proxy" ] || return 1
  for n in $(printf '%s' "${NO_PROXY:-${no_proxy:-}}" | tr ',' ' '); do
    n="${n#.}"
    case "${1%%:*}" in "$n"|*".$n") return 1 ;; esac
    [ "$n" = "*" ] && return 1
  done
  return 0
}
reach() {
  if answers "$2"; then
    if uses_proxy "$1"; then ok "$1 ($3): reachable through the proxy $proxy_shown"; else ok "$1 ($3): reachable"; fi
  elif uses_proxy "$1"; then
    fix "$1 ($3): cannot be reached through the proxy $proxy_shown. Ask the network team to allow $1 on the proxy."
  else
    fix "$1 ($3): cannot be reached over HTTPS (TCP 443). Open it in the firewall, or set HTTPS_PROXY if the network uses a proxy."
  fi
}
if [ "$OFFLINE" = 1 ]; then
  not_checked "Network: installation without Internet access (--offline): the registry and GitHub are not needed."
elif ! has curl; then
  fix "curl: missing. Install it (sudo apt-get install -y curl), then run the check again."
else
  if [ -n "$IMAGE" ]; then
    registry="${IMAGE%%/*}"
    case "$IMAGE" in */*) case "$registry" in *.*|*:*|localhost) ;; *) registry=docker.io ;; esac ;; *) registry=docker.io ;; esac
    [ "$registry" = docker.io ] && registry="registry-1.docker.io"
    # a registry on the machine itself answers over HTTP, as Docker allows it
    case "$registry" in 127.*|localhost|localhost:*) scheme=http ;; *) scheme=https ;; esac
    reach "$registry" "$scheme://$registry/v2/" "image"
    if [ "$registry" = ghcr.io ]; then reach pkg-containers.githubusercontent.com https://pkg-containers.githubusercontent.com/ "image"; fi
  else
    reach registry-1.docker.io https://registry-1.docker.io/v2/ "base image of the build"
    reach pypi.org https://pypi.org/simple/ "Python packages of the build"
    reach files.pythonhosted.org https://files.pythonhosted.org/ "Python packages of the build"
  fi
  reach "$source_host" "$SOURCE" "files of the version"
  if [ "$SOURCE" = "https://github.com/Probant-Reporting/probant" ]; then
    reach raw.githubusercontent.com https://raw.githubusercontent.com/ "files of the version"
  fi
  # Docker downloads the image itself: with a proxy, the Docker service needs it too, unless the registry answers
  # without a proxy
  if [ -n "$proxy" ] && [ -n "$IMAGE" ] && [ "$DOCKER_OK" = 1 ] && [ -z "$(docker info --format '{{.HTTPSProxy}}' 2>/dev/null || true)" ]; then
    if answers --noproxy '*' "$scheme://$registry/v2/"; then
      ok "Proxy of Docker: none needed ($registry answers without the proxy)"
    else
      fix "Proxy of Docker: Docker uses no proxy, and $registry answers only through $proxy_shown. Set the proxy of the Docker service (https://docs.docker.com/engine/daemon/proxy/)."
    fi
  fi
fi

# Docker downloads images itself, outside the tool: behind a proxy that inspects the traffic, the Docker service must
# trust the authority of the company too (not readable from here)
if [ -n "$CA_CERTS" ] && [ "$OFFLINE" = 0 ]; then
  not_checked "Docker and the authority of your company: if a proxy inspects the traffic, Docker must trust the authority too to download images. Add it to the authorities of the system (Debian and Ubuntu: /usr/local/share/ca-certificates, then update-ca-certificates), restart Docker (https://docs.docker.com/engine/network/ca-certs/)."
fi

# ---- Clock: compared with the time given by GitHub (certificates and signatures need the right time)
now=$(date -u +%s 2>/dev/null || echo 0)
shown=$(date -u -d "@$now" '+%Y-%m-%d %H:%M UTC' 2>/dev/null || date -u '+%Y-%m-%d %H:%M UTC' 2>/dev/null || echo unknown)
reference=""
if [ "$OFFLINE" = 0 ] && has curl; then
  # last Date header: the one of the server, after the answer of a proxy
  stamp=$(curl_ca -sS -I --connect-timeout 10 --max-time 20 "$SOURCE" 2>/dev/null | tr -d '\r' \
    | awk 'tolower($1) == "date:" { sub(/^[^:]*:[ ]*/, ""); d = $0 } END { print d }')
  if [ -n "$stamp" ]; then reference=$(date -u -d "$stamp" +%s 2>/dev/null || true); fi
fi
if [ "$now" -lt "$MIN_CLOCK" ]; then
  fix "Clock: $shown. The date is wrong: set the date and time, with time synchronisation (sudo timedatectl set-ntp true)."
elif [ -n "$reference" ]; then
  gap=$((now - reference)); [ "$gap" -lt 0 ] && gap=$((-gap))
  if [ "$gap" -le 300 ]; then
    ok "Clock: $shown (right, compared with $source_host)"
  else
    fix "Clock: $shown, $((gap / 60)) minutes away from the time of $source_host. Turn on time synchronisation (sudo timedatectl set-ntp true)."
  fi
elif [ "$OFFLINE" = 1 ]; then
  ok "Clock: $shown (plausible; without Internet access, not compared with a reference)"
else
  not_checked "Clock: $shown. No reference time ($source_host gives none)."
fi

conclude
