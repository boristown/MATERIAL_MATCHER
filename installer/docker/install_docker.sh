#!/usr/bin/env bash
# MATERIAL_MATCHER Docker 方式离线安装脚本（非交互核心，由 docker 向导调用）。
# 介质结构（01-Docker方式/）：
#   docker/engine/docker-<ver>.tgz  docker/compose/docker-compose-linux-x86_64
#   images/material-matcher-<ver>.tar  compose/compose.yaml  seed/business  smoke  bootstrap
# 进度协议：@@STEP@@|pct|text；结束 @@RESULT@@|json（不含密码）。退出码与 Native 一致。
set -uo pipefail

APP="material_matcher"
PROJECT="material_matcher"
CONTAINER="material_matcher-app"
NETWORK="material_matcher-net"
CONTAINER_PORT=18080
OPT="/opt/material_matcher"
ETC="/etc/material_matcher"
VAR="/var/lib/material_matcher"
LOG="/var/log/material_matcher"
PASSWORD_FILE="$ETC/secret/admin_password.env"
DOCKER_ENV="$ETC/docker.env"
COMPOSE_HOME="$OPT/docker"
REPORT_DIR="$LOG/install-reports"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MEDIA="${MATERIAL_MATCHER_DOCKER_MEDIA:-$SCRIPT_DIR}"
DEFAULT_PORT="${MM_INSTALL_PORT:-18080}"
MIN_DOCKER_MAJOR=20

EXIT_GENERIC=1
EXIT_PORT=40
EXIT_MEDIA=41
EXIT_DISK=42
EXIT_OS=43
EXIT_PRIV=44
EXIT_DB=45
EXIT_DOCKER=46
EXIT_START=47
EXIT_READY=48
EXIT_SEED=49
EXIT_INCOMPATIBLE_DOCKER=50

PROGRESS_ON="${MM_PROGRESS_ON:-1}"
step() {
  if [[ "$PROGRESS_ON" == "1" ]]; then echo "@@STEP@@|${1}|${2}"; fi
  echo "[$1%] $2"
}
die() { echo "安装失败：$2" >&2; exit "$1"; }

[[ $EUID -eq 0 ]] || die "$EXIT_PRIV" "当前账号没有系统管理员权限，无法安装服务。请使用 root 或通过 sudo 重新运行安装程序。"
[[ -f "$MEDIA/docker-manifest.json" ]] || die "$EXIT_MEDIA" "Docker 安装介质缺少 docker-manifest.json，请把 01-Docker方式 目录完整复制到服务器本地磁盘后再运行。"
[[ -f "$MEDIA/verify_docker_bundle.py" ]] || die "$EXIT_MEDIA" "Docker 安装介质缺少校验脚本，请重新复制完整介质。"

# 解释器：bootstrap → 系统兜底
resolve_python() {
  local c
  for c in "$MEDIA/bootstrap/python/bin/python3" "$(command -v python3 2>/dev/null || true)"; do
    [[ -n "$c" && -x "$c" ]] || continue
    "$c" -c 'import json,hashlib,socket' >/dev/null 2>&1 && { echo "$c"; return 0; }
  done
  return 1
}
PY="$(resolve_python || true)"
[[ -n "$PY" ]] || die "$EXIT_MEDIA" "安装介质缺少 bootstrap 运行环境，且本机没有可用 Python。请重新复制完整介质。"

step 3 "正在校验 Docker 安装介质完整性……"
"$PY" "$MEDIA/verify_docker_bundle.py" "$MEDIA" >> /var/tmp/material_matcher_docker_verify.log 2>&1 \
  || { echo "校验明细：/var/tmp/material_matcher_docker_verify.log" >&2; die "$EXIT_MEDIA" "Docker 安装介质校验失败：文件可能被修改、缺失或架构不匹配。请重新复制完整介质，不要继续使用当前介质。"; }

read -r RELEASE_VERSION IMAGE_REF IMAGE_TAR_REL < <("$PY" - "$MEDIA/docker-manifest.json" <<'PY'
import json, sys
m = json.load(open(sys.argv[1], encoding="utf-8"))
print(m["release_version"], m["image_ref"], m["image_tar"])
PY
)

step 5 "正在检查操作系统与架构……"
if [[ "${MATERIAL_MATCHER_ALLOW_UNSUPPORTED_OS:-0}" != "1" ]]; then
  grep -Eqi 'kylin|银河麒麟' /etc/os-release 2>/dev/null || die "$EXIT_OS" "当前安装包只支持银河麒麟 Linux V10。"
fi
[[ -d /run/systemd/system ]] || die "$EXIT_OS" "当前环境未运行 systemd，无法按正式方式管理 Docker 服务。"
ARCH_NOW="$(uname -m)"
ARCH_MEDIA="$("$PY" -c "import json;print(json.load(open('$MEDIA/docker-manifest.json',encoding='utf-8'))['target_arch'])")"
[[ "$ARCH_NOW" == "$ARCH_MEDIA" ]] || die "$EXIT_OS" "安装介质架构（$ARCH_MEDIA）与服务器 CPU（$ARCH_NOW）不一致，请更换匹配介质。"

require_free_mb() {  # <路径> <需要MB> <说明>；路径不存在时按最近存在父目录计算
  local path="$1" need_mb="$2" label="$3" probe="$1" avail_mb
  while [[ ! -e "$probe" ]]; do probe="$(dirname "$probe")"; done
  avail_mb=$(df -Pk "$probe" | awk 'NR==2 {print int($4/1024)}')
  [[ -n "$avail_mb" ]] || { echo "警告：无法读取 ${probe} 磁盘信息，跳过该项空间预检。" >&2; return 0; }
  (( avail_mb >= need_mb )) || die "$EXIT_DISK" "磁盘空间不足：${label} 需要至少 ${need_mb} MB 可用空间，当前 ${avail_mb} MB。请清理磁盘后重试。"
}
require_free_mb / 6144 "根分区（系统组件与镜像）"
require_free_mb "$OPT" 2048 "程序目录 $OPT"

# ---- Docker Engine 检测 / 离线安装 ------------------------------------------------
DOCKER_STATE=""
ensure_docker_engine() {
  if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
    local major
    major="$(docker version --format '{{.Server.Version}}' 2>/dev/null | cut -d. -f1)"
    [[ -n "$major" && "$major" -ge "$MIN_DOCKER_MAJOR" ]] 2>/dev/null || major=0
    if (( major < MIN_DOCKER_MAJOR )); then
      die "$EXIT_INCOMPATIBLE_DOCKER" "服务器已有 Docker（版本 $(docker version --format '{{.Server.Version}}' 2>/dev/null)）低于本系统要求的 ${MIN_DOCKER_MAJOR}+。安装器不会静默替换客户 Docker，请联系管理员确认升级 Docker 后重试。"
    fi
    step 10 "检测到可用 Docker（服务器版本 $(docker version --format '{{.Server.Version}}' 2>/dev/null)），直接复用，不做任何改动……"
    DOCKER_STATE="reused"
    return 0
  fi
  if command -v docker >/dev/null 2>&1; then
    die "$EXIT_DOCKER" "服务器存在 docker 命令但 Docker 守护进程未运行且无法连接。请先由系统管理员启动现有 Docker（systemctl start docker），或确认无 Docker 残留后重试。安装器不会覆盖客户已有 Docker 安装。"
  fi
  step 8 "正在从安装介质离线安装 Docker Engine（docker-27.1.1 官方静态组件，无需联网）……"
  local engine_tgz="$MEDIA/docker/engine/docker-27.1.1.tgz"
  tar -xzf "$engine_tgz" -C /tmp || die "$EXIT_MEDIA" "Docker Engine 组件解压失败，介质可能损坏。"
  install -m 0755 /tmp/docker/* /usr/local/bin/ || die "$EXIT_DOCKER" "Docker 组件安装到 /usr/local/bin 失败，请检查磁盘与权限。"
  rm -rf /tmp/docker
  mkdir -p /etc/docker
  if [[ ! -f /etc/docker/daemon.json ]]; then
    if [[ -n "${MM_DATA_MOUNT:-}" && -d "${MM_DATA_MOUNT:-}" ]]; then
      mkdir -p "$MM_DATA_MOUNT/docker-data"
      printf '{\n  "data-root": "%s/docker-data",\n  "log-driver": "json-file",\n  "log-opts": {"max-size": "20m", "max-file": "3"}\n}\n' "$MM_DATA_MOUNT" > /etc/docker/daemon.json
    else
      printf '{\n  "log-driver": "json-file",\n  "log-opts": {"max-size": "20m", "max-file": "3"}\n}\n' > /etc/docker/daemon.json
    fi
  fi
  cat >/etc/systemd/system/containerd.service <<'EOF'
[Unit]
Description=containerd container runtime
After=network.target

[Service]
ExecStart=/usr/local/bin/containerd
Restart=always
OOMScoreAdjust=-999

[Install]
WantedBy=multi-user.target
EOF
  cat >/etc/systemd/system/docker.socket <<'EOF'
[Unit]
Description=Docker Socket for the API

[Socket]
ListenStream=/run/docker.sock
SocketMode=0660
SocketUser=root

[Install]
WantedBy=sockets.target
EOF
  cat >/etc/systemd/system/docker.service <<'EOF'
[Unit]
Description=Docker Application Container Engine
After=network-online.target docker.socket containerd.service
Requires=docker.socket containerd.service

[Service]
ExecStart=/usr/local/bin/dockerd -H fd:// --containerd=/run/containerd/containerd.sock
Restart=always
LimitNOFILE=1048576

[Install]
WantedBy=multi-user.target
EOF
  systemctl daemon-reload
  systemctl enable --now containerd docker >/dev/null 2>&1 || systemctl start containerd docker >/dev/null 2>&1 || true
  for _ in $(seq 1 60); do docker info >/dev/null 2>&1 && break; sleep 1; done
  docker info >/dev/null 2>&1 || die "$EXIT_DOCKER" "Docker 守护进程安装后未能启动（可能受 SELinux/Kylin 安全加固限制）。安装日志已保留，请导出诊断包并联系维护人员；本安装器不会改动其它系统服务。"
  DOCKER_STATE="installed"
}

ensure_compose() {
  if docker compose version >/dev/null 2>&1; then
    step 14 "已存在 Docker Compose v2，直接复用……"
    return 0
  fi
  step 14 "正在离线安装 Docker Compose v2 插件……"
  mkdir -p /usr/local/lib/docker/cli-plugins
  install -m 0755 "$MEDIA/docker/compose/docker-compose-linux-x86_64" /usr/local/lib/docker/cli-plugins/docker-compose \
    || die "$EXIT_DOCKER" "Compose 插件安装失败。"
  docker compose version >/dev/null 2>&1 || die "$EXIT_DOCKER" "Compose 安装后不可用，请导出诊断包联系维护人员。"
}

step 6 "正在检查 Docker 环境……"
ensure_docker_engine
ensure_compose

# ---- 端口 / 存储目录 / 密码 --------------------------------------------------------
port_free() {
  "$PY" - "$1" <<'PY'
import socket, sys
port = int(sys.argv[1]); s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
try: s.bind(("0.0.0.0", port))
except OSError: raise SystemExit(1)
finally: s.close()
PY
}
IS_UPGRADE=0
[[ -f "$DOCKER_ENV" ]] && IS_UPGRADE=1
FINAL_PORT="$DEFAULT_PORT"
if [[ "$IS_UPGRADE" == "1" && -z "${MM_PORT_USER_CHOICE:-}" ]]; then
  FINAL_PORT="$(grep -m1 '^MM_HOST_PORT=' "$DOCKER_ENV" | cut -d= -f2)"
fi
if ! port_free "$FINAL_PORT"; then
  if [[ "$IS_UPGRADE" == "1" ]] && docker ps --format '{{.Names}}' 2>/dev/null | grep -qx "$CONTAINER" \
    && grep -qx "MM_HOST_PORT=$FINAL_PORT" "$DOCKER_ENV" 2>/dev/null; then
    : # 占用者是本产品旧容器：升级会先停容器，属正常
  else
    die "$EXIT_PORT" "端口 ${FINAL_PORT} 已被其它程序占用。请在向导中选择其它端口后重试。"
  fi
fi

STORAGE_ENV="$ETC/storage.env"
mkdir -p "$OPT" "$ETC/secret" "$ETC/profiles" "$LOG" "$REPORT_DIR" "$COMPOSE_HOME" "$VAR"
chmod 0700 "$ETC/secret"
if [[ ! -f "$STORAGE_ENV" ]]; then
  printf 'MATERIAL_MATCHER_DATA_MOUNT=%q\nMATERIAL_MATCHER_DATA_DIR=%q\n' "$VAR" "$VAR" >"$STORAGE_ENV"
fi
DATA_DIR="$(grep -m1 '^MATERIAL_MATCHER_DATA_DIR=' "$STORAGE_ENV" | cut -d= -f2 | tr -d '"')"
[[ "$DATA_DIR" == "$VAR" ]] || die "$EXIT_DB" "Docker 方式要求数据目录为 /var/lib/material_matcher（storage.env 当前指向 $DATA_DIR）。两种方式不能混用在同一数据目录，请先由维护人员确认，不自动迁移。"

DATA_MOUNT_RESOLVED=""
apply_data_mount() {  # 全新安装时把 lib/log 数据目录放到选定磁盘（已有数据绝不迁移）
  [[ -n "${MM_DATA_MOUNT:-}" && -d "${MM_DATA_MOUNT:-}" ]] || return 0
  local base="$MM_DATA_MOUNT/material_matcher_data"
  mkdir -p "$base/lib" "$base/log" 2>/dev/null || { echo "提示：$MM_DATA_MOUNT 不可写，使用默认位置。" >&2; return 0; }
  local pair link target
  for pair in "$VAR:$base/lib" "$LOG:$base/log"; do
    link="${pair%%:*}"; target="${pair##*:}"
    if [[ ! -e "$link" ]]; then
      ln -sfn "$target" "$link"
    elif [[ -d "$link" && -z "$(ls -A "$link" 2>/dev/null)" ]]; then
      rmdir "$link" 2>/dev/null && ln -sfn "$target" "$link"
    fi
    [[ "$(readlink -f "$link")" != "$(readlink -f "$target")" ]] && echo "提示：$link 已有既有数据，保持原位（不自动迁移）。" >&2
  done
  DATA_MOUNT_RESOLVED="$base"
}
apply_data_mount
mkdir -p "$VAR/meta" "$VAR/uploads" "$VAR/datasets" "$VAR/results" "$VAR/indexes" "$VAR/jobs" "$VAR/tmp" "$VAR/cache/embeddings"
[[ -s "$VAR/meta/material_matcher.db" ]] || true

if [[ ! -f "$PASSWORD_FILE" ]]; then
  if [[ -n "${MM_ADMIN_PASSWORD:-}" ]]; then
    printf 'MATERIAL_MATCHER_ADMIN_PASSWORD=%s\n' "$MM_ADMIN_PASSWORD" >"$PASSWORD_FILE"
    PASSWORD_SOURCE="${MM_ADMIN_PASSWORD_SOURCE:-user}"
  else
    PASSWORD_SOURCE=generated
    "$PY" - >"$PASSWORD_FILE" <<'PY'
import secrets, string
letters, digits = string.ascii_letters, string.digits
pool = [secrets.choice(letters), *map(lambda _: secrets.choice(letters + digits), range(10)), secrets.choice(digits)]
secrets.SystemRandom().shuffle(pool)
print("MATERIAL_MATCHER_ADMIN_PASSWORD=" + "".join(pool))
PY
  fi
else
  PASSWORD_SOURCE="existing"
fi
chmod 0600 "$PASSWORD_FILE"; chown root:root "$PASSWORD_FILE"
MM_ADMIN_PASSWORD=""

# ---- 镜像导入（含旧版本保留用于回滚） ------------------------------------------------
step 20 "正在导入应用镜像（约 1.5 GB，docker load 可能需要 1～3 分钟，请耐心等待）……"
PREV_IMAGE=""
if [[ -f "$DOCKER_ENV" ]]; then PREV_IMAGE="$(grep -m1 '^MM_IMAGE=' "$DOCKER_ENV" | cut -d= -f2 || true)"; fi
LOADED="$("$(command -v docker)" load -i "$MEDIA/$IMAGE_TAR_REL" 2>&1 | tail -1)" || die "$EXIT_MEDIA" "镜像导入失败：$LOADED"
docker image inspect "$IMAGE_REF" >/dev/null 2>&1 || die "$EXIT_MEDIA" "镜像包中未找到预期标签 $IMAGE_REF。"
if [[ -n "$PREV_IMAGE" && "$PREV_IMAGE" != "$IMAGE_REF" ]]; then
  docker image inspect "$PREV_IMAGE" >/dev/null 2>&1 && docker tag "$PREV_IMAGE" "material-matcher-app:previous" || true
fi

# ---- compose 配置与持久目录 ---------------------------------------------------------
step 55 "正在生成 Compose 配置与宿主机持久目录……"
cat >"$DOCKER_ENV" <<EOF
MM_IMAGE=$IMAGE_REF
MM_HOST_PORT=$FINAL_PORT
MM_DATA_DIR=$VAR
MM_CONFIG_DIR=$ETC
MM_LOG_DIR=$LOG
MM_COMPOSE_HOME=$COMPOSE_HOME
EOF
mkdir -p "$VAR/docker-persist-meta" 
cat >"$COMPOSE_HOME/compose.yaml" <<EOF
name: $PROJECT
networks:
  $NETWORK:
    name: $NETWORK
services:
  app:
    image: $IMAGE_REF
    container_name: $CONTAINER
    restart: unless-stopped
    networks: [$NETWORK]
    env_file:
      - $ETC/secret/admin_password.env
    ports:
      - "0.0.0.0:$FINAL_PORT:18080"
    volumes:
      - $ETC:/etc/material_matcher
      - $VAR:/var/lib/material_matcher
      - $LOG:/var/log/material_matcher
    environment:
      MATERIAL_MATCHER_DATA_DIR: /var/lib/material_matcher
      MATERIAL_MATCHER_CONFIG_DIR: /etc/material_matcher
      MATERIAL_MATCHER_LOG_DIR: /var/log/material_matcher
      MATERIAL_MATCHER_MODEL_ROOT: /opt/material_matcher/model
      MATERIAL_MATCHER_WEB_DIST_DIR: /opt/material_matcher/current/web/dist
      MATERIAL_MATCHER_HOST: 0.0.0.0
      MATERIAL_MATCHER_PORT: "18080"
      MATERIAL_MATCHER_SESSION_TTL_SECONDS: "1209600"
EOF
sed "s|RELEASE_VERSION_PLACEHOLDER|$RELEASE_VERSION|g" "$MEDIA/compose/BUILD_TAG" >"$COMPOSE_HOME/RELEASE" 2>/dev/null || echo "$IMAGE_REF" > "$COMPOSE_HOME/RELEASE"

# 介质 compose 参考文件随装入宿主机，便于维护人员查看。
cp -f "$MEDIA/compose/compose.yaml" "$COMPOSE_HOME/compose.reference.yaml" 2>/dev/null || true

# 安装器 bootstrap runtime 落到 /opt，供维护与修复场景复用。
if [[ -x "$MEDIA/bootstrap/python/bin/python3" && ! -x "$OPT/bootstrap/python/bin/python3" ]]; then
  mkdir -p "$OPT/bootstrap"
  cp -a "$MEDIA/bootstrap" "$OPT/bootstrap/python.tmp" 2>/dev/null || true
  rm -rf "$OPT/bootstrap/python"; mv "$OPT/bootstrap/python.tmp" "$OPT/bootstrap/python" 2>/dev/null || true
fi

# ---- 停旧容器并启动 -----------------------------------------------------------------
step 62 "正在启动服务容器……"
if docker ps -aq --filter "name=^/$CONTAINER$" 2>/dev/null | grep -q .; then
  ( cd "$COMPOSE_HOME" && MM_ENV_FILE="$DOCKER_ENV" docker compose --env-file "$DOCKER_ENV" -f compose.yaml down --ignore-stopped 2>/dev/null ) || docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
fi
if ! ( cd "$COMPOSE_HOME" && docker compose --env-file "$DOCKER_ENV" -f compose.yaml up -d 2>>"$LOG/docker-compose.log" ); then
  if [[ -n "$PREV_IMAGE" && "$PREV_IMAGE" != "$IMAGE_REF" && "$IS_UPGRADE" == "1" ]]; then
    echo "新版本容器启动失败，自动回滚旧镜像……" >&2
    sed -i "s|^MM_IMAGE=.*|MM_IMAGE=$PREV_IMAGE|" "$DOCKER_ENV"
    sed -i "s|image: .*|image: $PREV_IMAGE|" "$COMPOSE_HOME/compose.yaml"
    docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
    ( cd "$COMPOSE_HOME" && docker compose --env-file "$DOCKER_ENV" -f compose.yaml up -d 2>>"$LOG/docker-compose.log" ) || true
    die "$EXIT_START" "新版本容器启动失败，已自动回滚到旧镜像，旧系统恢复运行。请导出诊断包联系维护人员。"
  fi
  die "$EXIT_START" "容器启动失败，请导出诊断包联系维护人员。"
fi

step 66 "正在等待服务就绪（模型加载可能较慢，将持续显示进度）……"
READY_OK=""
for i in $(seq 1 180); do
  if "$PY" - "$FINAL_PORT" <<'PY'
import json, sys, urllib.request
try:
    with urllib.request.urlopen(f"http://127.0.0.1:{sys.argv[1]}/api/health/ready", timeout=3) as r:
        raise SystemExit(0 if json.load(r).get("status") == "ready" else 1)
except Exception:
    raise SystemExit(1)
PY
  then READY_OK=1; break; fi
  (( i % 15 == 0 )) && echo "[66%] 服务仍在初始化，已等待 ${i} 秒……"
  sleep 1
done
if [[ -z "$READY_OK" ]]; then
  if [[ -n "$PREV_IMAGE" && "$PREV_IMAGE" != "$IMAGE_REF" && "$IS_UPGRADE" == "1" ]]; then
    docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
    sed -i "s|^MM_IMAGE=.*|MM_IMAGE=$PREV_IMAGE|" "$DOCKER_ENV"
    sed -i "s|image: .*|image: $PREV_IMAGE|" "$COMPOSE_HOME/compose.yaml"
    ( cd "$COMPOSE_HOME" && docker compose --env-file "$DOCKER_ENV" -f compose.yaml up -d 2>>"$LOG/docker-compose.log" ) || true
    for _ in $(seq 1 120); do curl -sf "http://127.0.0.1:$FINAL_PORT/api/health" >/dev/null 2>&1 && break; sleep 1; done
    die "$EXIT_READY" "新版本 3 分钟内未就绪，已自动回滚旧镜像并恢复服务。请导出诊断包联系维护人员。"
  fi
  die "$EXIT_READY" "新版本 3 分钟内未就绪。首次安装已停止，容器与日志状态保留供诊断。请导出诊断包联系维护人员。"
fi

# ---- 默认业务 seed（幂等） ------------------------------------------------------------
step 90 "正在导入默认业务配置（6 个正式方案与同义词表，重复运行自动跳过）……"
SEED_SUMMARY="未导入"
SEED_OUT="$(docker exec "$CONTAINER" /opt/material_matcher/current/runtime/bin/material-matcher seed-import --seed-dir /opt/material_matcher/current/seed/business 2>&1)" || true
if printf '%s' "$SEED_OUT" | "$PY" -c 'import json,sys;raise SystemExit(0 if json.load(sys.stdin).get("ok") else 1)' 2>/dev/null; then
  SEED_SUMMARY="$(MM_SEED_JSON="$SEED_OUT" "$PY" - <<'PY'
import json, os
c = json.loads(os.environ["MM_SEED_JSON"])["counts"]
print(f"新增方案 {c['profiles_imported']} 个，跳过已有 {c['profiles_skipped']} 个；同义词表新增 {c['dictionaries_imported']} 张，跳过已有 {c['dictionaries_skipped']} 张")
PY
)"
elif [[ "$IS_UPGRADE" == "0" ]]; then
  die "$EXIT_SEED" "默认业务配置导入失败，系统缺少 6 个正式方案，不能视为安装成功。请导出诊断包联系维护人员。"
else
  SEED_SUMMARY="导入失败（升级不阻断；请稍后通过维护工具重试）"
fi

# ---- 报告与结果 ----------------------------------------------------------------------
step 96 "正在生成安装报告……"
MAP_ADDRESSES="$(ip -4 -o addr show scope global 2>/dev/null | awk '{print $2, $4}' | grep -Ev '^(docker[0-9]*|br-|veth|virbr|tailscale|kube|flannel|cni|nerdctl|lo)' | awk '{print $2}' | cut -d/ -f1 || true)"
MODE_TEXT="首次安装"; [[ "$IS_UPGRADE" == "1" ]] && MODE_TEXT="升级安装"
FIREWALL_HINT=""
if command -v firewall-cmd >/dev/null 2>&1 && firewall-cmd --state >/dev/null 2>&1; then
  FIREWALL_HINT="检测到 firewalld：如其它电脑无法访问，请网络管理员放行端口 $FINAL_PORT（本安装器不自动改防火墙）。"
fi
GIT_COMMIT="$("$PY" -c "import json;print(json.load(open('$MEDIA/docker-manifest.json',encoding='utf-8')).get('git_commit','unknown'))" 2>/dev/null || echo unknown)"
REPORT_FILE="$REPORT_DIR/docker-install-$(date +%Y%m%d-%H%M%S).txt"
{
  echo "物料集团码智能匹配平台（Docker 方式）安装报告"
  echo "===================================="
  echo "模式：$MODE_TEXT"
  echo "版本：$RELEASE_VERSION"
  echo "Git commit：$GIT_COMMIT"
  echo "Docker 状态：$DOCKER_STATE ($(docker version --format '{{.Server.Version}}' 2>/dev/null))"
  echo "Compose：$(docker compose version --short 2>/dev/null)"
  echo "镜像：$IMAGE_REF (ID $(docker image inspect --format '{{.Id}}' "$IMAGE_REF" | cut -c8-19)…)"
  echo "时间：$(date '+%F %T')"
  echo "配置：$ETC  数据：$VAR  日志：$LOG"
  [[ -n "$DATA_MOUNT_RESOLVED" ]] && echo "数据盘：${MM_DATA_MOUNT:-}（实际存储 $DATA_MOUNT_RESOLVED；Docker data-root：$(sed -n 's/.*"data-root": *"\([^"]*\)".*/\1/p' /etc/docker/daemon.json 2>/dev/null || true)）"
  echo "宿主机端口：$FINAL_PORT"
  echo "本机访问：http://127.0.0.1:$FINAL_PORT"
  for a in $MAP_ADDRESSES; do echo "局域网访问：http://${a}:$FINAL_PORT"; done
  [[ -n "$FIREWALL_HINT" ]] && echo "防火墙提示：$FIREWALL_HINT"
  echo "默认业务配置：$SEED_SUMMARY"
  echo "管理员账号：admin；密码：（报告不含明文，见 $PASSWORD_FILE）"
} >"$REPORT_FILE"
chmod 0600 "$REPORT_FILE"
step 100 "安装完成。"
echo "@@RESULT@@|$(MM_SEED="$SEED_SUMMARY" MM_MODE="$MODE_TEXT" MM_VER="$RELEASE_VERSION" MM_COMMIT="$GIT_COMMIT" MM_PORT="$FINAL_PORT" MM_PW="$PASSWORD_SOURCE" MM_ADDR="$MAP_ADDRESSES" MM_FW="$FIREWALL_HINT" MM_REPORT="$REPORT_FILE" MM_IMG="$IMAGE_REF" "$PY" - <<'PY'
import json, os
e = os.environ
print(json.dumps({"ok": True, "mode": e["MM_MODE"], "version": e["MM_VER"], "git_commit": e["MM_COMMIT"], "port": int(e["MM_PORT"]),
                  "password_source": e["MM_PW"], "seed_summary": e["MM_SEED"], "addresses": [a for a in e["MM_ADDR"].split() if a],
                  "firewall_hint": e["MM_FW"], "report_file": e["MM_REPORT"], "image": e["MM_IMG"],
                  "service_active": "running" if os.system("docker ps --format '{{.Names}}' | grep -qx material_matcher-app") == 0 else "unknown"}, ensure_ascii=False))
PY
)"
echo "MATERIAL_MATCHER（Docker 方式）${MODE_TEXT}完成：版本 $RELEASE_VERSION，端口 $FINAL_PORT。"
for a in $MAP_ADDRESSES; do echo "局域网访问地址：http://${a}:$FINAL_PORT"; done
echo "管理员账号：admin；初始密码文件：$PASSWORD_FILE（root 可读）"
echo "安装报告：$REPORT_FILE"
