#!/usr/bin/env bash
# Signs in to a running Probant with curl, like a browser, then opens the home page and checks that it is the page of
# a signed-in person (sign-out link) and, if given, that its footer shows the expected version.
#
#   bash docker/check_sign_in.sh http://127.0.0.1:8000 admin PASSWORD [VERSION]
#
# Used by the Docker job of .github/workflows/tests.yml. HTTP only (over HTTPS, Django also checks the Referer).
set -euo pipefail
[ $# -ge 3 ] || { echo "Usage: $0 URL LOGIN PASSWORD [VERSION]"; exit 2; }
URL="${1%/}"; LOGIN="$2"; PASSWORD="$3"; VERSION="${4:-}"
JAR="$(mktemp)"
trap 'rm -f "$JAR"' EXIT
fail() { echo "FAILED: $*"; exit 1; }

# 1. sign-in page: gives the CSRF cookie (Django's default name, csrftoken)
curl -fsS -c "$JAR" -b "$JAR" -o /dev/null "$URL/connexion/" || fail "the sign-in page does not open"
TOKEN="$(awk '$6 == "csrftoken" { print $7 }' "$JAR" | tail -1)"
[ -n "$TOKEN" ] || fail "the sign-in page gave no CSRF cookie"

# 2. sign in: a correct password redirects (302) away from the sign-in page; a wrong one shows the form again (200)
RESULT="$(curl -sS -c "$JAR" -b "$JAR" -o /dev/null -w '%{http_code} %{redirect_url}' \
  -H "Referer: $URL/connexion/" \
  --data-urlencode "csrfmiddlewaretoken=$TOKEN" \
  --data-urlencode "username=$LOGIN" \
  --data-urlencode "password=$PASSWORD" \
  "$URL/connexion/")"
case "$RESULT" in
  302\ *) ;;
  *) fail "sign-in refused for \"$LOGIN\" (answer: $RESULT)" ;;
esac
case "$RESULT" in
  *"/connexion/"*) fail "sign-in leads back to the sign-in page ($RESULT)" ;;
esac
grep -q "sessionid" "$JAR" || fail "no session cookie after the sign-in"
echo "  ok  signed in as \"$LOGIN\""

# 3. home page with the session: a page of the tool, signed in, with the version in the footer
PAGE="$(curl -fsS -L -c "$JAR" -b "$JAR" "$URL/")" || fail "the home page does not open after the sign-in"
grep -q 'href="/deconnexion/"\|action="/deconnexion/"' <<<"$PAGE" || fail "the home page is not the page of a signed-in person"
echo "  ok  home page opens signed in"
if [ -n "$VERSION" ]; then
  grep -q 'class="pied-version"[^<]*'"${VERSION//./\\.}" <<<"$PAGE" || fail "the footer does not show the version $VERSION"
  echo "  ok  footer shows version $VERSION"
fi
