#!/bin/bash
# Install mosquitto-scw's private files, owned by the broker user (uid 1883)
# with mode 600, as Mosquitto 2.1+ requires:
#   mosquitto/config/acl     <- copy of the tracked mosquitto/acl
#   mosquitto/config/passwd  <- built from a "user password" file
# Both are git-ignored. Run from anywhere; re-run after editing mosquitto/acl
# or the credentials file, then: docker compose restart mosquitto
#
# Usage: mosquitto/setup.sh [CREDENTIALS_FILE]   (default ~/secrets/weewxscw-mqtt.txt)
set -euo pipefail
cd "$(dirname "$0")"
CREDS="${1:-$HOME/secrets/weewxscw-mqtt.txt}"
IMAGE=eclipse-mosquitto:2.1.2-alpine
[ -r "$CREDS" ] || { echo "credentials file not readable: $CREDS" >&2; exit 1; }

# Build the password file in a temp dir, then install both files as root
# inside a throwaway container (no host sudo needed).
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
cp acl "$TMP/acl"
touch "$TMP/passwd"; chmod 600 "$TMP/passwd"
grep -v -E '^\s*(#|$)' "$CREDS" | while read -r u p; do
  docker run --rm --user "$(id -u):$(id -g)" -v "$TMP:/t" "$IMAGE" \
    mosquitto_passwd -b /t/passwd "$u" "$p" >/dev/null
  echo "user: $u"
done
docker run --rm -v "$TMP:/t:ro" -v "$PWD/config:/c" --entrypoint sh "$IMAGE" -c '
  install -o 1883 -g 1883 -m 600 /t/acl /c/acl &&
  install -o 1883 -g 1883 -m 600 /t/passwd /c/passwd'
ls -ln config
