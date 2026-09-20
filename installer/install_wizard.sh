#!/usr/bin/env bash
# 物料集团码智能匹配平台 · 图形/终端安装向导。
# 只使用 POSIX 常用工具 + 介质自带 bootstrap Python；不依赖目标机已安装 Python/Node。
# 界面文案与 docs/安装手册.md 一一对应；任何不一致视为安装包缺陷。
set -uo pipefail

MEDIA_ROOT="${MM_MEDIA_ROOT:-}"
if [[ -z "$MEDIA_ROOT" ]]; then
  MEDIA_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
fi
INSTALL_SH="$MEDIA_ROOT/install.sh"
MANIFEST="$MEDIA_ROOT/offline-manifest.json"
DEFAULT_INSTALL_PREFIX="/opt/material_matcher"
DEFAULT_PORT="18080"
GUI=""            # zenity | kdialog | ""(终端)
PY=""
BUNDLE_VERSION=""
BUNDLE_ARCH=""
BUNDLE_COMMIT=""
INSTALL_LOG_DIR="/var/log/material_matcher/install-reports"
WIZARD_LOG="${MM_WIZARD_LOG:-/var/tmp/material_matcher_wizard-$(date +%Y%m%d-%H%M%S).log}"
IS_TTY=0; [[ -t 1 ]] && IS_TTY=1   # main 会被管道化，此处提前判定操作员终端

# ---- 提权（.desktop / 启动安装.sh 已可能以 root 进入；此处兜底） ------------------
if [[ $EUID -ne 0 ]]; then
  if command -v sudo >/dev/null 2>&1; then
    exec sudo env DISPLAY="${DISPLAY:-}" MM_MEDIA_ROOT="$MEDIA_ROOT" bash "$MEDIA_ROOT/install_wizard.sh" "$@"
  fi
  if command -v pkexec >/dev/null 2>&1; then
    exec pkexec env DISPLAY="${DISPLAY:-}" XAUTHORITY="${XAUTHORITY:-}" \
      MM_MEDIA_ROOT="$MEDIA_ROOT" bash "$MEDIA_ROOT/install_wizard.sh" "$@"
  fi
  echo "当前账号没有安装权限：请使用具备系统管理员权限的账号重新运行安装程序。" >&2
  exit 44
fi

# ---- bootstrap Python（安装器不依赖目标机 Python） --------------------------------
if [[ -x "$MEDIA_ROOT/bootstrap/python/bin/python3" ]]; then
  PY="$MEDIA_ROOT/bootstrap/python/bin/python3"
elif [[ -x "$MEDIA_ROOT/release/runtime/bin/python3" ]]; then
  PY="$MEDIA_ROOT/release/runtime/bin/python3"
elif command -v python3 >/dev/null 2>&1; then
  PY="$(command -v python3)"
else
  echo "安装介质缺少 bootstrap 运行环境，本机也没有可用 Python；无法继续。请重新复制完整安装介质。" >&2
  exit 41
fi

py_json() {  # py_json <文件> <键>
  "$PY" - "$1" "$2" <<'PY' 2>/dev/null || true
import json, sys
m = json.load(open(sys.argv[1], encoding="utf-8"))
v = m.get(sys.argv[2], "")
print(v if isinstance(v, str) else json.dumps(v, ensure_ascii=False))
PY
}

[[ -f "$MANIFEST" ]] && {
  # 数据盘候选工具
[[ -f "$MEDIA_ROOT/disk_select.sh" ]] && . "$MEDIA_ROOT/disk_select.sh"

BUNDLE_VERSION="$(py_json "$MANIFEST" release_version)"
  BUNDLE_ARCH="$(py_json "$MANIFEST" target_arch)"
}
[[ -f "$MEDIA_ROOT/release/release-manifest.json" ]] && \
  BUNDLE_COMMIT="$(py_json "$MEDIA_ROOT/release/release-manifest.json" git_commit)"

detect_gui() {
  [[ -n "${DISPLAY:-}" || -n "${WAYLAND_DISPLAY:-}" ]] || return 0
  if command -v zenity >/dev/null 2>&1; then GUI=zenity
  elif command -v kdialog >/dev/null 2>&1; then GUI=kdialog
  fi
}
detect_gui

port_busy() { (exec 3<>/dev/tcp/127.0.0.1/"$1") 2>/dev/null; }

# ---- 对话原语 ---------------------------------------------------------------------
ui_note() {
  case "$GUI" in
    zenity)  zenity --info --title="$1" --text="$2" --width=600 ;;
    kdialog) kdialog --title "$1" --passiveinfo "$2" ;;
    *)       printf '\n== %s ==\n%b\n' "$1" "$2" ;;
  esac
}

ui_error() {
  case "$GUI" in
    zenity)  zenity --error --title="$1" --text="$2" --width=600 ;;
    kdialog) kdialog --title "$1" --error "$2" ;;
    *)       printf '\n!! %s\n%b\n' "$1" "$2" ;;
  esac
  printf '[ERROR] %s | %b\n' "$1" "$2" >>"$WIZARD_LOG" 2>/dev/null || true
}

ui_confirm() {  # -> 0 第一项 / 3 第二项 / 9 退出（终端）；$3/$4 选项文字
  case "$GUI" in
    zenity)  zenity --question --title="$1" --text="$2" --width=600 --yes-label="${3:-继续}" --no-label="${4:-取消}" && return 0
             [[ $? == "1" ]] && return 3 || return 9 ;;
    kdialog) kdialog --title "$1" --yesno "$2" && return 0
             [[ $? == "1" ]] && return 3 || return 9 ;;
    *)
      local a
      printf '%b\n请输入 y = %s；n = %s；其它键 = 退出安装（不做任何修改）：' "$2" "${3:-继续}" "${4:-取消}" >&2
      read -r a
      case "$a" in y|Y) return 0 ;; n|N) return 3 ;; *) return 9 ;; esac
      ;;
  esac
}

ui_entry() {  # $1 标题 $2 提示 $3 默认值
  case "$GUI" in
    zenity)  zenity --entry --title="$1" --text="$2" --entry-text="$3" --width=600 ;;
    kdialog) kdialog --title "$1" --inputbox "$2" "$3" ;;
    *)       local v; printf '%s [%s]：' "$2" "$3" >&2; read -r v; printf '%s' "${v:-$3}" ;;
  esac
}

ui_password() {  # stdout 密码；空表示放弃手工输入
  case "$GUI" in
    zenity)  zenity --password --title="$1" ;;
    kdialog) kdialog --title "$1" --password "管理员密码（至少 10 位）" ;;
    *)
      local p1 p2
      printf '%s（至少 10 位，输入不回显；直接回车改用自动生成）：' "$1" >&2
      IFS= read -rs p1; echo >&2
      [[ -z "$p1" ]] && return 0
      while [[ ${#p1} -lt 10 ]]; do
        printf '密码太短（至少 10 位），重新输入（回车改用自动生成）：' >&2; IFS= read -rs p1; echo >&2
        [[ -z "$p1" ]] && { printf ''; return 0; }
      done
      printf '再次输入确认：' >&2; IFS= read -rs p2; echo >&2
      while [[ "$p1" != "$p2" ]]; do
        printf '两次不一致，重新确认：' >&2; IFS= read -rs p2; echo >&2
      done
      printf '%s' "$p1"
      ;;
  esac
}

generate_password() {
  "$PY" - <<'PY'
import secrets, string
letters = string.ascii_letters
digits = string.digits
pool = list(secrets.choice(letters + digits) for _ in range(10))
pool[0] = secrets.choice(letters)
pool[-1] = secrets.choice(digits)
secrets.SystemRandom().shuffle(pool)
print("".join(pool))
PY
}

# ---- 环境检查 ---------------------------------------------------------------------
CHECKS_OK=1
CHECK_LINES=()
PORT_DEFAULT="$DEFAULT_PORT"
PORT_SUGGESTED=""
IS_UPGRADE_DETECTED=0

check() {  # check <说明> <1通过/0失败> <失败建议>
  if [[ "$2" == "1" ]]; then
    CHECK_LINES+=("✅ $1")
  else
    CHECK_LINES+=("❌ $1 —— $3")
    CHECKS_OK=0
  fi
}

run_env_checks() {
  CHECKS_OK=1; CHECK_LINES=(); PORT_SUGGESTED=""

  local os_ok=1; grep -Eqi 'kylin|银河麒麟' /etc/os-release 2>/dev/null || os_ok=0
  check "操作系统：银河麒麟" "$os_ok" "当前安装包仅支持银河麒麟 V10，请向交付人员索取匹配当前系统的介质。"

  local arch_now; arch_now="$(uname -m)"
  local arch_norm="$BUNDLE_ARCH"
  case "$arch_norm" in amd64) arch_norm=x86_64;; arm64) arch_norm=aarch64;; esac
  local arch_ok=0; [[ -n "$arch_norm" && "$arch_now" == "$arch_norm" ]] && arch_ok=1
  check "CPU 架构：本机 $arch_now / 介质 ${arch_norm:-未知}" "$arch_ok" "请使用与本服务器 CPU 架构一致的介质（x86_64 或 aarch64）。"

  local sd_ok=1; [[ -d /run/systemd/system ]] || sd_ok=0
  check "systemd 服务管理器" "$sd_ok" "当前环境未运行 systemd（例如普通容器），请在正式银河麒麟 V10 服务器上安装。"

  local media_ok=1
  [[ -f "$INSTALL_SH" && -f "$MANIFEST" && -f "$MEDIA_ROOT/verify_offline_bundle.py" ]] || media_ok=0
  check "安装入口文件" "$media_ok" "安装目录不完整，请从源头重新完整复制安装介质。"

  local disk_avail=$(( $(df -Pk / | awk 'NR==2 {print $4}') / 1024 ))
  local disk_ok=1; (( disk_avail < 6144 )) && disk_ok=0
  check "磁盘可用空间：约 $((disk_avail / 1024)) GB" "$disk_ok" "至少需要约 6 GB 可用空间（程序+数据+模型），请清理磁盘或更换安装位置。"

  local assets_ok=1
  [[ -d "$MEDIA_ROOT/wheelhouse" && -d "$MEDIA_ROOT/models" ]] || assets_ok=0
  check "离线运行环境与 AI 模型随介质提供" "$assets_ok" "介质缺少 wheelhouse 或 models 目录，请重新复制完整介质。"

  if [[ -L /opt/material_matcher/current ]]; then
    IS_UPGRADE_DETECTED=1
    local installed="未知"
    [[ -f /opt/material_matcher/current/release-manifest.json ]] && \
      installed="$(py_json /opt/material_matcher/current/release-manifest.json release_version)"
    CHECK_LINES+=("ℹ️ 检测到已安装版本 ${installed:-未知}：本次为升级安装，现有账号、任务、数据与结果将完整保留")
    local existing
    existing="$(grep -m1 '^MATERIAL_MATCHER_PORT=' /etc/material_matcher/server.env 2>/dev/null | cut -d= -f2 || true)"
    [[ -n "$existing" ]] && PORT_DEFAULT="$existing"
  else
    CHECK_LINES+=("ℹ️ 未检测到已安装版本：本次为首次安装")
  fi

  own_service=0
  if [[ "$IS_UPGRADE_DETECTED" == "1" ]] && systemctl is-active --quiet material_matcher.service 2>/dev/null; then
    own_service=1  # 占用者就是本产品自身：升级会短暂停服再复用同一端口，不算冲突
  fi
  if [[ "$own_service" == "0" ]] && port_busy "$PORT_DEFAULT"; then
    PORT_SUGGESTED="$("$PY" - "$PORT_DEFAULT" <<'PY'
import socket, sys
start = int(sys.argv[1]) + 1
for port in range(start, start + 200):
    s = socket.socket(); s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        s.bind(("0.0.0.0", port)); print(port); break
    except OSError:
        pass
    finally:
        s.close()
PY
)"
    if [[ -n "$PORT_SUGGESTED" ]]; then
      CHECK_LINES+=("ℹ️ 端口 $PORT_DEFAULT 已被占用，向导建议使用 $PORT_SUGGESTED")
    else
      check "端口可用性" "0" "默认端口被占用且附近没有可用端口，请联系网络管理员释放端口。"
    fi
  fi

  local db_a=""
  if [[ -f /etc/material_matcher/storage.env ]]; then
    db_a="$(grep -m1 '^MATERIAL_MATCHER_DATA_DIR=' /etc/material_matcher/storage.env | cut -d= -f2 | tr -d '"')"
    [[ -n "$db_a" ]] && db_a="$(readlink -m "$db_a")/meta/material_matcher.db"
  fi
  local db_b; db_b="$(readlink -m /var/lib/material_matcher/meta/material_matcher.db)"
  if [[ -n "$db_a" && "$db_a" != "$db_b" && -f "$db_a" && -f "$db_b" ]]; then
    check "唯一数据目录" "0" "检测到两份业务数据库，安装已按数据保护规则停止。请导出诊断包并联系维护人员确认唯一数据目录。"
  fi
}

# ---- 安装执行（单进程 + 进度通道） --------------------------------------------------
TMP_OUT=""
FIFO=""
ZPID=""
INSTALL_RC=1

exec_install_with_progress() {
  local args=()
  [[ -n "${MM_DATA_DIR_SET:-}" ]] && args+=("MM_DATA_DIR=$MM_DATA_DIR_SET")
  [[ -n "${MM_DATA_MOUNT_SET:-}" ]] && args+=("MM_DATA_MOUNT=$MM_DATA_MOUNT_SET")
  [[ -n "${MM_ADMIN_PASSWORD_SET:-}" ]] && args+=("MM_ADMIN_PASSWORD=$MM_ADMIN_PASSWORD_SET")
  rm -f '/var/lib/material_matcher/install/last_result.json' 2>/dev/null || true
  TMP_OUT="$(mktemp /tmp/mm_install.XXXXXX)"
  : >"$WIZARD_LOG" 2>/dev/null || true

  if [[ "$GUI" == "zenity" ]]; then
    FIFO="$(mktemp -u /tmp/mm_progress.XXXXXX)"; mkfifo "$FIFO"
    zenity --progress --title="正在安装 物料集团码智能匹配平台" --text="准备开始……" \
      --percentage=0 --no-cancel --width=600 <"$FIFO" &
    ZPID=$!
    exec 5>"$FIFO"
    MM_PROGRESS_ON=1 MM_PORT_USER_CHOICE=1 MM_INSTALL_PORT="$CHOSEN_PORT" \
      MM_INSTALL_PREFIX="$INSTALL_PREFIX" MM_ADMIN_PASSWORD_SOURCE="$PW_MODE" \
      env "${args[@]}" bash "$INSTALL_SH" > >(tee "$TMP_OUT" | _forward_steps) 2>&1
    INSTALL_RC=$?
    sleep 1
    printf '100\n#安装结束\n' >&5 2>/dev/null || true
    exec 5>&-
    wait "$ZPID" 2>/dev/null || true
    rm -f "$FIFO"
  else
    echo
    MM_PROGRESS_ON=1 MM_PORT_USER_CHOICE=1 MM_INSTALL_PORT="$CHOSEN_PORT" \
      MM_INSTALL_PREFIX="$INSTALL_PREFIX" MM_ADMIN_PASSWORD_SOURCE="$PW_MODE" \
      env "${args[@]}" bash "$INSTALL_SH" 2>&1 | _relay_terminal
    INSTALL_RC=${PIPESTATUS[0]}
  fi
  cat "$TMP_OUT" >>"$WIZARD_LOG" 2>/dev/null || true
}

_relay_terminal() {
  # 显示给人看：隐藏 @@协议行@@；完整原始输出保留在 TMP_OUT 供解析。
  while IFS= read -r line; do
    printf '%s\n' "$line" >>"$TMP_OUT"
    case "$line" in
      "@@STEP@@|"*|"@@RESULT@@|"*) : ;;
      *) printf '%s\n' "$line" ;;
    esac
  done
}

_forward_steps() {
  # stdin: install.sh 输出；全部转发到 $FIFO 对应的 fd 5（形如 <pct>\n#<text>），原样透传 tee。
  while IFS= read -r line; do
    printf '%s\n' "$line"
    case "$line" in
      "@@STEP@@|"*)
        local rest="${line#@@STEP@@|}"
        printf '%s\n#%s\n' "${rest%%|*}" "${rest#*|}" >&5 2>/dev/null || true
        ;;
    esac
  done
}

# ---- 主流程 -------------------------------------------------------------------------
main() {
  if [[ ! -f "$MANIFEST" ]]; then
    ui_error "无法启动安装" "当前目录不是完整的安装介质（缺少 offline-manifest.json）。\n请把整个安装目录完整复制到服务器本地磁盘后再运行。"
    exit 41
  fi

  ui_note "欢迎" "欢迎安装【物料集团码智能匹配平台】。\n\n本向导引导您完成完全离线安装，全程无需联网。\n根据服务器与存储速度，整个安装通常不到 1 分钟至 10 分钟。\n\n版本：${BUNDLE_VERSION:-未知}　架构：${BUNDLE_ARCH:-未知}"

  echo "正在自动检查运行环境……"
  run_env_checks
  local check_text=""; local line
  for line in "${CHECK_LINES[@]}"; do check_text+="$line\n"; done
  ui_note "环境检查" "$check_text"
  if [[ "$CHECKS_OK" != "1" ]]; then
    ui_error "环境检查未通过" "环境检查发现问题，为避免损坏系统，安装未开始。\n\n$check_text\n\n请按建议处理后重新运行安装。详细记录：$WIZARD_LOG"
    exit 43
  fi

  INSTALL_PREFIX="$(ui_entry "安装位置" "程序安装位置（直接回车使用默认值）" "$DEFAULT_INSTALL_PREFIX")" || { echo "已取消安装。"; exit 0; }
  [[ "$INSTALL_PREFIX" == /* ]] || { ui_error "安装位置无效" "安装位置必须是绝对路径（例如 /opt/material_matcher）。"; exit 1; }

  MM_DATA_DIR_SET=""; MM_DATA_MOUNT_SET=""
  if [[ "$IS_UPGRADE_DETECTED" == "1" ]]; then
    ui_note "数据位置" "检测到已有安装：升级将自动沿用现有数据目录（/etc/material_matcher/storage.env 指向的位置），不会移动、清空或重建任何业务数据。"
  else
    rc_choice=0
    DISK_TEXT=""
    if [[ -f "$MEDIA_ROOT/disk_select.sh" ]]; then
      DISK_TEXT="$(disk_candidates_text)"
      DISK_RECOMMEND="$(disk_top_mount)"
    fi
    ui_confirm "数据盘选择" "数据目录将决定数据库、上传文件与结果存放位置，安装后固定不变，建议选择剩余空间最大的磁盘。\n\n服务器磁盘（前三名）：\n${DISK_TEXT:-  （探测不到多磁盘，将使用系统默认策略）}\n推荐：${DISK_RECOMMEND:-默认策略}\n\ny = 接受推荐　n = 改选其它磁盘/自定义路径　其它键 = 退出安装（不做任何修改）" "接受推荐" "改选" || rc_choice=$?
    if [[ "$rc_choice" == "0" ]]; then
      MM_DATA_MOUNT_SET="${DISK_RECOMMEND:-}"
    elif [[ "$rc_choice" == "3" ]]; then
      ANS="$(ui_entry "改选磁盘" "输入编号（1-3），或输入自定义数据目录绝对路径" "1")" || { echo "用户已取消，未对系统做任何修改。"; exit 0; }
      RESOLVED=""
      if [[ -f "$MEDIA_ROOT/disk_select.sh" ]]; then RESOLVED="$(disk_resolve_choice "$ANS" || true)"; fi
      [[ -z "$RESOLVED" && "$ANS" == /* ]] && RESOLVED="$ANS"
      [[ -z "$RESOLVED" ]] && { ui_error "无效选择" "未识别编号或路径，安装已退出，系统未做修改。"; exit 1; }
      if [[ "$RESOLVED" == /*/* || "${ANS:-1}" =~ ^[1-4]$ ]]; then MM_DATA_MOUNT_SET="$RESOLVED"; fi
      [[ "${ANS:-}" == /* ]] && { MM_DATA_MOUNT_SET=""; MM_DATA_DIR_SET="$ANS"; }
    else
      echo "用户已取消，未对系统做任何修改。"; exit 0
    fi
  fi

  local port_default_eff="$PORT_DEFAULT"
  [[ -n "$PORT_SUGGESTED" ]] && port_default_eff="$PORT_SUGGESTED"
  CHOSEN_PORT=""
  while :; do
    CHOSEN_PORT="$(ui_entry "服务端口" "服务监听端口$([[ "$IS_UPGRADE_DETECTED" == "1" ]] && echo "（升级安装建议保持默认=当前端口）" || echo "（首次安装默认 18080，直接回车即可）")" "$port_default_eff")" || { echo "已取消安装。"; exit 0; }
    [[ "$CHOSEN_PORT" =~ ^[0-9]+$ ]] && (( CHOSEN_PORT >= 1024 && CHOSEN_PORT <= 65535 )) || \
      { ui_error "端口无效" "请输入 1024～65535 之间的数字端口。"; continue; }
    if port_busy "$CHOSEN_PORT"; then
      if [[ "$IS_UPGRADE_DETECTED" == "1" ]] && grep -q "MATERIAL_MATCHER_PORT=$CHOSEN_PORT" /etc/material_matcher/server.env 2>/dev/null; then
        break  # 占用者就是本产品（升级重启属正常）
      fi
      ui_error "端口被占用" "端口 $CHOSEN_PORT 已被其它程序占用，请选择其它端口。\n（参考：${PORT_SUGGESTED:-附近可用端口请手工尝试}）"
      continue
    fi
    break
  done

  MM_ADMIN_PASSWORD_SET=""
  PW_MODE=""
  if [[ "$IS_UPGRADE_DETECTED" == "1" && -f /etc/material_matcher/secret/admin_password.env ]]; then
    PW_MODE="keep"
    ui_note "管理员账号" "升级安装保留现有 admin 账号与密码，安装程序不会重置任何登录信息。"
  else
    rc_pw=0; ui_confirm "管理员密码" "请选择 admin 初始密码设置方式：\n\ny = 由您手工输入密码\nn = 自动生成强密码（完成后按环境策略显示或写入 root-only 文件）" "手工输入" "自动生成" || rc_pw=$?
    if [[ "$rc_pw" == "0" ]]; then
      local pw
      while :; do
        pw="$(ui_password "设置管理员密码")" || { echo "已取消安装。"; exit 0; }
        if [[ -z "$pw" ]]; then PW_MODE="generated"; MM_ADMIN_PASSWORD_SET="$(generate_password)"; break; fi
        if (( ${#pw} >= 10 )) && [[ "$pw" =~ [A-Za-z] ]] && [[ "$pw" =~ [0-9] ]]; then PW_MODE="user"; MM_ADMIN_PASSWORD_SET="$pw"; break; fi
        ui_error "密码不符合要求" "密码至少 10 位且需同时包含字母和数字（或改选自动生成）。"
      done
    elif [[ "$rc_pw" == "3" ]]; then
      PW_MODE="generated"; MM_ADMIN_PASSWORD_SET="$(generate_password)"
    else
      echo "用户已取消，未对系统做任何修改。"; exit 0
    fi
  fi
  local pw_choice
  case "$PW_MODE" in
    keep)      pw_choice="保留现有密码（升级不重置）" ;;
    user)      pw_choice="由您手工设置" ;;
    generated) pw_choice=$([[ "$IS_TTY" == "1" || -n "$GUI" ]] && echo "自动生成，完成后显示一次" || echo "自动生成（写入 root-only 密码文件，不回显）") ;;
  esac

  local mode_text="首次安装"
  [[ "$IS_UPGRADE_DETECTED" == "1" ]] && mode_text="升级安装（保留全部账号、任务、数据库、索引与结果）"
  local data_text="自动选择安全数据盘"
  [[ -n "${MM_DATA_MOUNT_SET:-}" ]] && data_text="$MM_DATA_MOUNT_SET/material_matcher_data（数据盘统一经 /var/lib/material_matcher 访问）"
  [[ -n "${MM_DATA_DIR_SET:-}" ]] && data_text="$MM_DATA_DIR_SET"
  [[ "$IS_UPGRADE_DETECTED" == "1" ]] && data_text="沿用现有数据目录（不改动）"
  [[ -n "$MM_DATA_DIR_SET" ]] && data_text="$MM_DATA_DIR_SET"
  ui_confirm "确认安装" "即将开始安装，请确认：\n\n· 产品：物料集团码智能匹配平台\n· 版本：${BUNDLE_VERSION:-未知}（commit ${BUNDLE_COMMIT:-见安装报告}）\n· 架构：${BUNDLE_ARCH:-未知}\n· 方式：$mode_text\n· 程序目录：$INSTALL_PREFIX\n· 数据目录：$data_text\n· 服务端口：$CHOSEN_PORT\n· 管理员密码：$pw_choice\n· 网络：完全离线安装，无需公网\n\n确认后开始安装，期间请勿关闭窗口。" "开始安装" "取消安装" || { echo "用户已取消，未对系统做任何修改。"; exit 0; }

  echo "开始安装（过程日志：$WIZARD_LOG）……"
  exec_install_with_progress

  local install_err result_json
  result_json="$(cat '/var/lib/material_matcher/install/last_result.json' 2>/dev/null || true)"
  [[ -z "$result_json" ]] && result_json="$(grep -m1 '^@@RESULT@@|' "$TMP_OUT" 2>/dev/null | sed 's/^@@RESULT@@|//' || true)"
  install_err="$(grep -m1 '^安装失败：' "$TMP_OUT" 2>/dev/null | sed 's/^安装失败：//' || true)"
  [[ -n "$install_err" ]] || install_err="安装程序异常退出（详见日志）"

  if [[ "$INSTALL_RC" != "0" ]]; then
    local hint=""
    case "$INSTALL_RC" in
      40) hint="\n处理建议：重新运行向导并选择一个未被占用的端口。" ;;
      41) hint="\n处理建议：介质可能不完整或被修改。请从源头重新完整复制介质；不要继续使用当前介质。" ;;
      42) hint="\n处理建议：清理磁盘或更换更大磁盘后重新运行安装。" ;;
      45) hint="\n处理建议：为避免数据丢失安装已停止，系统未被改动。请导出诊断包并联系原厂确认唯一数据目录。" ;;
      46) hint="\n处理建议：未发生版本切换，旧版本仍在线。请导出诊断包联系原厂。" ;;
      47|48) hint="\n处理建议：安装程序已自动回滚，旧系统已恢复。请导出诊断包联系原厂。" ;;
      49) hint="\n处理建议：默认业务配置（6 个正式方案/同义词表）导入失败。请重新复制介质后重试；已导入过的系统再次运行不会重复生成。" ;;
    esac
    ui_error "安装失败" "安装失败：$install_err\n$hint\n技术细节已保存：$WIZARD_LOG"
    exit "$INSTALL_RC"
  fi

  local addrs report fw
  export MM_RESULT="$result_json"
  addrs="$("$PY" - <<'PY' 2>/dev/null || true
import json, os
try:
    d = json.loads(os.environ.get("MM_RESULT", "{}"))
    print("\n".join(f"http://{a}:{d.get('port')}" for a in d.get("addresses", [])))
except Exception:
    pass
PY
)"
  report="$(grep -o '安装报告：.*' "$TMP_OUT" | tail -1 | sed 's/^安装报告：//' || true)"
  fw="$("$PY" - <<'PY' 2>/dev/null || true
import json, os
try:
    print(json.loads(os.environ.get("MM_RESULT", "{}")).get("firewall_hint", ""))
except Exception:
    pass
PY
)"
  local pw_line=""
  if [[ "$PW_MODE" == "generated" ]]; then
    if [[ "$IS_TTY" == "1" || -n "$GUI" ]]; then
      pw_line="\n· 初始密码（请立即保存，本页面之后不再显示）：$MM_ADMIN_PASSWORD_SET"
    else
      # 非交互管道场景：密码绝不写入任何输出流/日志，仅指向 root-only 密码文件。
      pw_line="\n· 初始密码已自动生成。出于安全，本输出与安装日志不包含密码明文；请系统管理员以 root 查看：/etc/material_matcher/secret/admin_password.env"
    fi
  elif [[ "$PW_MODE" == "user" ]]; then
    pw_line="\n· 初始密码：您刚才设置的密码"
  else
    pw_line="\n· 管理员密码：保持原有密码不变"
  fi
  local success_text="【安装成功】物料集团码智能匹配平台 ${BUNDLE_VERSION}\n\n· 服务器地址：http://127.0.0.1:$CHOSEN_PORT"
  [[ -n "$addrs" ]] && success_text="$success_text\n· 局域网访问地址：\n$addrs" || success_text="$success_text\n· 未检测到局域网 IPv4 地址：当前仅本机可访问，请确认服务器网络已连接后由维护工具复查"
  SEED_LINE="$(grep -o '"seed_summary": *"[^"]*"' "$TMP_OUT" 2>/dev/null | head -1 | sed 's/.*: *"//; s/"$//' || true)"
  [[ -n "$SEED_LINE" ]] && success_text="$success_text\n· 默认业务数据：$SEED_LINE（6 个正式方案 + 同义词表，登录后可在“匹配方案/数据上传”查看）"
  success_text="$success_text\n· 管理员账号：admin$pw_line\n· 安装报告：${report:-$WIZARD_LOG}\n\n请在浏览器打开上述地址，用 admin 登录；出于安全，系统会要求首次登录时设置新的登录密码。\n登录后可在“系统设置 · 关于”核对版本号 ${BUNDLE_VERSION}。\n\n后续维护（状态/日志/备份/恢复/前端重建）：\n· 图形：双击介质中的 维护物料集团码智能匹配平台.desktop\n· 命令行：以 root 运行 menu.sh 或 mmctl"
  [[ -n "$fw" ]] && success_text="$success_text\n\n注意：$fw"

  if [[ "$GUI" == "zenity" ]]; then
    if zenity --question --title="安装成功" --text="$success_text" --width=640 --yes-label="打开系统" --no-label="稍后再说"; then
      _open_browser "http://127.0.0.1:$CHOSEN_PORT"
    fi
  elif [[ "$GUI" == "kdialog" ]]; then
    kdialog --title "安装成功" --yesno "$success_text" && _open_browser "http://127.0.0.1:$CHOSEN_PORT"
  else
    printf '\n============== 安装成功 ==============\n%b\n' "$success_text"
    printf '\n需要打开浏览器时请在浏览器地址栏输入上述地址。安装向导结束。\n'
  fi
  rm -f "$TMP_OUT"
  exit 0
}

_open_browser() {
  local url="$1" b
  for b in xdg-open firefox google-chrome chromium-browser kylin-firefox; do
    command -v "$b" >/dev/null 2>&1 && { "$b" "$url" >/dev/null 2>&1 & return 0; }
  done
  echo "未能自动打开浏览器，请手动访问：$url"
}

main "$@" 2>&1 | tee -a "$WIZARD_LOG"
rc=${PIPESTATUS[0]}
chmod 600 "$WIZARD_LOG" 2>/dev/null || true
exit "$rc"
