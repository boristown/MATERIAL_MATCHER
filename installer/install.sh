#!/usr/bin/env bash
set -euo pipefail

APP_NAME="material_matcher"
APP_DIR="/opt/material_matcher"
CONFIG_DIR="/etc/material_matcher"
DATA_LINK="/var/lib/material_matcher"
LOG_DIR="/var/log/material_matcher"
SERVICE_NAME="material_matcher.service"
PORT_MIN=12000
PORT_MAX=29999

log() { printf '[MATERIAL_MATCHER] %s\n' "$*"; }
die() { printf '[MATERIAL_MATCHER][ERROR] %s\n' "$*" >&2; exit 1; }

[[ "${EUID}" -eq 0 ]] || die "请使用 root 权限运行：sudo ./install.sh"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUNDLE_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

check_os() {
  if [[ -r /etc/os-release ]]; then
    # shellcheck disable=SC1091
    source /etc/os-release
    log "检测到操作系统：${PRETTY_NAME:-${NAME:-unknown}}"
    if [[ "${ID:-}" != *kylin* && "${NAME:-}" != *麒麟* && "${NAME:-}" != *Kylin* ]]; then
      log "警告：当前不是已识别的银河麒麟系统；开发/验证环境允许继续，生产环境应使用银河麒麟 Linux V10。"
    fi
  fi
}

choose_data_mount() {
  local best_mount="/"
  local best_avail=0
  while read -r filesystem fstype blocks used avail capacity mountpoint; do
    [[ "${filesystem}" == "Filesystem" ]] && continue
    case "${fstype}" in
      ext2|ext3|ext4|xfs|btrfs) ;;
      *) continue ;;
    esac
    case "${mountpoint}" in
      /boot*|/run*|/tmp*|/var/log*) continue ;;
    esac
    [[ -w "${mountpoint}" ]] || continue
    if [[ "${avail}" =~ ^[0-9]+$ ]] && (( avail > best_avail )); then
      best_avail="${avail}"
      best_mount="${mountpoint}"
    fi
  done < <(df -PT -B1 2>/dev/null || true)
  printf '%s\n' "${best_mount}"
}

port_is_free() {
  local port="$1"
  if command -v ss >/dev/null 2>&1; then
    ! ss -ltnH 2>/dev/null | awk '{print $4}' | grep -Eq "(^|:)${port}$"
  elif command -v netstat >/dev/null 2>&1; then
    ! netstat -ltn 2>/dev/null | awk '{print $4}' | grep -Eq "(^|:)${port}$"
  else
    return 0
  fi
}

choose_port() {
  local span=$((PORT_MAX - PORT_MIN + 1))
  local i value candidate
  for i in $(seq 1 200); do
    value="$(od -An -N4 -tu4 /dev/urandom | tr -d ' ')"
    candidate=$((PORT_MIN + value % span))
    if port_is_free "${candidate}"; then
      printf '%s\n' "${candidate}"
      return 0
    fi
  done
  for candidate in $(seq "${PORT_MIN}" "${PORT_MAX}"); do
    if port_is_free "${candidate}"; then
      printf '%s\n' "${candidate}"
      return 0
    fi
  done
  return 1
}

generate_password() {
  dd if=/dev/urandom bs=48 count=1 status=none | base64 | tr -dc 'A-Za-z0-9' | cut -c1-10
}

install_files() {
  mkdir -p "${APP_DIR}" "${CONFIG_DIR}/secret" "${LOG_DIR}"
  chmod 0755 "${APP_DIR}" "${CONFIG_DIR}" "${LOG_DIR}"
  chmod 0700 "${CONFIG_DIR}/secret"

  # Development checkout: copy source tree. Release bundle will replace this
  # with the self-contained runtime + wheels + prebuilt Vue dist.
  mkdir -p "${APP_DIR}/app"
  if [[ -d "${BUNDLE_ROOT}/src" ]]; then
    rm -rf "${APP_DIR}/app/src"
    cp -a "${BUNDLE_ROOT}/src" "${APP_DIR}/app/src"
  fi
  [[ -f "${BUNDLE_ROOT}/pyproject.toml" ]] && cp -f "${BUNDLE_ROOT}/pyproject.toml" "${APP_DIR}/app/pyproject.toml"
  if [[ -d "${BUNDLE_ROOT}/web/dist" ]]; then
    rm -rf "${APP_DIR}/web"
    cp -a "${BUNDLE_ROOT}/web/dist" "${APP_DIR}/web"
  else
    mkdir -p "${APP_DIR}/web"
  fi
}

configure_data_path() {
  local mountpoint="$1"
  local physical_root
  if [[ "${mountpoint}" == "/" ]]; then
    physical_root="${DATA_LINK}"
    mkdir -p "${physical_root}"
  else
    physical_root="${mountpoint%/}/material_matcher"
    mkdir -p "${physical_root}"
    if [[ -e "${DATA_LINK}" && ! -L "${DATA_LINK}" ]]; then
      if [[ -d "${DATA_LINK}" && -z "$(ls -A "${DATA_LINK}" 2>/dev/null)" ]]; then
        rmdir "${DATA_LINK}"
      else
        die "${DATA_LINK} 已存在且非空，安装器不会自动覆盖。"
      fi
    fi
    ln -sfn "${physical_root}" "${DATA_LINK}"
  fi

  mkdir -p "${DATA_LINK}/catalogs" "${DATA_LINK}/indexes" "${DATA_LINK}/profiles" \
           "${DATA_LINK}/results" "${DATA_LINK}/tmp" "${DATA_LINK}/uploads" "${DATA_LINK}/models"
  printf 'MATERIAL_MATCHER_DATA_PHYSICAL=%s\n' "${physical_root}" > "${CONFIG_DIR}/storage.env"
  chmod 0644 "${CONFIG_DIR}/storage.env"
}

configure_runtime() {
  local port="$1"
  local password_file="${CONFIG_DIR}/secret/admin_password.env"

  cat > "${CONFIG_DIR}/server.env" <<EOF
MATERIAL_MATCHER_HOST=0.0.0.0
MATERIAL_MATCHER_PORT=${port}
MATERIAL_MATCHER_CONFIG_DIR=${CONFIG_DIR}
MATERIAL_MATCHER_DATA_DIR=${DATA_LINK}
MATERIAL_MATCHER_LOG_DIR=${LOG_DIR}
MATERIAL_MATCHER_APP_DIR=${APP_DIR}
MATERIAL_MATCHER_WEB_ROOT=${APP_DIR}/web
EOF
  chmod 0644 "${CONFIG_DIR}/server.env"

  if [[ ! -s "${password_file}" ]]; then
    local password
    password="$(generate_password)"
    [[ "${#password}" -eq 10 ]] || die "随机密码生成失败"
    printf 'MATERIAL_MATCHER_ADMIN_PASSWORD=%s\n' "${password}" > "${password_file}"
    chmod 0600 "${password_file}"
  fi
}

install_service() {
  local python_bin="${APP_DIR}/runtime/bin/python"
  local command
  if [[ -x "${python_bin}" ]]; then
    command="${python_bin} -m material_matcher.cli serve"
  elif command -v python3 >/dev/null 2>&1; then
    # Development fallback only. Production release must ship its own runtime.
    command="$(command -v python3) -m material_matcher.cli serve"
    log "警告：当前使用系统 Python 作为开发回退；正式离线包必须携带 ${APP_DIR}/runtime。"
  else
    die "未找到随包 Python runtime，也没有系统 python3。"
  fi

  cat > "/etc/systemd/system/${SERVICE_NAME}" <<EOF
[Unit]
Description=MATERIAL_MATCHER B/S Service
After=network.target local-fs.target

[Service]
Type=simple
WorkingDirectory=${APP_DIR}/app
Environment=PYTHONPATH=${APP_DIR}/app/src
EnvironmentFile=${CONFIG_DIR}/server.env
EnvironmentFile=${CONFIG_DIR}/secret/admin_password.env
ExecStart=${command}
Restart=on-failure
RestartSec=3
NoNewPrivileges=true
PrivateTmp=true
ProtectSystem=full
ReadWritePaths=${DATA_LINK} ${LOG_DIR} ${CONFIG_DIR}

[Install]
WantedBy=multi-user.target
EOF

  systemctl daemon-reload
  systemctl enable --now "${SERVICE_NAME}"
}

healthcheck() {
  local port="$1"
  local url="http://127.0.0.1:${port}/api/health"
  local i
  for i in $(seq 1 30); do
    if command -v curl >/dev/null 2>&1 && curl -fsS "${url}" >/dev/null 2>&1; then
      return 0
    fi
    if command -v wget >/dev/null 2>&1 && wget -qO- "${url}" >/dev/null 2>&1; then
      return 0
    fi
    sleep 1
  done
  return 1
}

main() {
  check_os
  local data_mount port password
  data_mount="$(choose_data_mount)"
  port="$(choose_port)" || die "未能找到可用高位端口"

  log "推荐数据磁盘：${data_mount}"
  log "选择服务端口：${port}"

  install_files
  configure_data_path "${data_mount}"
  configure_runtime "${port}"
  install_service

  if healthcheck "${port}"; then
    log "服务健康检查通过。"
  else
    log "警告：服务尚未通过健康检查，请执行：journalctl -u ${SERVICE_NAME} -n 100"
  fi

  password="$(sed -n 's/^MATERIAL_MATCHER_ADMIN_PASSWORD=//p' "${CONFIG_DIR}/secret/admin_password.env" | head -n1)"
  printf '\nMATERIAL_MATCHER 安装完成\n\n'
  printf '访问地址 : http://<服务器IP>:%s\n' "${port}"
  printf '用户名   : admin\n'
  printf '首次密码 : %s\n' "${password}"
  printf '密码路径 : %s/secret/admin_password.env\n' "${CONFIG_DIR}"
  printf '配置路径 : %s\n' "${CONFIG_DIR}"
  printf '数据路径 : %s\n' "${DATA_LINK}"
  printf '日志路径 : %s\n' "${LOG_DIR}"
}

main "$@"
