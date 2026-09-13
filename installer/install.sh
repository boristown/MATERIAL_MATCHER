#!/usr/bin/env bash
set -euo pipefail

APP_USER="material_matcher"
OPT="/opt/material_matcher"
ETC="/etc/material_matcher"
VAR="/var/lib/material_matcher"
LOG="/var/log/material_matcher"
PASSWORD_FILE="$ETC/secret/admin_password.env"
SERVER_ENV="$ETC/server.env"
STORAGE_ENV="$ETC/storage.env"
SERVICE_FILE="/etc/systemd/system/material_matcher.service"

[[ $EUID -eq 0 ]] || { echo "请使用 sudo ./install.sh"; exit 1; }

find_data_mount() {
  findmnt -rn -o TARGET,FSTYPE,OPTIONS | while read -r target fs opts; do
    case "$fs" in ext2|ext3|ext4|xfs|btrfs) ;; *) continue ;; esac
    [[ "$target" == /boot* ]] && continue
    grep -qw ro <<<"${opts//,/ }" && continue
    [[ -w "$target" ]] || continue
    avail=$(df -Pk "$target" | awk 'NR==2 {print $4}')
    printf '%s\t%s\n' "$avail" "$target"
  done | sort -nr | head -1 | cut -f2-
}

port_free() {
  python3 - "$1" <<'PY'
import socket
import sys
port = int(sys.argv[1])
sock = socket.socket()
try:
    sock.bind(("0.0.0.0", port))
except OSError:
    raise SystemExit(1)
finally:
    sock.close()
PY
}

choose_port() {
  for _ in $(seq 1 200); do
    port=$((12000 + $(od -An -N2 -tu2 /dev/urandom) % 18000))
    if port_free "$port"; then echo "$port"; return; fi
  done
  for port in $(seq 12000 29999); do
    if port_free "$port"; then echo "$port"; return; fi
  done
  echo "没有找到可用高位端口" >&2
  exit 1
}

mkdir -p "$OPT/releases" "$ETC/secret" "$ETC/profiles" "$ETC/catalogs" \
  "$ETC/mappings" "$ETC/dictionaries" "$LOG"

if [[ ! -f "$STORAGE_ENV" ]]; then
  data_mount=$(find_data_mount || true)
  [[ -n "$data_mount" ]] || data_mount="/var/lib"
  physical_data="$data_mount/material_matcher_data"
  mkdir -p "$physical_data"
  if [[ ! -e "$VAR" ]]; then
    ln -s "$physical_data" "$VAR"
  elif [[ -d "$VAR" && ! -L "$VAR" && -z "$(find "$VAR" -mindepth 1 -maxdepth 1 -print -quit)" ]]; then
    rmdir "$VAR"
    ln -s "$physical_data" "$VAR"
  else
    physical_data="$VAR"
  fi
  printf 'MATERIAL_MATCHER_DATA_MOUNT=%q\nMATERIAL_MATCHER_DATA_DIR=%q\n' "$data_mount" "$VAR" >"$STORAGE_ENV"
else
  mkdir -p "$VAR"
fi

mkdir -p "$VAR/meta" "$VAR/uploads" "$VAR/results" "$VAR/indexes" "$VAR/models" "$VAR/tmp"

if [[ ! -f "$SERVER_ENV" ]]; then
  printf 'MATERIAL_MATCHER_HOST=0.0.0.0\nMATERIAL_MATCHER_PORT=%s\n' "$(choose_port)" >"$SERVER_ENV"
fi

if [[ ! -f "$PASSWORD_FILE" ]]; then
  password=$(python3 - <<'PY'
import secrets
import string
alphabet = string.ascii_letters + string.digits
print(''.join(secrets.choice(alphabet) for _ in range(10)))
PY
)
  printf 'MATERIAL_MATCHER_ADMIN_PASSWORD=%s\n' "$password" >"$PASSWORD_FILE"
fi
chown root:root "$PASSWORD_FILE"
chmod 0600 "$PASSWORD_FILE"

if ! id "$APP_USER" >/dev/null 2>&1; then
  useradd --system --home "$VAR" --shell /usr/sbin/nologin "$APP_USER"
fi
chown -R "$APP_USER:$APP_USER" "$VAR" "$LOG"

cat >"$SERVICE_FILE" <<EOF
[Unit]
Description=Material Matcher
After=network.target

[Service]
Type=simple
User=$APP_USER
Group=$APP_USER
WorkingDirectory=$OPT/current
EnvironmentFile=$SERVER_ENV
EnvironmentFile=$STORAGE_ENV
EnvironmentFile=$PASSWORD_FILE
Environment=MATERIAL_MATCHER_CONFIG_DIR=$ETC
Environment=MATERIAL_MATCHER_LOG_DIR=$LOG
ExecStart=$OPT/current/runtime/bin/material-matcher --host \${MATERIAL_MATCHER_HOST} --port \${MATERIAL_MATCHER_PORT}
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
if [[ -x "$OPT/current/runtime/bin/material-matcher" ]]; then
  systemctl enable --now material_matcher.service
  set -a
  source "$SERVER_ENV"
  set +a
  python3 - "${MATERIAL_MATCHER_PORT}" <<'PY'
import json
import sys
import urllib.request
port = int(sys.argv[1])
with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health/ready", timeout=10) as response:
    payload = json.load(response)
if payload.get("status") != "ready":
    raise SystemExit("服务已启动，但 readiness 检查未通过")
PY
else
  echo "安装目录已准备；正式离线发布包解压到 $OPT/current 后再启动服务。"
fi
