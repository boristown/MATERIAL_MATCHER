#!/usr/bin/env bash
# 物料集团码智能匹配平台 · Docker 方式安装向导（CLI-first 终端交互，GUI 可选增强）。
set -uo pipefail

MEDIA="${MM_MEDIA_ROOT:-}"
if [[ -z "$MEDIA" ]]; then MEDIA="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; fi
INSTALL_SH="$MEDIA/install_docker.sh"
MANIFEST="$MEDIA/docker-manifest.json"
WIZARD_LOG="/var/tmp/material_matcher_docker_wizard-$(date +%Y%m%d-%H%M%S).log"
IS_TTY=0; [[ -t 1 ]] && IS_TTY=1
DEFAULT_PORT="18080"
GUI=""
[[ -n "${DISPLAY:-}" ]] && { command -v zenity >/dev/null 2>&1 && GUI=zenity; }

if [[ $EUID -ne 0 ]]; then
  if command -v sudo >/dev/null 2>&1; then
    exec sudo env MM_MEDIA_ROOT="$MEDIA" bash "$MEDIA/docker_wizard.sh" "$@"
  fi
  if command -v pkexec >/dev/null 2>&1; then
    exec pkexec env DISPLAY="${DISPLAY:-}" MM_MEDIA_ROOT="$MEDIA" bash "$MEDIA/docker_wizard.sh" "$@"
  fi
  echo "当前账号没有安装权限：请切换到具备 root/sudo 权限的管理员账号后重新运行 ./启动Docker安装.sh。" >&2
  exit 44
fi

if [[ -x "$MEDIA/bootstrap/python/bin/python3" ]]; then PY="$MEDIA/bootstrap/python/bin/python3"
elif command -v python3 >/dev/null 2>&1; then PY="$(command -v python3)"
else echo "介质缺少 bootstrap 运行环境且本机无 Python，无法继续。"; exit 41; fi

py_json() { "$PY" - "$1" "$2" <<'PY' 2>/dev/null || true
import json, sys
print(json.load(open(sys.argv[1], encoding="utf-8")).get(sys.argv[2], ""))
PY
}
BUNDLE_VERSION="$(py_json "$MANIFEST" release_version)"
BUNDLE_ARCH="$(py_json "$MANIFEST" target_arch)"
ENGINE_VERSION="$(py_json "$MANIFEST" docker_engine_version)"
COMPOSE_VERSION="$(py_json "$MANIFEST" docker_compose_version)"

ui_note() {
  if [[ -n "$GUI" ]]; then zenity --info --title="$1" --text="$2" --width=640
  else printf '\n== %s ==\n%b\n' "$1" "$2"; fi
}
ui_error() {
  if [[ -n "$GUI" ]]; then zenity --error --title="$1" --text="$2" --width=640
  else printf '\n!! %s\n%b\n' "$1" "$2"; fi
  printf '[ERROR] %s %b\n' "$1" "$2" >>"$WIZARD_LOG" 2>/dev/null || true
}
ui_confirm() {  # 0=第一项 3=第二项 9=退出
  if [[ -n "$GUI" ]]; then
    zenity --question --title="$1" --text="$2" --width=640 --yes-label="${3:-继续}" --no-label="${4:-取消}" && return 0
    [[ $? == "1" ]] && return 3 || return 9
  fi
  local a; printf '%b\n请输入 y = %s；n = %s；其它键 = 退出安装（不做任何修改）：' "$2" "${3:-继续}" "${4:-取消}" >&2
  read -r a; case "$a" in y|Y) return 0 ;; n|N) return 3 ;; *) return 9 ;; esac
}
ui_entry() {
  local v; printf '%s [%s]：' "$2" "$3" >&2; read -r v; printf '%s' "${v:-$3}"
}
ui_password() {
  local p1 p2
  printf '%s（至少 10 位，不回显；直接回车改用自动生成）：' "$1" >&2
  IFS= read -rs p1; echo >&2
  [[ -z "$p1" ]] && return 0
  while [[ ${#p1} -lt 10 ]]; do printf '太短，重新输入（回车=自动生成）：' >&2; IFS= read -rs p1; echo >&2; [[ -z "$p1" ]] && return 0; done
  printf '再次输入确认：' >&2; IFS= read -rs p2; echo >&2
  while [[ "$p1" != "$p2" ]]; do printf '两次不一致：' >&2; IFS= read -rs p2; echo >&2; done
  printf '%s' "$p1"
}
generate_password() {
  "$PY" - <<'PY'
import secrets, string
letters, digits = string.ascii_letters, string.digits
pool = [secrets.choice(letters), *[secrets.choice(letters + digits) for _ in range(10)], secrets.choice(digits)]
secrets.SystemRandom().shuffle(pool)
print("".join(pool))
PY
}

CHECKS_OK=1; CHECK_LINES=(); IS_UPGRADE=0; PORT_DEFAULT="$DEFAULT_PORT"

run_env_checks() {
  CHECKS_OK=1; CHECK_LINES=()
  local os_ok=1; grep -Eqi 'kylin|银河麒麟' /etc/os-release 2>/dev/null || os_ok=0
  [[ "$os_ok" == "1" ]] && CHECK_LINES+=("✅ 操作系统：银河麒麟") || { CHECK_LINES+=("❌ 操作系统 —— 本介质仅支持银河麒麟 V10"); CHECKS_OK=0; }
  local arch_now; arch_now="$(uname -m)"
  [[ "$arch_now" == "$BUNDLE_ARCH" ]] && CHECK_LINES+=("✅ CPU 架构：$arch_now（与介质一致）") || { CHECK_LINES+=("❌ CPU 架构 —— 本机 $arch_now / 介质 $BUNDLE_ARCH，请更换匹配介质"); CHECKS_OK=0; }
  local sd=1; [[ -d /run/systemd/system ]] || sd=0
  [[ "$sd" == "1" ]] && CHECK_LINES+=("✅ systemd 服务管理器") || { CHECK_LINES+=("❌ 未运行 systemd，无法管理 Docker 服务"); CHECKS_OK=0; }
  local py=1; [[ -x "$MEDIA/bootstrap/python/bin/python3" ]] || py=0
  [[ "$py" == "1" ]] && CHECK_LINES+=("✅ 安装器自带运行环境") || { CHECK_LINES+=("❌ 缺少 bootstrap 运行环境，请重新复制完整介质"); CHECKS_OK=0; }
  local engine=1; [[ -f "$MEDIA/docker/engine/docker-27.1.1.tgz" && -f "$MEDIA/docker/compose/docker-compose-linux-x86_64" ]] || engine=0
  [[ "$engine" == "1" ]] && CHECK_LINES+=("✅ Docker Engine/Compose 离线组件随介质提供（$ENGINE_VERSION + Compose $COMPOSE_VERSION）") || { CHECK_LINES+=("❌ 缺少 Docker 离线组件"); CHECKS_OK=0; }
  local img=1; [[ -f "$MEDIA/images/$(py_json "$MANIFEST" image_tar | sed 's|^images/||')" ]] || img=0
  [[ "$img" == "1" ]] && CHECK_LINES+=("✅ 应用镜像 tar 完整") || { CHECK_LINES+=("❌ images/ 缺少应用镜像 tar"); CHECKS_OK=0; }
  local seed=1; [[ -d "$MEDIA/seed/business" && -d "$MEDIA/smoke" ]] || seed=0
  [[ "$seed" == "1" ]] && CHECK_LINES+=("✅ 默认业务数据（6 个方案 + 同义词）与验收数据随介质提供") || { CHECK_LINES+=("❌ 缺少 seed/ 或 smoke/"); CHECKS_OK=0; }
  local disk=$(( $(df -Pk / | awk 'NR==2 {print $4}') / 1024 ))
  [[ "$disk" -ge 12288 ]] && CHECK_LINES+=("✅ 磁盘可用约 $((disk/1024)) GB") || { CHECK_LINES+=("❌ 磁盘不足：Docker 方式建议至少 12 GB（镜像+数据）"); CHECKS_OK=0; }

  if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
    CHECK_LINES+=("ℹ️ 检测到本机已有可用 Docker（$(docker version --format '{{.Server.Version}}' 2>/dev/null)）：将直接复用，不会覆盖或清理你的容器/镜像")
  elif command -v docker >/dev/null 2>&1; then
    CHECK_LINES+=("ℹ️ 检测到 docker 命令但守护进程未运行：安装器会尝试复用现有安装并启动；若失败将明确提示")
  else
    CHECK_LINES+=("ℹ️ 本机没有 Docker：将由介质离线安装 Docker Engine $ENGINE_VERSION（不影响系统其它部分）")
  fi
  if [[ -f /etc/material_matcher/docker.env ]]; then
    IS_UPGRADE=1
    PORT_DEFAULT="$(grep -m1 '^MM_HOST_PORT=' /etc/material_matcher/docker.env | cut -d= -f2)"
    CHECK_LINES+=("ℹ️ 检测到已安装的 Docker 方式系统（端口 $PORT_DEFAULT）：本次为升级，业务数据保留")
  else
    CHECK_LINES+=("ℹ️ 未检测到已安装版本：本次为首次安装")
    if [[ -L /opt/material_matcher/current ]]; then
      CHECK_LINES+=("ℹ️ 注意：本机存在“非 Docker 方式”的安装痕迹（/opt/material_matcher/current）。两种方式只能二选一，请确认旧方式已停用，否则安装可能因数据目录约定而停止")
    fi
  fi
}

TMP_OUT=""
FIFO=""
INSTALL_RC=1
run_install() {
  local args=()
  [[ -n "${MM_ADMIN_PASSWORD_SET:-}" ]] && args+=("MM_ADMIN_PASSWORD=$MM_ADMIN_PASSWORD_SET")
  TMP_OUT="$(mktemp /tmp/mm_docker_install.XXXXXX)"
  if [[ -n "$GUI" ]]; then
    FIFO="$(mktemp -u /tmp/mm_docker_prog.XXXXXX)"; mkfifo "$FIFO"
    zenity --progress --title="正在安装（Docker 方式）" --text="准备……" --percentage=0 --no-cancel --width=620 <"$FIFO" &
    local zpid=$!
    exec 5>"$FIFO"
    MM_PROGRESS_ON=1 MM_PORT_USER_CHOICE=1 MM_INSTALL_PORT="$CHOSEN_PORT" MM_ADMIN_PASSWORD_SOURCE="$PW_MODE" \
      env "${args[@]}" bash "$INSTALL_SH" > >(tee "$TMP_OUT" | _forward) 2>&1
    INSTALL_RC=$?
    sleep 1; printf '100\n#安装结束\n' >&5 2>/dev/null || true; exec 5>&-
    wait "$zpid" 2>/dev/null || true; rm -f "$FIFO"
  else
    MM_PROGRESS_ON=1 MM_PORT_USER_CHOICE=1 MM_INSTALL_PORT="$CHOSEN_PORT" MM_ADMIN_PASSWORD_SOURCE="$PW_MODE" \
      env "${args[@]}" bash "$INSTALL_SH" 2>&1 | _relay
    INSTALL_RC=${PIPESTATUS[0]}
  fi
  cat "$TMP_OUT" >>"$WIZARD_LOG" 2>/dev/null || true
}
_forward() {
  while IFS= read -r line; do
    printf '%s\n' "$line"
    case "$line" in
      "@@STEP@@|"*) local r="${line#@@STEP@@|}"; printf '%s\n#%s\n' "${r%%|*}" "${r#*|}" >&5 2>/dev/null || true ;;
    esac
  done
}
_relay() {
  while IFS= read -r line; do
    printf '%s\n' "$line" >>"$TMP_OUT"
    case "$line" in "@@STEP@@|"*|"@@RESULT@@|"*) : ;; *) printf '%s\n' "$line" ;; esac
  done
}

main() {
  [[ -f "$MANIFEST" ]] || { ui_error "无法启动" "当前目录不是完整的 Docker 安装介质（缺少 docker-manifest.json）。请完整复制 01-Docker方式 目录后再运行。"; exit 41; }
  ui_note "欢迎" "欢迎安装【物料集团码智能匹配平台 · Docker 方式】。\n\n全程离线：Docker Engine、Compose、应用镜像、业务数据全部由本介质提供。\n版本 ${BUNDLE_VERSION:-未知}（$BUNDLE_ARCH）。无需你手动配置任何 Docker 命令。"
  ui_note "重要说明" "“Docker 方式”与“非 Docker 方式”是两种二选一的安装方案，只需安装其中一种。\n本向导执行的是 Docker 方式。"
  echo "正在自动检查环境……"
  run_env_checks
  local check_text=""; for line in "${CHECK_LINES[@]}"; do check_text+="$line\n"; done
  ui_note "环境检查" "$check_text"
  [[ "$CHECKS_OK" == "1" ]] || { ui_error "环境检查未通过" "$check_text\n安装未开始，系统未做任何修改。"; exit 43; }

  local port_note="（首次安装默认 18080）"
  [[ "$IS_UPGRADE" == "1" ]] && port_note="（升级：保持当前端口）"
  CHOSEN_PORT=""
  while :; do
    CHOSEN_PORT="$(ui_entry "服务端口" "服务监听端口$port_note" "$PORT_DEFAULT")" || { echo "已取消安装。"; exit 0; }
    [[ "$CHOSEN_PORT" =~ ^[0-9]+$ ]] && (( CHOSEN_PORT >= 1024 && CHOSEN_PORT <= 65535 )) || { ui_error "端口无效" "请输入 1024～65535 的数字端口。"; continue; }
    if (exec 3<>/dev/tcp/127.0.0.1/"$CHOSEN_PORT") 2>/dev/null; then
      if [[ "$IS_UPGRADE" == "1" ]] && grep -qx "MM_HOST_PORT=$CHOSEN_PORT" /etc/material_matcher/docker.env 2>/dev/null; then
        break  # 占用者就是本产品的旧容器：升级会先停容器再复用同一端口
      fi
      ui_error "端口被占用" "端口 $CHOSEN_PORT 已被占用，请选择其它端口。"; continue
    fi
    break
  done

  MM_ADMIN_PASSWORD_SET=""; PW_MODE=""
  if [[ "$IS_UPGRADE" == "1" && -f /etc/material_matcher/secret/admin_password.env ]]; then
    PW_MODE="keep"; ui_note "管理员账号" "升级安装保留现有 admin 账号与密码，不会重置任何登录信息。"
  else
    local rc_pw=0
    ui_confirm "管理员密码" "请选择 admin 初始密码设置方式：\n\ny = 手工输入\nn = 自动生成强密码（推荐给多数用户）" "手工输入" "自动生成" || rc_pw=$?
    if [[ "$rc_pw" == "0" ]]; then
      local pw
      while :; do
        pw="$(ui_password "设置管理员密码")" || { echo "已取消安装。"; exit 0; }
        [[ -z "$pw" ]] && { PW_MODE="generated"; MM_ADMIN_PASSWORD_SET="$(generate_password)"; break; }
        if (( ${#pw} >= 10 )) && [[ "$pw" =~ [A-Za-z] ]] && [[ "$pw" =~ [0-9] ]]; then PW_MODE="user"; MM_ADMIN_PASSWORD_SET="$pw"; break; fi
        ui_error "密码不符合要求" "密码至少 10 位且需同时包含字母和数字（或改选自动生成）。"
      done
    elif [[ "$rc_pw" == "3" ]]; then
      PW_MODE="generated"; MM_ADMIN_PASSWORD_SET="$(generate_password)"
    else
      echo "用户已取消，未对系统做任何修改。"; exit 0
    fi
  fi
  local pw_choice; case "$PW_MODE" in keep) pw_choice="保留现有密码（升级不重置）" ;; user) pw_choice="由您手工设置" ;; *) pw_choice="自动生成" ;; esac
  local mode_text="首次安装"; [[ "$IS_UPGRADE" == "1" ]] && mode_text="升级安装（保留业务数据与配置）"
  local confirm_rc=0
  ui_confirm "确认安装" "即将开始安装（Docker 方式）：\n\n· 版本：${BUNDLE_VERSION}　架构：$BUNDLE_ARCH\n· 方式：$mode_text\n· 服务端口：$CHOSEN_PORT\n· 管理员密码：$pw_choice\n· Docker：${ENGINE_VERSION} + Compose ${COMPOSE_VERSION}（离线组件）\n· 数据：宿主机 /etc /var/lib /var/log/material_matcher（容器删除不丢数据）\n· 配置目录：/opt/material_matcher/docker\n· 完全离线，无需任何手工 Docker 命令\n\n确认开始？" "开始安装" "取消安装" || confirm_rc=$?
  [[ "$confirm_rc" != "0" ]] && { echo "用户已取消，未对系统做任何修改。"; exit 0; }

  run_install
  local err result_json
  result_json="$(grep -m1 '^@@RESULT@@|' "$TMP_OUT" | sed 's/^@@RESULT@@|//' || true)"
  err="$(grep -m1 '^安装失败：' "$TMP_OUT" | sed 's/^安装失败：//' || true)"
  [[ -n "$err" ]] || err="安装程序异常退出（详见日志）"
  if [[ "$INSTALL_RC" != "0" ]]; then
    local hint=""
    case "$INSTALL_RC" in
      40) hint="\n处理建议：重新运行并选择其它端口。" ;;
      41) hint="\n处理建议：介质不完整或被修改，请重新完整复制 01-Docker方式 目录。" ;;
      42) hint="\n处理建议：清理磁盘或换更大磁盘（Docker 方式建议 12 GB 以上）。" ;;
      46) hint="\n处理建议：Docker 安装/启动失败。请查看安装日志；安装器不会改动系统其它服务。" ;;
      47|48) hint="\n处理建议：安装器已尝试自动回滚旧镜像；请确认旧系统可用后导出诊断包联系原厂。" ;;
      49) hint="\n处理建议：默认业务配置导入失败，请重新复制介质后重试（已导入过的内容不会重复生成）。" ;;
      50) hint="\n处理建议：请先与系统管理员确认现有 Docker 的升级计划；安装器不会静默替换客户 Docker。" ;;
    esac
    ui_error "安装失败" "安装失败：$err$hint\n技术细节：$WIZARD_LOG"
    exit "$INSTALL_RC"
  fi

  local pw_line addrs report seed fw
  case "$PW_MODE" in
    generated) if [[ "$IS_TTY" == "1" || -n "$GUI" ]]; then pw_line="\n· 初始密码（请立即保存）：$MM_ADMIN_PASSWORD_SET"; else pw_line="\n· 初始密码已自动生成；本输出不含明文，请用 root 查看 /etc/material_matcher/secret/admin_password.env"; fi ;;
    user) pw_line="\n· 初始密码：您刚才设置的密码" ;;
    *) pw_line="\n· 管理员密码：保持原有密码不变" ;;
  esac
  export MM_RESULT="$result_json"
  addrs="$(printf '%s' "$result_json" | "$PY" - <<'PYE' 2>/dev/null || true
import json, sys
d = json.loads(sys.stdin.read() or "{}")
print("\n".join("http://{}:{}".format(a, d.get("port")) for a in d.get("addresses", [])))
PYE
)"
  seed="$(printf '%s' "$result_json" | "$PY" - <<'PYE' 2>/dev/null || true
import json, sys
print(json.loads(sys.stdin.read() or "{}").get("seed_summary", ""))
PYE
)"
  fw="$(printf '%s' "$result_json" | "$PY" - <<'PYE' 2>/dev/null || true
import json, sys
print(json.loads(sys.stdin.read() or "{}").get("firewall_hint", ""))
PYE
)"
  report="$(grep -m1 '安装报告：' "$TMP_OUT" | sed 's/^安装报告：//' || true)"
  local text="【安装成功】物料集团码智能匹配平台 $BUNDLE_VERSION（Docker 方式）\n\n· 服务器地址：http://127.0.0.1:$CHOSEN_PORT"
  [[ -n "$addrs" ]] && text="$text\n· 局域网访问：\n$addrs" || text="$text\n· 未检测到局域网 IPv4 地址：仅本机可访问，请确认网络后查看"
  text="$text\n· 管理员账号：admin$pw_line\n· 默认业务数据：${seed:-已导入}\n· 安装报告：${report:-$WIZARD_LOG}\n\n业务数据保存在宿主机 /etc、/var/lib、/var/log/material_matcher —— 删除或重建容器都不会丢数据。\n\n后续维护：以 root 运行本目录 ./维护工具-Docker.sh\n客户电脑若是 Windows 7 且页面异常，请安装介质根目录《客户端浏览器-Win7》中的 Firefox ESR。"
  [[ -n "$fw" ]] && text="$text\n\n注意：$fw"
  if [[ -n "$GUI" ]]; then
    zenity --info --title="安装成功" --text="$text" --width=660 && true
  else
    printf '\n============== 安装成功 ==============\n%b\n' "$text"
  fi
  rm -f "$TMP_OUT"
  exit 0
}

main "$@" 2>&1 | tee -a "$WIZARD_LOG"
rc=${PIPESTATUS[0]}
chmod 600 "$WIZARD_LOG" 2>/dev/null || true
exit "$rc"
