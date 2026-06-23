#!/usr/bin/env bash
# Install always-on macOS launchd services for the live read-only stack:
#   - com.webprofits.obagent.tunnel : self-healing SSH tunnel to the PMS
#   - com.webprofits.obagent.web    : the backend (live profile) on :8000
# Both start at login and are kept alive (launchd relaunches on exit/crash).
#
# Usage: ./scripts/install_services.sh
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
PY="$REPO/.venv/bin/python"
ENV_FILE="$REPO/.env.live"
LA="$HOME/Library/LaunchAgents"
LOGS="$HOME/Library/Logs"
UID_NUM="$(id -u)"

[ -x "$PY" ] || { echo "venv python not found at $PY"; exit 1; }
[ -f "$ENV_FILE" ] || { echo "$ENV_FILE not found"; exit 1; }

# Pull SSH settings from .env.live
set -a; . "$ENV_FILE"; set +a
SSH_PORT="${SSH_PORT:-22}"
LOCAL_PORT="${TUNNEL_LOCAL_PORT:-3307}"
KEY="${SSH_KEY/#\~/$HOME}"
: "${SSH_HOST:?set SSH_HOST in .env.live}" "${SSH_USER:?set SSH_USER in .env.live}"

mkdir -p "$LA" "$LOGS"

# Free the ports if something is already bound (e.g. a manual run)
pkill -f "studio_agent.web" 2>/dev/null || true
pkill -f "ssh -N .*${LOCAL_PORT}:127.0.0.1:3306" 2>/dev/null || true

TUNNEL_PLIST="$LA/com.webprofits.obagent.tunnel.plist"
WEB_PLIST="$LA/com.webprofits.obagent.web.plist"

cat > "$TUNNEL_PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.webprofits.obagent.tunnel</string>
  <key>ProgramArguments</key><array>
    <string>/usr/bin/ssh</string><string>-N</string>
    <string>-o</string><string>ExitOnForwardFailure=yes</string>
    <string>-o</string><string>StrictHostKeyChecking=accept-new</string>
    <string>-o</string><string>ServerAliveInterval=30</string>
    <string>-o</string><string>ServerAliveCountMax=3</string>
    <string>-o</string><string>BatchMode=yes</string>
    <string>-i</string><string>${KEY}</string>
    <string>-p</string><string>${SSH_PORT}</string>
    <string>-L</string><string>${LOCAL_PORT}:127.0.0.1:3306</string>
    <string>${SSH_USER}@${SSH_HOST}</string>
  </array>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>${LOGS}/obagent-tunnel.log</string>
  <key>StandardErrorPath</key><string>${LOGS}/obagent-tunnel.log</string>
</dict></plist>
PLIST

cat > "$WEB_PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>com.webprofits.obagent.web</string>
  <key>ProgramArguments</key><array>
    <string>${PY}</string><string>-m</string><string>studio_agent.web</string>
  </array>
  <key>WorkingDirectory</key><string>${REPO}</string>
  <key>EnvironmentVariables</key><dict>
    <key>STUDIO_ENV_FILE</key><string>.env.live</string>
    <key>PATH</key><string>/usr/bin:/bin:/usr/sbin:/sbin</string>
  </dict>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>${LOGS}/obagent-web.log</string>
  <key>StandardErrorPath</key><string>${LOGS}/obagent-web.log</string>
</dict></plist>
PLIST

for plist in "$TUNNEL_PLIST" "$WEB_PLIST"; do
  label="$(basename "$plist" .plist)"
  launchctl bootout "gui/$UID_NUM/$label" 2>/dev/null || true
  launchctl bootstrap "gui/$UID_NUM" "$plist"
  launchctl enable "gui/$UID_NUM/$label" 2>/dev/null || true
done

echo "Installed and started:"
echo "  - com.webprofits.obagent.tunnel  (localhost:${LOCAL_PORT} -> ${SSH_HOST})"
echo "  - com.webprofits.obagent.web     (http://127.0.0.1:8000)"
echo "Logs: ${LOGS}/obagent-tunnel.log , ${LOGS}/obagent-web.log"
echo "Uninstall: ./scripts/uninstall_services.sh"
