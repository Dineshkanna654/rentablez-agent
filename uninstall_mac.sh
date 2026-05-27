#!/usr/bin/env bash
# uninstall_mac.sh — remove the Rentablez agent but preserve baseline.json
# so reinstalling on the same laptop keeps its original baseline.
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "ERROR: must run as root (try: sudo $0)" >&2
  exit 1
fi

echo "==> Stopping LaunchDaemon"
launchctl bootout system /Library/LaunchDaemons/com.rentablez.agent.plist 2>/dev/null || true

echo "==> Removing files (preserving baseline.json)"
rm -f /Library/LaunchDaemons/com.rentablez.agent.plist
rm -rf /usr/local/rentablez
rm -rf /etc/rentablez
find /var/lib/rentablez -mindepth 1 ! -name baseline.json -delete 2>/dev/null || true

echo "==> Uninstall complete."
echo "    Baseline preserved at /var/lib/rentablez/baseline.json"
echo "    To fully wipe, run: sudo rm -rf /var/lib/rentablez /var/log/rentablez"
