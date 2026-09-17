#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BUNDLE_ROOT="${MATERIAL_MATCHER_BUNDLE_ROOT:-$SCRIPT_DIR}"
INSTALL_SCRIPT="$BUNDLE_ROOT/install.sh"
MANIFEST="$BUNDLE_ROOT/offline-manifest.json"
TEMP_ENV=""
TEMP_LOG=""
GUI_KIND=""

cleanup() {
  [[ -n "$TEMP_ENV" ]] && rm -f "$TEMP_ENV"
  [[ -n "$TEMP_LOG" ]] && rm -f "$TEMP_LOG"
}
trap cleanup EXIT

fail() {
  show_error "$*"
  exit 1
}

if [[ -n "${DISPLAY:-}${WAYLAND_DISPLAY:-}" ]]; then
  if command -v zenity >/dev/null 2>&1; then GUI_KIND="zenity"
  elif command -v kdialog >/dev/null 2>&1; then GUI_KIND="kdialog"
  fi
fi

show_info() {
  local text="$1"
  case "$GUI_KIND" in
    zenity) zenity --info --title="物料集团码智能匹配平台" --width=520 --text="$text" ;;
    kdialog) kdialog --title "物料集团码智能匹配平台" --msgbox "$text" ;;
    *) printf '\n%s\n\n' "$text" ;;
  esac
}

show_error() {
  local text="$1"
  case "$GUI_KIND" in
    zenity) zenity --error --title="安装失败" --width=560 --text="$text" || true ;;
    kdialog) kdialog --title "安装失败" --error "$text" || true ;;
    *) printf '安装失败：%s\n' "$text" >&2 ;;
  esac
}

ask_text() {
  local title="$1" prompt="$2" default_value="${3:-}"
  case "$GUI_KIND" in
    zenity) zenity --entry --title="$title" --width=560 --text="$prompt" --entry-text="$default_value" ;;
    kdialog) kdialog --title "$title" --inputbox "$prompt" "$default_value" ;;
    *)
      local answer
      read -r -p "$prompt [$default_value]: " answer
      printf '%s\n' "${answer:-$default_value}"
      ;;
  esac
}

ask_password() {
  local prompt="$1"
  case "$GUI_KIND" in
    zenity) zenity --password --title="管理员密码（可留空自动生成）" 2>/dev/null || true ;;
    kdialog) kdialog --title "管理员密码（可留空自动生成）" --password "$prompt" 2>/dev/null || true ;;
    *)
      local answer
      read -r -s -p "$prompt（直接回车自动生成）: " answer
      printf '\n' >&2
      printf '%s\n' "$answer"
      ;;
  esac
}

confirm_install() {
  local text="$1"
  case "$GUI_KIND" in
    zenity) zenity --question --title="确认安装" --width=580 --ok-label="开始安装" --cancel-label="返回" --text="$text" ;;
    kdialog) kdialog --title "确认安装" --yesno "$text" --yes-label "开始安装" --no-label "返回" ;;
    *)
      local answer
      read -r -p "$text\n输入 y 开始安装: " answer
      [[ "$answer" =~ ^[Yy]$ ]]
      ;;
  esac
}

run_root() {
  if [[ $EUID -eq 0 ]]; then
    bash -c 'set -a; source "$1"; set +a; exec "$2"' _ "$TEMP_ENV" "$INSTALL_SCRIPT"
  elif command -v pkexec >/dev/null 2>&1 && [[ -n "$GUI_KIND" ]]; then
    pkexec bash -c 'set -a; source "$1"; set +a; exec "$2"' _ "$TEMP_ENV" "$INSTALL_SCRIPT"
  elif command -v sudo >/dev/null 2>&1; then
    sudo bash -c 'set -a; source "$1"; set +a; exec "$2"' _ "$TEMP_ENV" "$INSTALL_SCRIPT"
  else
    return 127
  fi
}

read_root_file() {
  local path="$1"
  if [[ $EUID -eq 0 ]]; then cat "$path"
  elif command -v sudo >/dev/null 2>&1; then sudo cat "$path"
  elif command -v pkexec >/dev/null 2>&1; then pkexec cat "$path"
  else return 1
  fi
}

[[ -x "$INSTALL_SCRIPT" ]] || fail "安装介质缺少可执行 install.sh。"
[[ -f "$MANIFEST" ]] || fail "当前目录不是完整离线安装介质：缺少 offline-manifest.json。"
command -v python3 >/dev/null 2>&1 || fail "系统缺少 python3，请联系运维人员。"
command -v systemctl >/dev/null 2>&1 || fail "系统缺少 systemd/systemctl，请联系运维人员。"

grep -Eqi 'kylin|银河麒麟' /etc/os-release 2>/dev/null || fail "该安装向导仅面向银河麒麟 Linux V10 正式环境。"

VERSION="$(python3 - "$MANIFEST" <<'PY'
import json, sys
print(json.load(open(sys.argv[1], encoding='utf-8')).get('release_version',''))
PY
)"

show_info "欢迎安装“物料集团码智能匹配平台”。\n\n版本：${VERSION:-未知}\n\n向导只会询问安装路径、数据路径、端口和管理员密码，其余配置自动完成。"
show_info "环境检查通过。\n\n已检测：银河麒麟、Python 3、systemd、安装介质清单。\n安装前不会删除已有数据库、索引或结果。"

INSTALL_DIR="$(ask_text "安装位置" "请选择程序安装路径（不要包含空格）" "/opt/material_matcher")" || exit 0
[[ "$INSTALL_DIR" == /* ]] || fail "安装路径必须是绝对路径。"
[[ "$INSTALL_DIR" != *[[:space:]]* ]] || fail "安装路径暂不支持空格。"

DATA_DIR="$(ask_text "数据位置（高级）" "数据路径可留空，由系统自动选择；已有安装不会自动切换数据目录" "")" || exit 0
[[ -z "$DATA_DIR" || "$DATA_DIR" == /* ]] || fail "数据路径必须是绝对路径。"

PORT="$(ask_text "服务端口" "请输入访问端口" "18080")" || exit 0
[[ "$PORT" =~ ^[0-9]+$ ]] || fail "端口必须是数字。"
(( PORT >= 1 && PORT <= 65535 )) || fail "端口必须在 1-65535 之间。"

ADMIN_PASSWORD="$(ask_password "请输入 admin 初始密码")"
if [[ -n "$ADMIN_PASSWORD" ]]; then
  (( ${#ADMIN_PASSWORD} >= 10 )) || fail "密码至少 10 位。"
  [[ "$ADMIN_PASSWORD" =~ [A-Za-z] && "$ADMIN_PASSWORD" =~ [0-9] ]] || fail "密码必须同时包含字母和数字。"
fi

DATA_TEXT="${DATA_DIR:-自动选择}"
PASSWORD_TEXT="自动生成"
[[ -n "$ADMIN_PASSWORD" ]] && PASSWORD_TEXT="使用已输入密码"
confirm_install "请确认：\n\n版本：${VERSION:-未知}\n安装路径：$INSTALL_DIR\n数据路径：$DATA_TEXT\n端口：$PORT\nadmin 密码：$PASSWORD_TEXT\n\n升级时将保留已有账号、数据库、索引和结果。" || exit 0

TEMP_ENV="$(mktemp)"
chmod 600 "$TEMP_ENV"
printf 'MATERIAL_MATCHER_BUNDLE_ROOT=%q\n' "$BUNDLE_ROOT" >"$TEMP_ENV"
printf 'MATERIAL_MATCHER_INSTALL_DIR=%q\n' "$INSTALL_DIR" >>"$TEMP_ENV"
printf 'MATERIAL_MATCHER_INSTALL_PORT=%q\n' "$PORT" >>"$TEMP_ENV"
printf 'MATERIAL_MATCHER_INSTALL_DATA_DIR=%q\n' "$DATA_DIR" >>"$TEMP_ENV"
printf 'MATERIAL_MATCHER_INSTALL_ADMIN_PASSWORD=%q\n' "$ADMIN_PASSWORD" >>"$TEMP_ENV"
TEMP_LOG="$(mktemp)"

set +e
if [[ "$GUI_KIND" == "zenity" ]]; then
  run_root 2>&1 | tee "$TEMP_LOG" | sed 's/^/# /' | zenity --progress --title="正在安装" --text="正在安装物料集团码智能匹配平台…" --pulsate --auto-close --no-cancel --width=560
  INSTALL_RC=${PIPESTATUS[0]}
elif [[ "$GUI_KIND" == "kdialog" ]]; then
  show_info "即将开始安装。系统可能会弹出管理员授权窗口。"
  run_root > >(tee "$TEMP_LOG") 2>&1
  INSTALL_RC=$?
else
  run_root 2>&1 | tee "$TEMP_LOG"
  INSTALL_RC=${PIPESTATUS[0]}
fi
set -e

if [[ $INSTALL_RC -ne 0 ]]; then
  LAST_LINES="$(tail -n 12 "$TEMP_LOG" 2>/dev/null || true)"
  fail "安装未完成。原有数据和旧版本会按底层安装器规则保留/回滚。\n\n最后日志：\n$LAST_LINES"
fi

PASSWORD_LINE="$(read_root_file /etc/material_matcher/secret/admin_password.env 2>/dev/null | sed -n 's/^MATERIAL_MATCHER_ADMIN_PASSWORD=//p' | tail -1 || true)"
if [[ -z "$PASSWORD_LINE" ]]; then PASSWORD_LINE="（请联系管理员查看 /etc/material_matcher/secret/admin_password.env）"; fi
show_info "安装成功。\n\n访问地址：http://127.0.0.1:$PORT\n管理员账号：admin\n管理员密码：$PASSWORD_LINE\n\n请立即记录密码并妥善保管，然后打开浏览器访问系统。"
