#!/usr/bin/env bash
# Stop and remove the OBAgent launchd services.
set -euo pipefail
LA="$HOME/Library/LaunchAgents"
UID_NUM="$(id -u)"
for label in com.webprofits.obagent.web com.webprofits.obagent.tunnel; do
  launchctl bootout "gui/$UID_NUM/$label" 2>/dev/null || true
  rm -f "$LA/$label.plist"
  echo "removed $label"
done
