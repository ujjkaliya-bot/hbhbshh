#!/usr/bin/env bash
#
# install_from_zip.sh — local 24/7 installer for the Kilo Host Agent.
#
# Use this when you have ALREADY uploaded/extracted the kilo-host-agent.zip on a
# Selfhost.dev Ubuntu/Debian server and just want to install + start it as a
# systemd service. (For the fully pre-filled one-command install, use the
# self-extracting install_247.sh instead.)
#
#   unzip kilo-host-agent.zip && cd kilo-host-agent
#   sudo bash install_from_zip.sh
#
# Run as root. Values can be pre-set via env to skip the prompts, e.g.
#   sudo TELEGRAM_BOT_TOKEN='123:ABC' ADMIN_USER_ID='123' bash install_from_zip.sh
set -euo pipefail

c_grn=$'\033[1;32m'; c_ylw=$'\033[1;33m'; c_red=$'\033[1;31m'; c_reset=$'\033[0m'
ok()   { printf "${c_grn}  ✓ %s${c_reset}\n" "$1"; }
info() { printf "${c_ylw}==> %s${c_reset}\n" "$1"; }
die()  { printf "${c_red}✗ %s${c_reset}\n" "$1" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "Root ke roop me chalayein (sudo bash install_from_zip.sh)."

SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_DIR="/opt/kilo-host-agent"
SERVICE_NAME="kilo-host-agent"

info "System packages install ho rahe hain..."
if command -v apt-get >/dev/null 2>&1; then
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -y -qq
  apt-get install -y -qq python3 python3-pip python3-venv python3-dev \
    build-essential git curl unzip openssh-client ca-certificates
elif command -v dnf >/dev/null 2>&1; then
  dnf install -y -q python3 python3-pip git curl unzip openssh-clients
else
  die "apt-get/dnf nahi mila — manually python3 + pip install karein."
fi
ok "System packages ready"

info "Files -> $APP_DIR"
mkdir -p "$APP_DIR"
cp -f "$SRC_DIR"/*.py "$SRC_DIR"/servers.json "$SRC_DIR"/requirements.txt \
      "$SRC_DIR"/.env.example "$APP_DIR"/ 2>/dev/null || true
ok "Files copied"

info "Python virtual environment..."
python3 -m venv "$APP_DIR/.venv"
"$APP_DIR/.venv/bin/pip" install --upgrade pip -q
"$APP_DIR/.venv/bin/pip" install -r "$APP_DIR/requirements.txt" -q
ok "Dependencies installed"

info "Configuration"
TG_TOKEN="${TELEGRAM_BOT_TOKEN:-}"
ADMIN_ID="${ADMIN_USER_ID:-}"
AI_KEY="${AI_API_KEY:-}"
AI_BASE="${AI_BASE_URL:-https://api.kilo.ai/api/openrouter/v1}"
AI_MODEL="${AI_MODEL:-kilo-auto/free}"

if [ -f "$APP_DIR/.env" ]; then
  set -a; . "$APP_DIR/.env"; set +a
  TG_TOKEN="${TELEGRAM_BOT_TOKEN:-$TG_TOKEN}"
  ADMIN_ID="${ADMIN_USER_ID:-$ADMIN_ID}"
fi
[ -n "$TG_TOKEN" ] || read -rp "1) TELEGRAM_BOT_TOKEN: " TG_TOKEN
[ -n "$ADMIN_ID" ] || read -rp "2) ADMIN_USER_ID (numeric): " ADMIN_ID
[ -n "$AI_KEY" ]   || read -rp "3) AI_API_KEY (Enter = skip): " AI_KEY || true

cat > "$APP_DIR/.env" <<EOF
TELEGRAM_BOT_TOKEN=$TG_TOKEN
ADMIN_USER_ID=$ADMIN_ID
AI_API_KEY=$AI_KEY
AI_BASE_URL=$AI_BASE
AI_MODEL=$AI_MODEL
WATCHDOG_INTERVAL=60
EOF
chmod 600 "$APP_DIR/.env"
ok ".env written"

info "Cluster SSH key generate ho rahi hai..."
CLUSTER_KEY_PATH=/root/.ssh/cluster_key "$APP_DIR/.venv/bin/python" -c \
  "import cluster_manager as cm; cm.ensure_cluster_key()" || true
ok "Cluster key ready"

info "systemd service install ho rahi hai..."
cat > "/etc/systemd/system/$SERVICE_NAME.service" <<EOF
[Unit]
Description=Kilo Host Agent — 24/7 AI Coding & Bot Hosting Agent
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
WorkingDirectory=$APP_DIR
EnvironmentFile=$APP_DIR/.env
Environment=PYTHONUNBUFFERED=1
Environment=PORT=10000
ExecStart=$APP_DIR/.venv/bin/python $APP_DIR/main.py
Restart=always
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable "$SERVICE_NAME" >/dev/null 2>&1 || true
systemctl restart "$SERVICE_NAME"
sleep 2
if systemctl is-active --quiet "$SERVICE_NAME"; then
  ok "Service chal rahi hai (24/7 + reboot autostart)"
else
  printf "${c_ylw}Service abhi active nahi. Logs: journalctl -u %s -n 50${c_reset}\n" "$SERVICE_NAME"
fi

printf "\n${c_grn}================ CLUSTER SSH PUBLIC KEY ================${c_reset}\n"
cat /root/.ssh/cluster_key.pub 2>/dev/null || echo "(key nahi mili)"
printf "${c_grn}=========================================================${c_reset}\n\n"
printf "${c_ylw}Ye key Account 2/Account 3 ke Org Settings > SSH Keys me paste karein,${c_reset}\n"
printf "${c_ylw}phir Telegram me:  /addserver server2 <IP> 22 root 2048${c_reset}\n"
printf "${c_ylw}Live logs: journalctl -u %s -f${c_reset}\n" "$SERVICE_NAME"
