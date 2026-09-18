#!/usr/bin/env bash
# MATERIAL_MATCHER 正式离线安装脚本（非交互）。
# 供 install_wizard.sh 调用，也允许维护人员直接以 root 运行。
# 进度协议：stdout 输出 "@@STEP@@|<百分比>|<阶段说明>"；
# 结尾输出 "@@RESULT@@|<json>"（不含密码）。业务错误输出"安装失败：<原因>"并以专用退出码结束。
set -euo pipefail

APP_USER="material_matcher"
OPT="${MM_INSTALL_PREFIX:-/opt/material_matcher}"
ETC="/etc/material_matcher"
VAR="/var/lib/material_matcher"
LOG="/var/log/material_matcher"
PASSWORD_FILE="$ETC/secret/admin_password.env"
SERVER_ENV="$ETC/server.env"
STORAGE_ENV="$ETC/storage.env"
SERVICE_FILE="/etc/systemd/system/material_matcher.service"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUNDLE_ROOT="${MATERIAL_MATCHER_BUNDLE_ROOT:-}"
DEFAULT_SESSION_TTL_SECONDS=1209600
DEFAULT_PORT="${MM_INSTALL_PORT:-18080}"
REPORT_DIR="$LOG/install-reports"
RUNTIME_DIR_NAME="${MM_PYTHON_RUNTIME_DIR:-runtime}"
NODE_OFFLINE_DIR="${MM_NODE_OFFLINE_DIR:-}"

# 退出码：向导据此给出业务化处理建议。
EXIT_GENERIC=1
EXIT_PORT=40
EXIT_MEDIA=41
EXIT_DISK=42
EXIT_OS=43
EXIT_PRIV=44
EXIT_DB=45
EXIT_DOCTOR=46
EXIT_START=47
EXIT_READY=48

PROGRESS_ON=0
step() {
  # step <百分比> <说明>
  if [[ "$PROGRESS_ON" == "1" ]]; then
    echo "@@STEP@@|${1}|${2}"
  fi
  echo "[$1%] $2"
}

die() {
  # die <退出码> <业务化中文说明>
  echo "安装失败：$2" >&2
  exit "$1"
}

# 解释器解析顺序：介质 bootstrap runtime → 已安装正式 runtime → 系统 python3（仅兜底）。
resolve_python() {
  local candidates=()
  [[ -n "$BUNDLE_ROOT" && -x "$BUNDLE_ROOT/bootstrap/python/bin/python3" ]] && candidates+=("$BUNDLE_ROOT/bootstrap/python/bin/python3")
  [[ -x "$OPT/current/$RUNTIME_DIR_NAME/bin/python3" ]] && candidates+=("$OPT/current/$RUNTIME_DIR_NAME/bin/python3")
  [[ -n "$BUNDLE_ROOT" && -x "$BUNDLE_ROOT/release/$RUNTIME_DIR_NAME/bin/python3" ]] && candidates+=("$BUNDLE_ROOT/release/$RUNTIME_DIR_NAME/bin/python3")
  command -v python3 >/dev/null 2>&1 && candidates+=("$(command -v python3)")
  local c
  for c in "${candidates[@]}"; do
    if "$c" -c 'import json,hashlib,socket' >/dev/null 2>&1; then echo "$c"; return 0; fi
  done
  return 1
}

fail() { echo "安装失败：$*" >&2; exit "$EXIT_GENERIC"; }

[[ $EUID -eq 0 ]] || die "$EXIT_PRIV" "当前账号没有系统管理员权限，无法安装服务。请使用 root 或通过管理员授权重新运行安装程序。"

if [[ -z "$BUNDLE_ROOT" ]]; then
  if [[ -f "$SCRIPT_DIR/offline-manifest.json" ]]; then
    BUNDLE_ROOT="$SCRIPT_DIR"
  elif [[ -f "$SCRIPT_DIR/../offline-manifest.json" ]]; then
    BUNDLE_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
  fi
fi

PY=""
RELEASE_VERSION=""
MODEL_ID=""
MANIFEST_SHA=""
GIT_COMMIT="unknown"
IS_UPGRADE=0

if [[ -n "$BUNDLE_ROOT" ]]; then
  BUNDLE_ROOT="$(cd "$BUNDLE_ROOT" && pwd)"
  [[ -f "$BUNDLE_ROOT/offline-manifest.json" ]] || die "$EXIT_MEDIA" "安装介质缺少 offline-manifest.json，文件可能不完整，请重新复制完整安装介质。"
  [[ -f "$BUNDLE_ROOT/verify_offline_bundle.py" ]] || die "$EXIT_MEDIA" "安装介质缺少 verify_offline_bundle.py，文件可能不完整，请重新复制完整安装介质。"
  PROGRESS_ON="${MM_PROGRESS_ON:-1}"
  step 1 "正在准备安装器运行环境……"
  PY="$(resolve_python || true)"
  [[ -n "$PY" ]] || die "$EXIT_MEDIA" "安装介质缺少可用的 bootstrap 运行环境，且本机也没有可用 Python。请重新复制完整安装介质。"
  step 3 "正在校验安装介质完整性（文件数量较多，请稍候）……"
  if ! "$PY" "$BUNDLE_ROOT/verify_offline_bundle.py" "$BUNDLE_ROOT" >>"${MM_INSTALL_LOG:-/var/tmp/material_matcher_install-detail.log}" 2>&1; then
    echo "介质校验明细：${MM_INSTALL_LOG:-/var/tmp/material_matcher_install-detail.log}" >&2
    die "$EXIT_MEDIA" "安装介质校验失败：文件可能被修改、缺失或架构不匹配。请重新从源头完整复制安装介质后再试；不要继续使用当前介质。"
  fi
  read -r RELEASE_VERSION MODEL_ID < <("$PY" - "$BUNDLE_ROOT/offline-manifest.json" <<'PY'
import json, sys
m=json.load(open(sys.argv[1],encoding='utf-8'))
print(m['release_version'], m['model_id'])
PY
)
  MANIFEST_SHA="$("$PY" - "$BUNDLE_ROOT/offline-manifest.json" <<'PY'
import hashlib, sys
print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest())
PY
)"
  if [[ -f "$BUNDLE_ROOT/release/release-manifest.json" ]]; then
    GIT_COMMIT="$("$PY" - "$BUNDLE_ROOT/release/release-manifest.json" <<'PY'
import json, sys
m=json.load(open(sys.argv[1],encoding='utf-8'))
print(m.get('git_commit') or 'unknown')
PY
)" || true
  fi
  if [[ "${MATERIAL_MATCHER_ALLOW_UNSUPPORTED_OS:-0}" != "1" ]]; then
    step 5 "正在检查操作系统……"
    if ! grep -Eqi 'kylin|银河麒麟' /etc/os-release 2>/dev/null; then
      die "$EXIT_OS" "当前安装包只支持银河麒麟 Linux V10。请向交付人员确认服务器操作系统，或使用与当前系统匹配的介质。"
    fi
  fi
  [[ -d /run/systemd/system ]] || die "$EXIT_OS" "当前系统没有运行 systemd 服务管理器，无法按正式方式安装服务。请在标准的银河麒麟 V10 服务器环境中安装。"
else
  PROGRESS_ON="${MM_PROGRESS_ON:-0}"
  step 1 "未检测到离线介质 manifest，仅执行运行目录准备。"
  PY="$(resolve_python || true)"
fi

if [[ -L "$OPT/current" ]]; then IS_UPGRADE=1; fi

find_data_mount() {
  findmnt -rn -o TARGET,FSTYPE,OPTIONS | while read -r target fs opts; do
    case "$fs" in ext2|ext3|ext4|xfs|btrfs) ;; *) continue ;; esac
    [[ -d "$target" ]] || continue
    [[ "$target" == /boot* ]] && continue
    [[ "$target" == /etc/* || "$target" == /media/* || "$target" == /run/media/* ]] && continue
    grep -qw ro <<<"${opts//,/ }" && continue
    [[ -w "$target" ]] || continue
    avail=$(df -Pk "$target" | awk 'NR==2 {print $4}')
    printf '%s\t%s\n' "$avail" "$target"
  done | sort -nr | head -1 | cut -f2-
}

require_free_mb() {
  # require_free_mb <路径> <需要MB> <说明>；升级时目标盘已有旧版本占用，按“至少 2GB 余量”校验。
  local path="$1" need_mb="$2" label="$3"
  [[ -d "$path" ]] || path="$(dirname "$path")"
  local avail_mb
  avail_mb=$(df -Pk "$path" | awk 'NR==2 {print int($4/1024)}')
  if (( avail_mb < need_mb )); then
    die "$EXIT_DISK" "${label}所在磁盘空间不足：需要至少 ${need_mb} MB 可用空间，当前仅 ${avail_mb} MB。请清理磁盘或选择其它磁盘后重试。"
  fi
}

port_free() {
  if [[ -n "$PY" ]]; then
    "$PY" - "$1" <<'PY'
import socket, sys
port=int(sys.argv[1]); sock=socket.socket()
sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
try: sock.bind(("0.0.0.0",port))
except OSError: raise SystemExit(1)
finally: sock.close()
PY
  else
    (echo >"/dev/tcp/127.0.0.1/$1") >/dev/null 2>&1 && return 1 || return 0
  fi
}

suggest_port() {
  # 从给定端口向后连续探测，结果可预期、可告知用户。
  local start="$1" port
  for offset in $(seq 0 199); do
    port=$((start + offset))
    (( port > 65535 )) && break
    if port_free "$port"; then echo "$port"; return 0; fi
  done
  return 1
}

pick_port() {
  # 升级且未显式指定端口时保持原端口；否则使用默认端口（占用则建议下一个可用端口）。
  if [[ "$IS_UPGRADE" == "1" && -f "$SERVER_ENV" && -z "${MM_PORT_USER_CHOICE:-}" ]]; then
    local current
    current="$(grep -m1 '^MATERIAL_MATCHER_PORT=' "$SERVER_ENV" | cut -d= -f2 || true)"
    if [[ -n "$current" ]]; then echo "$current"; return 0; fi
  fi
  local port="${MM_INSTALL_PORT:-$DEFAULT_PORT}"
  # 本产品旧服务正在监听该端口：升级会先停服再复用同一端口，不算冲突。
  if port_free "$port"; then
    echo "$port"; return 0
  elif systemctl is-active --quiet material_matcher.service 2>/dev/null \
    && grep -qx "MATERIAL_MATCHER_PORT=$port" "$SERVER_ENV" 2>/dev/null; then
    echo "$port"; return 0
  fi
  local next
  next="$(suggest_port "$((port + 1))" || true)"
  if [[ -z "${MM_PORT_AUTO_SWITCH:-}" || -z "$next" ]]; then
    die "$EXIT_PORT" "端口 ${port} 已被其它程序占用。请在安装向导中选择其它端口，或停止占用该端口的程序后重试。"
  fi
  echo "提示：端口 ${port} 已被占用，自动改用 ${next}。" >&2
  echo "$next"
}

activate_link() {
  local link="$1" target="$2" next="${1}.next.$$"
  rm -f "$next"
  ln -s "$target" "$next"
  mv -Tf "$next" "$link"
}

lan_ipv4s() {
  local addrs=""
  addrs="$(hostname -I 2>/dev/null | tr ' ' '\n' | grep -Ev '^$|^127\.' || true)"
  if [[ -z "$addrs" ]] && command -v ip >/dev/null 2>&1; then
    addrs="$(ip -4 -o addr show scope global 2>/dev/null | awk '{print $4}' | cut -d/ -f1 || true)"
  fi
  printf '%s\n' "$addrs" | grep -Ev '^$' || true
}

mkdir -p "$OPT/releases" "$ETC/secret" "$ETC/profiles" "$ETC/catalogs" \
  "$ETC/mappings" "$ETC/dictionaries" "$ETC/templates" "$LOG" "$REPORT_DIR"
chmod 0700 "$ETC/secret"

step 6 "正在检查磁盘空间……"
require_free_mb "$OPT" 2048 "程序目录 $OPT"

# ---- 数据目录（storage.env 是唯一真相，升级绝不换库） -----------------------
if [[ ! -f "$STORAGE_ENV" ]]; then
  if [[ -n "${MM_DATA_DIR:-}" ]]; then
    [[ "$MM_DATA_DIR" == /* ]] || die "$EXIT_GENERIC" "数据目录必须是绝对路径：$MM_DATA_DIR"
    if [[ -e "$VAR" && ! -L "$VAR" ]]; then
      mkdir -p "$MM_DATA_DIR" || true
      cp -a --no-clobber "$VAR/." "$MM_DATA_DIR/" 2>/dev/null || true
      printf 'MATERIAL_MATCHER_DATA_MOUNT=%q\nMATERIAL_MATCHER_DATA_DIR=%q\n' "$(df -P "$MM_DATA_DIR" | awk 'NR==2{print $NF}')" "$MM_DATA_DIR" >"$STORAGE_ENV"
    else
      mkdir -p "$MM_DATA_DIR"
      printf 'MATERIAL_MATCHER_DATA_MOUNT=%q\nMATERIAL_MATCHER_DATA_DIR=%q\n' "$MM_DATA_DIR" "$MM_DATA_DIR" >"$STORAGE_ENV"
    fi
  else
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
  fi
fi

set -a
# shellcheck disable=SC1091
source "$STORAGE_ENV"
set +a
DATA_DIR="${MATERIAL_MATCHER_DATA_DIR:-}"
[[ -n "$DATA_DIR" ]] || die "$EXIT_GENERIC" "配置文件 $STORAGE_ENV 缺少 MATERIAL_MATCHER_DATA_DIR，请联系维护人员确认唯一数据目录。"
[[ "$DATA_DIR" == /* ]] || die "$EXIT_GENERIC" "MATERIAL_MATCHER_DATA_DIR 必须是绝对路径：$DATA_DIR"
mkdir -p "$DATA_DIR" "$VAR"

DATA_REAL="$(readlink -m "$DATA_DIR")"
VAR_REAL="$(readlink -m "$VAR")"
CONFIGURED_DB="$DATA_DIR/meta/material_matcher.db"
LEGACY_DB="$VAR/meta/material_matcher.db"
if [[ "$DATA_REAL" != "$VAR_REAL" ]]; then
  if [[ -f "$LEGACY_DB" && ! -f "$CONFIGURED_DB" ]]; then
    die "$EXIT_DB" "检测到数据目录指向 $DATA_DIR，但旧数据库位于 $LEGACY_DB。为防止登录信息和业务数据“消失”，安装已停止。请联系维护人员确认唯一数据目录后再继续，不要猜测或手工复制。"
  fi
  if [[ -f "$LEGACY_DB" && -f "$CONFIGURED_DB" ]]; then
    die "$EXIT_DB" "同时检测到两份业务数据库（$CONFIGURED_DB 与 $LEGACY_DB）。为避免账号和数据丢失，安装程序拒绝自动选择。请导出诊断包并联系维护人员确认唯一数据目录。"
  fi
fi
step 8 "正在检查数据目录安全……"
require_free_mb "$DATA_DIR" 4096 "数据目录 $DATA_DIR"

mkdir -p "$DATA_DIR/meta" "$DATA_DIR/datasets" "$DATA_DIR/uploads" "$DATA_DIR/results" \
  "$DATA_DIR/indexes" "$DATA_DIR/jobs" "$DATA_DIR/tmp" "$DATA_DIR/cache/embeddings" \
  "$VAR/models/releases"

# ---- 端口 / 会话 / 密码 -----------------------------------------------------
step 10 "正在选择服务端口……"
FINAL_PORT="$(pick_port)"
if [[ ! -f "$SERVER_ENV" ]]; then
  printf 'MATERIAL_MATCHER_HOST=0.0.0.0\nMATERIAL_MATCHER_PORT=%s\nMATERIAL_MATCHER_SESSION_TTL_SECONDS=%s\n' \
    "$FINAL_PORT" "$DEFAULT_SESSION_TTL_SECONDS" >"$SERVER_ENV"
else
  if ! sed -i "s/^MATERIAL_MATCHER_PORT=.*/MATERIAL_MATCHER_PORT=$FINAL_PORT/" "$SERVER_ENV"; then
    printf 'MATERIAL_MATCHER_PORT=%s\n' "$FINAL_PORT" >>"$SERVER_ENV"
  fi
  grep -q '^MATERIAL_MATCHER_HOST=' "$SERVER_ENV" || printf 'MATERIAL_MATCHER_HOST=0.0.0.0\n' >>"$SERVER_ENV"
  grep -q '^MATERIAL_MATCHER_SESSION_TTL_SECONDS=' "$SERVER_ENV" || printf 'MATERIAL_MATCHER_SESSION_TTL_SECONDS=%s\n' "$DEFAULT_SESSION_TTL_SECONDS" >>"$SERVER_ENV"
fi

PASSWORD_SOURCE=""
if [[ -f "$PASSWORD_FILE" ]]; then
  PASSWORD_SOURCE="existing"
elif [[ -n "${MM_ADMIN_PASSWORD:-}" ]]; then
  printf 'MATERIAL_MATCHER_ADMIN_PASSWORD=%s\n' "$MM_ADMIN_PASSWORD" >"$PASSWORD_FILE"
  PASSWORD_SOURCE="${MM_ADMIN_PASSWORD_SOURCE:-user}"
elif [[ -n "${MM_ADMIN_PASSWORD_FILE:-}" && -s "${MM_ADMIN_PASSWORD_FILE:-}" ]]; then
  cp -f "$MM_ADMIN_PASSWORD_FILE" /tmp/mm_admin_pw.$$
  printf 'MATERIAL_MATCHER_ADMIN_PASSWORD=%s\n' "$(cat /tmp/mm_admin_pw.$$)" >"$PASSWORD_FILE"
  rm -f /tmp/mm_admin_pw.$$
  PASSWORD_SOURCE="file"
else
  if [[ -n "$PY" ]]; then
    password=$("$PY" - <<'PY'
import secrets, string
alphabet=string.ascii_letters+string.digits
print(''.join(secrets.choice(alphabet) for _ in range(12)))
PY
)
  else
    password="$(tr -dc 'A-Za-z0-9' </dev/urandom | head -c 12)"
  fi
  printf 'MATERIAL_MATCHER_ADMIN_PASSWORD=%s\n' "$password" >"$PASSWORD_FILE"
  PASSWORD_SOURCE="generated"
fi
chown root:root "$PASSWORD_FILE"
chmod 0600 "$PASSWORD_FILE"
MM_ADMIN_PASSWORD=""
export MM_ADMIN_PASSWORD

# ---- 服务用户 ---------------------------------------------------------------
step 12 "正在创建系统服务账号……"
if ! id "$APP_USER" >/dev/null 2>&1; then
  if command -v useradd >/dev/null 2>&1; then
    useradd --system --home "$DATA_DIR" --shell /usr/sbin/nologin "$APP_USER"
  elif command -v adduser >/dev/null 2>&1; then
    adduser --system --home "$DATA_DIR" --shell /usr/sbin/nologin "$APP_USER"
  else
    die "$EXIT_OS" "当前系统没有 useradd/adduser，无法创建服务账号，请联系系统管理员。"
  fi
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
BOOTSTRAP_DEST="$OPT/bootstrap"

if [[ -n "$BUNDLE_ROOT" ]]; then
  RELEASE_DEST="$OPT/releases/$RELEASE_VERSION"
  if [[ -d "$RELEASE_DEST" ]]; then
    [[ -f "$RELEASE_DEST/.bundle_manifest_sha256" ]] || die "$EXIT_MEDIA" "相同版本 $RELEASE_VERSION 的发布目录已存在，但无法确认它是否来自同一介质。为避免覆盖不同内容，安装已停止。"
    [[ "$(cat "$RELEASE_DEST/.bundle_manifest_sha256")" == "$MANIFEST_SHA" ]] || die "$EXIT_MEDIA" "相同版本号 $RELEASE_VERSION 已存在不同内容。禁止同版本号覆盖安装，请提升 release 版本后重新制作介质。"
    step 24 "检测到相同版本已安装，正在复用现有发布目录……"
  else
    RELEASE_STAGE="$OPT/releases/.staging-${RELEASE_VERSION}-$$"
    rm -rf "$RELEASE_STAGE"; mkdir -p "$RELEASE_STAGE"
    step 18 "正在复制程序文件（约 300 MB，视磁盘速度约需 1～2 分钟）……"
    cp -a "$BUNDLE_ROOT/release/." "$RELEASE_STAGE/"
    printf '%s\n' "$MANIFEST_SHA" >"$RELEASE_STAGE/.bundle_manifest_sha256"
    mv "$RELEASE_STAGE" "$RELEASE_DEST"
  fi

  MODEL_RELEASE_ROOT="$VAR/models/releases/$RELEASE_VERSION"
  if [[ -d "$MODEL_RELEASE_ROOT" ]]; then
    [[ -f "$MODEL_RELEASE_ROOT/.bundle_manifest_sha256" ]] || die "$EXIT_MEDIA" "相同版本的模型目录已存在，但无法确认来源：$MODEL_RELEASE_ROOT"
    [[ "$(cat "$MODEL_RELEASE_ROOT/.bundle_manifest_sha256")" == "$MANIFEST_SHA" ]] || die "$EXIT_MEDIA" "相同版本的模型内容与当前介质不一致，禁止混用。"
    step 44 "检测到相同版本模型已安装，正在复用……"
  else
    MODEL_STAGE="$VAR/models/releases/.staging-${RELEASE_VERSION}-$$"
    rm -rf "$MODEL_STAGE"; mkdir -p "$MODEL_STAGE/$(dirname "$MODEL_ID")"
    step 40 "正在安装 AI 模型文件（约 400 MB，请耐心等待）……"
    cp -a "$BUNDLE_ROOT/models/$MODEL_ID" "$MODEL_STAGE/$MODEL_ID"
    printf '%s\n' "$MANIFEST_SHA" >"$MODEL_STAGE/.bundle_manifest_sha256"
    mv "$MODEL_STAGE" "$MODEL_RELEASE_ROOT"
    MODEL_COPIED=1
  fi

  [[ -x "$RELEASE_DEST/$RUNTIME_DIR_NAME/bin/python3" ]] || die "$EXIT_MEDIA" "自包含 Python 运行环境不完整（缺少可执行 runtime/bin/python3），请重新复制安装介质。"
  [[ -x "$RELEASE_DEST/$RUNTIME_DIR_NAME/bin/material-matcher" ]] || die "$EXIT_MEDIA" "自包含 Python 运行环境不完整（缺少 material-matcher 启动器），请重新复制安装介质。"
  [[ -f "$RELEASE_DEST/web/dist/index.html" ]] || die "$EXIT_MEDIA" "安装介质缺少前端页面发布产物，请重新复制安装介质。"
  [[ -f "$RELEASE_DEST/release-manifest.json" ]] || die "$EXIT_MEDIA" "安装介质缺少 release manifest，请重新复制安装介质。"

  # 安装器 bootstrap runtime 落到程序目录，供维护工具在无系统 Python 时使用。
  if [[ -x "$BUNDLE_ROOT/bootstrap/python/bin/python3" ]]; then
    step 44 "正在安装维护工具运行环境……"
    if [[ ! -x "$BOOTSTRAP_DEST/python/bin/python3" ]]; then
      mkdir -p "$BOOTSTRAP_DEST"
      cp -a "$BUNDLE_ROOT/bootstrap" "$BOOTSTRAP_DEST/python.tmp" 2>/dev/null || true
      rm -rf "$BOOTSTRAP_DEST/python"
      mv "$BOOTSTRAP_DEST/python.tmp" "$BOOTSTRAP_DEST/python" 2>/dev/null || true
    fi
  fi

  # 维护工具入口。
  step 45 "正在安装维护工具……"
  mkdir -p "$OPT/bin"
  [[ -f "$BUNDLE_ROOT/mmctl" ]] && cp -f "$BUNDLE_ROOT/mmctl" "$OPT/bin/mmctl"
  [[ -f "$BUNDLE_ROOT/docs/维护手册.md" ]] && mkdir -p "$OPT/docs" && cp -f "$BUNDLE_ROOT/docs/维护手册.md" "$OPT/docs/维护手册.md"
  chmod 0755 "$OPT/bin/mmctl" 2>/dev/null || true
  ln -sfn "$OPT/bin/mmctl" /usr/local/bin/mmctl 2>/dev/null || true

  # 可选：离线前端重建资源（Node 运行时 + node_modules 归档）。
  if [[ -z "$NODE_OFFLINE_DIR" && -d "$BUNDLE_ROOT/tools/node-offline" ]]; then
    NODE_OFFLINE_DIR="$BUNDLE_ROOT/tools/node-offline"
  fi
  if [[ -n "$NODE_OFFLINE_DIR" && -d "$NODE_OFFLINE_DIR" ]]; then
    mkdir -p "$OPT/tools"
    if [[ ! -d "$OPT/tools/node-offline" ]]; then
      step 46 "正在安装前端离线重建资源（体积较大，仅需一次）……"
      cp -a "$NODE_OFFLINE_DIR" "$OPT/tools/node-offline.tmp" 2>/dev/null || true
      rm -rf "$OPT/tools/node-offline"
      mv "$OPT/tools/node-offline.tmp" "$OPT/tools/node-offline" 2>/dev/null || true
    fi
    printf '%s\n' "$OPT/tools/node-offline" > "$OPT/tools/node-offline.path"
  fi
fi

step 48 "正在设置目录权限……"
# 不递归扫描已有海量索引/结果；固定目录只调整目录本身，新模型只处理本次版本。
chown "$APP_USER:$APP_USER" "$DATA_DIR" "$VAR" "$LOG"
for path in "$DATA_DIR/meta" "$DATA_DIR/datasets" "$DATA_DIR/uploads" "$DATA_DIR/results" "$DATA_DIR/indexes" "$DATA_DIR/jobs" "$DATA_DIR/tmp" "$DATA_DIR/cache" "$DATA_DIR/cache/embeddings"; do
  chown "$APP_USER:$APP_USER" "$path"
done
for path in "$VAR/models" "$VAR/models/releases"; do
  chown "$APP_USER:$APP_USER" "$path"
done
if [[ "$MODEL_COPIED" == "1" ]]; then chown -R "$APP_USER:$APP_USER" "$MODEL_RELEASE_ROOT"; fi

if [[ -n "$BUNDLE_ROOT" ]]; then
  step 55 "正在执行环境诊断（doctor：检查运行环境、模型与前端，最长约 1 分钟）……"
  DOCTOR_ENV=(
    "MATERIAL_MATCHER_DATA_DIR=$DATA_DIR"
    "MATERIAL_MATCHER_CONFIG_DIR=$ETC"
    "MATERIAL_MATCHER_LOG_DIR=$LOG"
    "MATERIAL_MATCHER_MODEL_ROOT=$MODEL_RELEASE_ROOT"
    "MATERIAL_MATCHER_WEB_DIST_DIR=$RELEASE_DEST/web/dist"
  )
  doctor_ok=0
  for _ in 1 2; do
    if command -v runuser >/dev/null 2>&1; then
      runuser -u "$APP_USER" -- env "${DOCTOR_ENV[@]}" "$RELEASE_DEST/$RUNTIME_DIR_NAME/bin/material-matcher" doctor \
        --require-frontend --require-embedding --require-release-manifest >/dev/null && { doctor_ok=1; break; }
    else
      env "${DOCTOR_ENV[@]}" "$RELEASE_DEST/$RUNTIME_DIR_NAME/bin/material-matcher" doctor \
        --require-frontend --require-embedding --require-release-manifest >/dev/null && { doctor_ok=1; break; }
    fi
    sleep 2
  done
  (( doctor_ok == 1 )) || die "$EXIT_DOCTOR" "新版本部署前诊断失败：安装介质中的运行环境、AI 模型或前端存在不完整项，系统未做任何改动，旧版本保持不变。请导出诊断包并联系原厂。"
fi

step 60 "正在配置系统服务（systemd）……"
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
ExecStart=$OPT/current/$RUNTIME_DIR_NAME/bin/material-matcher serve --host \${MATERIAL_MATCHER_HOST} --port \${MATERIAL_MATCHER_PORT}
Restart=on-failure
RestartSec=3

[Install]
WantedBy=multi-user.target
EOF

rollback_activation() {
  echo "新版本启动失败，正在回滚到安装前状态……" >&2
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
  if [[ "$SERVICE_WAS_ACTIVE" == "1" && -n "$OLD_RELEASE" && -x "$OLD_RELEASE/$RUNTIME_DIR_NAME/bin/material-matcher" ]]; then
    systemctl start material_matcher.service >/dev/null 2>&1 || true
  fi
}

if [[ -n "$BUNDLE_ROOT" ]]; then
  # 从这里开始才进入短暂停机窗口。
  if [[ "$SERVICE_WAS_ACTIVE" == "1" ]]; then
    systemctl stop material_matcher.service || die "$EXIT_START" "无法停止旧版本服务，安装已停止，未执行版本切换，旧系统仍可正常使用。"
  fi
  if [[ -n "$OLD_RELEASE" && "$OLD_RELEASE" != "$RELEASE_DEST" ]]; then activate_link "$OPT/previous" "$OLD_RELEASE"; fi
  if [[ -n "$OLD_MODEL_ROOT" && "$OLD_MODEL_ROOT" != "$MODEL_RELEASE_ROOT" ]]; then activate_link "$VAR/models/previous" "$OLD_MODEL_ROOT"; fi
  activate_link "$VAR/models/current" "$MODEL_RELEASE_ROOT"
  activate_link "$OPT/current" "$RELEASE_DEST"
fi

step 66 "正在启动服务并等待就绪（最长约 2 分钟）……"
systemctl daemon-reload
if [[ -x "$OPT/current/$RUNTIME_DIR_NAME/bin/material-matcher" ]]; then
  if ! systemctl enable material_matcher.service; then
    [[ -n "$BUNDLE_ROOT" ]] && rollback_activation
    die "$EXIT_START" "systemd 服务启用失败。新版本已回滚到安装前状态，旧系统不受影响。请导出诊断包并联系维护人员。"
  fi
  # 旧版 systemd(如 SLES12 的 228)会把与 stop 任务并发的 start 任务取消,
  # 因此先等停止任务彻底落定,再显式 start,而不是依赖 enable --now。
  for _ in $(seq 1 60); do
    [[ "$(systemctl is-active material_matcher.service 2>/dev/null || true)" == "inactive" ]] && break
    sleep 1
  done
  if ! systemctl start material_matcher.service; then
    [[ -n "$BUNDLE_ROOT" ]] && rollback_activation
    die "$EXIT_START" "服务启动失败。新版本已自动回滚到安装前状态，旧系统仍可正常使用。请导出诊断包并联系维护人员。"
  fi
  set -a; source "$SERVER_ENV"; set +a
  if ! "$PY" - "${MATERIAL_MATCHER_PORT}" <<'PY'
import json, sys, time, urllib.request
port=int(sys.argv[1]); last=None
for i in range(120):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health/ready",timeout=2) as response:
            payload=json.load(response)
        if payload.get("status")=="ready": raise SystemExit(0)
        last=payload
    except Exception as exc:
        last=str(exc)
    if i and i % 15 == 0:
        print(f"[78%] 服务正在完成初始化，已等待 {i} 秒……", flush=True)
    time.sleep(1)
print(f"readiness 未通过: {last}",file=sys.stderr)
raise SystemExit(1)
PY
  then
    [[ -n "$BUNDLE_ROOT" ]] && rollback_activation
    die "$EXIT_READY" "服务已启动，但健康检查未在 2 分钟内就绪。新版本已自动回滚，旧系统状态见诊断包。请导出诊断包并联系维护人员。"
  fi
fi

# ---- 成功汇总与安装报告 ------------------------------------------------------
step 96 "正在生成安装报告……"
set -a; source "$SERVER_ENV"; set +a; DATA_DIR="${MATERIAL_MATCHER_DATA_DIR:-$DATA_DIR}"
MAP_ADDRESSES="$(lan_ipv4s)"
FIREWALL_HINT=""
if command -v firewall-cmd >/dev/null 2>&1 && firewall-cmd --state >/dev/null 2>&1; then
  FIREWALL_HINT="检测到 firewalld 正在运行：如局域网其它电脑无法访问，请由网络管理员放行端口 ${MATERIAL_MATCHER_PORT}（本产品安装程序不会自动修改防火墙规则）。"
fi
MODE_TEXT="首次安装"
[[ "$IS_UPGRADE" == "1" ]] && MODE_TEXT="升级安装"
REPORT_FILE="$REPORT_DIR/install-$(date +%Y%m%d-%H%M%S).txt"
{
  echo "物料集团码智能匹配平台 安装报告"
  echo "===================================="
  echo "模式：$MODE_TEXT"
  echo "版本：${RELEASE_VERSION:-未安装发布}"
  echo "Git commit：$GIT_COMMIT"
  echo "安装时间：$(date '+%F %T')"
  echo "程序目录：$OPT"
  echo "配置目录：$ETC"
  echo "数据目录：$DATA_DIR"
  echo "日志目录：$LOG"
  echo "服务端口：${MATERIAL_MATCHER_PORT}"
  echo "服务状态：$(systemctl is-active material_matcher.service 2>/dev/null || true)"
  echo "开机自启：$(systemctl is-enabled material_matcher.service 2>/dev/null || true)"
  echo "本机访问：http://127.0.0.1:${MATERIAL_MATCHER_PORT}"
  for addr in $MAP_ADDRESSES; do echo "局域网访问：http://${addr}:${MATERIAL_MATCHER_PORT}"; done
  [[ -n "$FIREWALL_HINT" ]] && echo "防火墙提示：$FIREWALL_HINT"
  echo "管理员账号：admin"
  echo "管理员密码：（出于安全，本报告不包含明文密码；见 $PASSWORD_FILE 或安装完成界面）"
} >"$REPORT_FILE"
chmod 0600 "$REPORT_FILE"

step 100 "安装完成。"
if [[ -z "$PY" ]]; then PY="$(resolve_python || true)"; fi
if [[ -n "$PY" ]]; then
  SUMMARY_JSON="$(
    MM_MODE="$MODE_TEXT" MM_VERSION="${RELEASE_VERSION:-}" MM_COMMIT="$GIT_COMMIT" \
    MM_PORT="${MATERIAL_MATCHER_PORT:-0}" MM_DATA_DIR="$DATA_DIR" MM_LOG_DIR="$LOG" \
    MM_PW_SOURCE="$PASSWORD_SOURCE" MM_PW_FILE="$PASSWORD_FILE" MM_ADDRS="$MAP_ADDRESSES" \
    MM_ACTIVE="$(systemctl is-active material_matcher.service 2>/dev/null || true)" \
    MM_ENABLED="$(systemctl is-enabled material_matcher.service 2>/dev/null || true)" \
    MM_FIREWALL="$FIREWALL_HINT" MM_REPORT="$REPORT_FILE" \
    "$PY" - <<'PY'
import json, os
e = os.environ
print(json.dumps({
    "ok": True,
    "mode": e["MM_MODE"],
    "version": e["MM_VERSION"],
    "git_commit": e["MM_COMMIT"],
    "port": int(e["MM_PORT"] or 0),
    "data_dir": e["MM_DATA_DIR"],
    "log_dir": e["MM_LOG_DIR"],
    "password_source": e["MM_PW_SOURCE"],
    "password_file": e["MM_PW_FILE"],
    "addresses": [a for a in e["MM_ADDRS"].split() if a],
    "service_active": e["MM_ACTIVE"],
    "service_enabled": e["MM_ENABLED"],
    "firewall_hint": e["MM_FIREWALL"],
    "report_file": e["MM_REPORT"],
}, ensure_ascii=False))
PY
  )"
else
  SUMMARY_JSON="{\"ok\": true, \"mode\": \"$MODE_TEXT\", \"version\": \"${RELEASE_VERSION:-}\", \"port\": ${MATERIAL_MATCHER_PORT:-0}}"
fi
echo "@@RESULT@@|$SUMMARY_JSON"
[[ -n "$RELEASE_VERSION" ]] && echo "MATERIAL_MATCHER ${MODE_TEXT}完成：版本 $RELEASE_VERSION，端口 ${MATERIAL_MATCHER_PORT}。"
for addr in $MAP_ADDRESSES; do echo "局域网访问地址：http://${addr}:${MATERIAL_MATCHER_PORT}"; done
echo "管理员账号：admin；初始密码文件：$PASSWORD_FILE（root 可读，安装完成界面会显示密码或获取方式）"
echo "安装报告：$REPORT_FILE"
