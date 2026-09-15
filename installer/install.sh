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
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUNDLE_ROOT="${MATERIAL_MATCHER_BUNDLE_ROOT:-}"

fail() { echo "安装失败：$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || fail "请使用 sudo ./install.sh"

if [[ -z "$BUNDLE_ROOT" ]]; then
  if [[ -f "$SCRIPT_DIR/offline-manifest.json" ]]; then
    BUNDLE_ROOT="$SCRIPT_DIR"
  elif [[ -f "$SCRIPT_DIR/../offline-manifest.json" ]]; then
    BUNDLE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
  fi
fi

RELEASE_VERSION=""
MODEL_ID=""
MANIFEST_SHA=""
if [[ -n "$BUNDLE_ROOT" ]]; then
  BUNDLE_ROOT="$(cd "$BUNDLE_ROOT" && pwd)"
  [[ -f "$BUNDLE_ROOT/offline-manifest.json" ]] || fail "离线包缺少 offline-manifest.json"
  [[ -f "$BUNDLE_ROOT/verify_offline_bundle.py" ]] || fail "离线包缺少 verify_offline_bundle.py"
  python3 "$BUNDLE_ROOT/verify_offline_bundle.py" "$BUNDLE_ROOT" || fail "离线包完整性或架构校验未通过"
  read -r RELEASE_VERSION MODEL_ID < <(python3 - "$BUNDLE_ROOT/offline-manifest.json" <<'PY'
import json, sys
m=json.load(open(sys.argv[1],encoding='utf-8'))
print(m['release_version'], m['model_id'])
PY
)
  MANIFEST_SHA="$(python3 - "$BUNDLE_ROOT/offline-manifest.json" <<'PY'
import hashlib, sys
print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())
PY
)"
  if [[ "${MATERIAL_MATCHER_ALLOW_UNSUPPORTED_OS:-0}" != "1" ]]; then
    grep -Eqi 'kylin|银河麒麟' /etc/os-release 2>/dev/null || fail "正式离线安装包仅验收银河麒麟 Linux V10；测试其他 Linux 请显式设置 MATERIAL_MATCHER_ALLOW_UNSUPPORTED_OS=1"
  fi
fi

find_data_mount() {
  findmnt -rn -o TARGET,FSTYPE,OPTIONS | while read -r target fs opts; do
    case "$fs" in ext2|ext3|ext4|xfs|btrfs) ;; *) continue ;; esac
    [[ "$target" == /boot* ]] && continue
    [[ "$target" == /media/* || "$target" == /run/media/* ]] && continue
    grep -qw ro <<<"${opts//,/ }" && continue
    [[ -w "$target" ]] || continue
    avail=$(df -Pk "$target" | awk 'NR==2 {print $4}')
    printf '%s\t%s\n' "$avail" "$target"
  done | sort -nr | head -1 | cut -f2-
}

port_free() {
  python3 - "$1" <<'PY'
import socket, sys
port=int(sys.argv[1]); sock=socket.socket()
try: sock.bind(("0.0.0.0",port))
except OSError: raise SystemExit(1)
finally: sock.close()
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
  fail "没有找到可用高位端口"
}

activate_link() {
  local link="$1" target="$2" next="${1}.next.$$"
  rm -f "$next"
  ln -s "$target" "$next"
  mv -Tf "$next" "$link"
}

mkdir -p "$OPT/releases" "$ETC/secret" "$ETC/profiles" "$ETC/catalogs" \
  "$ETC/mappings" "$ETC/dictionaries" "$ETC/templates" "$LOG"

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

mkdir -p "$VAR/meta" "$VAR/datasets" "$VAR/uploads" "$VAR/results" "$VAR/indexes" \
  "$VAR/models/releases" "$VAR/jobs" "$VAR/tmp"

if [[ ! -f "$SERVER_ENV" ]]; then
  printf 'MATERIAL_MATCHER_HOST=0.0.0.0\nMATERIAL_MATCHER_PORT=%s\n' "$(choose_port)" >"$SERVER_ENV"
fi

if [[ ! -f "$PASSWORD_FILE" ]]; then
  password=$(python3 - <<'PY'
import secrets, string
alphabet=string.ascii_letters+string.digits
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

OLD_RELEASE=""
OLD_MODEL_ROOT=""
SERVICE_WAS_ACTIVE=0
if [[ -L "$OPT/current" ]]; then OLD_RELEASE="$(readlink -f "$OPT/current")"; fi
if [[ -L "$VAR/models/current" ]]; then OLD_MODEL_ROOT="$(readlink -f "$VAR/models/current")"; fi
if systemctl is-active --quiet material_matcher.service 2>/dev/null; then SERVICE_WAS_ACTIVE=1; fi

RELEASE_DEST=""
MODEL_RELEASE_ROOT=""
MODEL_COPIED=0
if [[ -n "$BUNDLE_ROOT" ]]; then
  RELEASE_DEST="$OPT/releases/$RELEASE_VERSION"
  if [[ -d "$RELEASE_DEST" ]]; then
    [[ -f "$RELEASE_DEST/.bundle_manifest_sha256" ]] || fail "同版本发布目录已存在但无法确认来源：$RELEASE_DEST"
    [[ "$(cat "$RELEASE_DEST/.bundle_manifest_sha256")" == "$MANIFEST_SHA" ]] || fail "同版本号已存在不同内容，请提升 release_version 后重试"
  else
    RELEASE_STAGE="$OPT/releases/.staging-${RELEASE_VERSION}-$$"
    rm -rf "$RELEASE_STAGE"; mkdir -p "$RELEASE_STAGE"
    cp -a "$BUNDLE_ROOT/release/." "$RELEASE_STAGE/"
    printf '%s\n' "$MANIFEST_SHA" >"$RELEASE_STAGE/.bundle_manifest_sha256"
    mv "$RELEASE_STAGE" "$RELEASE_DEST"
  fi

  MODEL_RELEASE_ROOT="$VAR/models/releases/$RELEASE_VERSION"
  if [[ -d "$MODEL_RELEASE_ROOT" ]]; then
    [[ -f "$MODEL_RELEASE_ROOT/.bundle_manifest_sha256" ]] || fail "同版本模型目录已存在但无法确认来源：$MODEL_RELEASE_ROOT"
    [[ "$(cat "$MODEL_RELEASE_ROOT/.bundle_manifest_sha256")" == "$MANIFEST_SHA" ]] || fail "同版本模型内容与离线包不一致"
  else
    MODEL_STAGE="$VAR/models/releases/.staging-${RELEASE_VERSION}-$$"
    rm -rf "$MODEL_STAGE"; mkdir -p "$MODEL_STAGE/$(dirname "$MODEL_ID")"
    cp -a "$BUNDLE_ROOT/models/$MODEL_ID" "$MODEL_STAGE/$MODEL_ID"
    printf '%s\n' "$MANIFEST_SHA" >"$MODEL_STAGE/.bundle_manifest_sha256"
    mv "$MODEL_STAGE" "$MODEL_RELEASE_ROOT"
    MODEL_COPIED=1
  fi

  [[ -x "$RELEASE_DEST/runtime/bin/python3" ]] || fail "自包含 Python Runtime 不可执行"
  [[ -x "$RELEASE_DEST/runtime/bin/material-matcher" ]] || fail "material-matcher 启动器不可执行"
  [[ -f "$RELEASE_DEST/web/dist/index.html" ]] || fail "Vue 前端发布产物缺失"
  [[ -f "$RELEASE_DEST/release-manifest.json" ]] || fail "release manifest 缺失"
fi

# 不递归扫描已有海量索引/结果；固定目录只调整目录本身，新模型只处理本次版本。
chown "$APP_USER:$APP_USER" "$VAR" "$LOG"
for path in "$VAR/meta" "$VAR/datasets" "$VAR/uploads" "$VAR/results" "$VAR/indexes" "$VAR/models" "$VAR/models/releases" "$VAR/jobs" "$VAR/tmp"; do
  chown "$APP_USER:$APP_USER" "$path"
done
if [[ "$MODEL_COPIED" == "1" ]]; then chown -R "$APP_USER:$APP_USER" "$MODEL_RELEASE_ROOT"; fi

if [[ -n "$BUNDLE_ROOT" ]]; then
  # 以正式运行用户、未来将激活的模型/前端路径执行切换前诊断；此时旧服务仍在线。
  DOCTOR_ENV=(
    "MATERIAL_MATCHER_DATA_DIR=$VAR"
    "MATERIAL_MATCHER_CONFIG_DIR=$ETC"
    "MATERIAL_MATCHER_LOG_DIR=$LOG"
    "MATERIAL_MATCHER_MODEL_ROOT=$MODEL_RELEASE_ROOT"
    "MATERIAL_MATCHER_WEB_DIST_DIR=$RELEASE_DEST/web/dist"
  )
  if command -v runuser >/dev/null 2>&1; then
    runuser -u "$APP_USER" -- env "${DOCTOR_ENV[@]}" "$RELEASE_DEST/runtime/bin/material-matcher" doctor \
      --require-frontend --require-embedding --require-release-manifest >/dev/null \
      || fail "新版本部署前诊断失败，旧服务保持不变"
  else
    env "${DOCTOR_ENV[@]}" "$RELEASE_DEST/runtime/bin/material-matcher" doctor \
      --require-frontend --require-embedding --require-release-manifest >/dev/null \
      || fail "新版本部署前诊断失败，旧服务保持不变"
  fi
fi

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
Environment=MATERIAL_MATCHER_MODEL_ROOT=$VAR/models/current
Environment=MATERIAL_MATCHER_WEB_DIST_DIR=$OPT/current/web/dist
ExecStart=$OPT/current/runtime/bin/material-matcher serve --host \${MATERIAL_MATCHER_HOST} --port \${MATERIAL_MATCHER_PORT}
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

rollback_activation() {
  echo "新版本启动失败，回滚到安装前状态..." >&2
  systemctl stop material_matcher.service >/dev/null 2>&1 || true
  if [[ -n "$OLD_RELEASE" && -d "$OLD_RELEASE" ]]; then
    activate_link "$OPT/current" "$OLD_RELEASE"
  else
    rm -f "$OPT/current"
  fi
  if [[ -n "$OLD_MODEL_ROOT" && -d "$OLD_MODEL_ROOT" ]]; then
    activate_link "$VAR/models/current" "$OLD_MODEL_ROOT"
  else
    rm -f "$VAR/models/current"
  fi
  systemctl daemon-reload >/dev/null 2>&1 || true
  if [[ "$SERVICE_WAS_ACTIVE" == "1" && -n "$OLD_RELEASE" && -x "$OLD_RELEASE/runtime/bin/material-matcher" ]]; then
    systemctl start material_matcher.service >/dev/null 2>&1 || true
  fi
}

if [[ -n "$BUNDLE_ROOT" ]]; then
  # 从这里开始才进入短暂停机窗口。
  if [[ "$SERVICE_WAS_ACTIVE" == "1" ]]; then
    systemctl stop material_matcher.service || fail "无法停止旧版本服务，未执行版本切换"
  fi
  if [[ -n "$OLD_RELEASE" && "$OLD_RELEASE" != "$RELEASE_DEST" ]]; then activate_link "$OPT/previous" "$OLD_RELEASE"; fi
  if [[ -n "$OLD_MODEL_ROOT" && "$OLD_MODEL_ROOT" != "$MODEL_RELEASE_ROOT" ]]; then activate_link "$VAR/models/previous" "$OLD_MODEL_ROOT"; fi
  activate_link "$VAR/models/current" "$MODEL_RELEASE_ROOT"
  activate_link "$OPT/current" "$RELEASE_DEST"
fi

systemctl daemon-reload
if [[ -x "$OPT/current/runtime/bin/material-matcher" ]]; then
  if ! systemctl enable material_matcher.service; then
    [[ -n "$BUNDLE_ROOT" ]] && rollback_activation
    fail "systemd 服务启用失败"
  fi
  # 旧版 systemd(如 SLES12 的 228)会把与 stop 任务并发的 start 任务取消,
  # 因此先等停止任务彻底落定,再显式 start,而不是依赖 enable --now。
  for _ in $(seq 1 60); do
    [[ "$(systemctl is-active material_matcher.service 2>/dev/null || true)" == "inactive" ]] && break
    sleep 1
  done
  if ! systemctl start material_matcher.service; then
    [[ -n "$BUNDLE_ROOT" ]] && rollback_activation
    fail "systemd 服务启动失败"
  fi
  set -a; source "$SERVER_ENV"; set +a
  if ! python3 - "${MATERIAL_MATCHER_PORT}" <<'PY'
import json, sys, time, urllib.request
port=int(sys.argv[1]); last=None
for _ in range(30):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health/ready",timeout=2) as response:
            payload=json.load(response)
        if payload.get("status")=="ready": raise SystemExit(0)
        last=payload
    except Exception as exc:
        last=str(exc)
    time.sleep(1)
print(f"readiness 未通过: {last}",file=sys.stderr)
raise SystemExit(1)
PY
  then
    [[ -n "$BUNDLE_ROOT" ]] && rollback_activation
    fail "服务已启动，但 readiness 检查未通过"
  fi
  echo "MATERIAL_MATCHER 安装完成。"
  echo "访问端口：${MATERIAL_MATCHER_PORT}"
  echo "管理员账号：admin"
  echo "初始密码文件：$PASSWORD_FILE"
  [[ -n "$RELEASE_VERSION" ]] && echo "当前版本：$RELEASE_VERSION"
else
  echo "安装目录已准备；正式离线发布包尚未安装到 $OPT/current。"
fi
