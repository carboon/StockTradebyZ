#!/usr/bin/env bash

set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$PROJECT_ROOT"

mkdir -p deploy/systemd deploy/launchd

if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

BACKEND_HOST="${BACKEND_HOST:-0.0.0.0}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_HOST="${FRONTEND_HOST:-0.0.0.0}"
FRONTEND_PORT="${FRONTEND_PORT:-5173}"
VITE_API_BASE_URL="${VITE_API_BASE_URL:-http://127.0.0.1:${BACKEND_PORT}/api}"

generate_systemd() {
  cat > deploy/systemd/stocktrader-backend.service <<EOF
[Unit]
Description=StockTrader Backend
After=network.target

[Service]
Type=simple
WorkingDirectory=${PROJECT_ROOT}
EnvironmentFile=${PROJECT_ROOT}/.env
ExecStart=${PROJECT_ROOT}/.venv/bin/uvicorn app.main:app --app-dir backend --host ${BACKEND_HOST} --port ${BACKEND_PORT}
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
EOF

  cat > deploy/systemd/stocktrader-frontend.service <<EOF
[Unit]
Description=StockTrader Frontend
After=network.target

[Service]
Type=simple
WorkingDirectory=${PROJECT_ROOT}/frontend
Environment=VITE_API_BASE_URL=${VITE_API_BASE_URL}
ExecStart=/bin/sh -lc 'printf "VITE_API_BASE_URL=%s\n" "$VITE_API_BASE_URL" > .env.local && npm run dev -- --host ${FRONTEND_HOST} --port ${FRONTEND_PORT}'
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
EOF

  cat <<EOF
已生成 systemd 用户服务文件：
- deploy/systemd/stocktrader-backend.service
- deploy/systemd/stocktrader-frontend.service

安装示例：
mkdir -p ~/.config/systemd/user
cp deploy/systemd/*.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now stocktrader-backend.service stocktrader-frontend.service
EOF
}

generate_launchd() {
  local user_home
  user_home="${HOME}"

  cat > deploy/launchd/com.stocktrader.backend.plist <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.stocktrader.backend</string>
  <key>ProgramArguments</key>
  <array>
    <string>${PROJECT_ROOT}/.venv/bin/uvicorn</string>
    <string>app.main:app</string>
    <string>--app-dir</string><string>backend</string>
    <string>--host</string><string>${BACKEND_HOST}</string>
    <string>--port</string><string>${BACKEND_PORT}</string>
  </array>
  <key>WorkingDirectory</key><string>${PROJECT_ROOT}</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>${PROJECT_ROOT}/data/logs/backend.launchd.log</string>
  <key>StandardErrorPath</key><string>${PROJECT_ROOT}/data/logs/backend.launchd.err</string>
</dict>
</plist>
EOF

  cat > deploy/launchd/com.stocktrader.frontend.plist <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.stocktrader.frontend</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/sh</string>
    <string>-lc</string>
    <string>cd ${PROJECT_ROOT}/frontend && printf "VITE_API_BASE_URL=%s\n" "${VITE_API_BASE_URL}" > .env.local && npm run dev -- --host ${FRONTEND_HOST} --port ${FRONTEND_PORT}</string>
  </array>
  <key>WorkingDirectory</key><string>${PROJECT_ROOT}/frontend</string>
  <key>RunAtLoad</key><true/>
  <key>KeepAlive</key><true/>
  <key>StandardOutPath</key><string>${PROJECT_ROOT}/data/logs/frontend.launchd.log</string>
  <key>StandardErrorPath</key><string>${PROJECT_ROOT}/data/logs/frontend.launchd.err</string>
</dict>
</plist>
EOF

  cat <<EOF
已生成 LaunchAgent 文件：
- deploy/launchd/com.stocktrader.backend.plist
- deploy/launchd/com.stocktrader.frontend.plist

安装示例：
mkdir -p ${user_home}/Library/LaunchAgents
cp deploy/launchd/*.plist ${user_home}/Library/LaunchAgents/
launchctl unload ${user_home}/Library/LaunchAgents/com.stocktrader.backend.plist 2>/dev/null || true
launchctl unload ${user_home}/Library/LaunchAgents/com.stocktrader.frontend.plist 2>/dev/null || true
launchctl load ${user_home}/Library/LaunchAgents/com.stocktrader.backend.plist
launchctl load ${user_home}/Library/LaunchAgents/com.stocktrader.frontend.plist
EOF
}

case "$(uname -s)" in
  Linux)
    generate_systemd
    ;;
  Darwin)
    generate_launchd
    ;;
  *)
    echo "当前系统不支持自动生成守护配置：$(uname -s)" >&2
    exit 1
    ;;
esac
