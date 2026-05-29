#!/usr/bin/env bash
# setup_mac.sh — one-shot installer for the Rentablez agent on macOS.
# Run as: sudo ./setup_mac.sh
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "ERROR: must run as root (try: sudo $0)" >&2
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "ERROR: python3 not found. macOS should ship with python3 at /usr/bin/python3." >&2
  exit 1
fi

SCRIPT_DIR="$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"

TOKEN=""
while [[ -z "$TOKEN" ]]; do
  read -rp "Enter device token (e.g. CHEA-MAC-BOOK-0010): " TOKEN
  if [[ -z "$TOKEN" ]]; then
    echo "  Token cannot be empty."
  fi
done

ENDPOINT="${RENTABLEZ_ENDPOINT:-https://api.rentablez.com/devices/checkin}"

echo "==> Creating directories"
mkdir -p /usr/local/rentablez /etc/rentablez /var/lib/rentablez /var/log/rentablez
chown -R root:wheel /etc/rentablez /var/lib/rentablez /var/log/rentablez
chmod 700 /etc/rentablez /var/lib/rentablez

echo "==> Copying agent files"
rm -rf /usr/local/rentablez/rentablez
cp -R "$SCRIPT_DIR/rentablez" /usr/local/rentablez/
cp "$SCRIPT_DIR/rentablez_agent.py" /usr/local/rentablez/
chown -R root:wheel /usr/local/rentablez
chmod 755 /usr/local/rentablez /usr/local/rentablez/rentablez_agent.py
find /usr/local/rentablez/rentablez -type f -exec chmod 644 {} \;
find /usr/local/rentablez/rentablez -type d -exec chmod 755 {} \;

echo "==> Writing config"
cat > /etc/rentablez/config.json <<JSON
{
  "device_token": "$TOKEN",
  "endpoint": "$ENDPOINT",
  "installed_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
JSON
chmod 600 /etc/rentablez/config.json
chown root:wheel /etc/rentablez/config.json

echo "==> Installing LaunchDaemon"
cp "$SCRIPT_DIR/com.rentablez.agent.plist" /Library/LaunchDaemons/
chown root:wheel /Library/LaunchDaemons/com.rentablez.agent.plist
chmod 644 /Library/LaunchDaemons/com.rentablez.agent.plist

launchctl bootout system /Library/LaunchDaemons/com.rentablez.agent.plist 2>/dev/null || true
launchctl bootstrap system /Library/LaunchDaemons/com.rentablez.agent.plist
launchctl kickstart system/com.rentablez.agent

echo
echo "===================================="
echo "  Rentablez agent installed."
echo "  Device token: $TOKEN"
echo "  Endpoint:     $ENDPOINT"
echo "  Log file:     /var/log/rentablez/agent.log"
echo "===================================="
