#!/usr/bin/env bash
set -euo pipefail

SERVICE="${MATERIAL_MATCHER_SERVICE_NAME:-material_matcher.service}"
ETC="${MATERIAL_MATCHER_ETC_DIR:-/etc/material_matcher}"
STORAGE_ENV="$ETC/storage.env"
SERVER_ENV="$ETC/server.env"
PASSWORD_ENV="$ETC/secret/admin_password.env"
TOOL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CURRENT_ROOT="${MATERIAL_MATCHER_CURRENT_ROOT:-$(cd "$TOOL_DIR/.." && pwd)}"
LAUNCHER="$CURRENT_ROOT/runtime/bin/material-matcher"
SOURCE_DIR="$CURRENT_ROOT/source/src"
WEB_DIST="$CURRENT_ROOT/web-dist"
MANIFEST="$CURRENT_ROOT/release-manifest.json"

usage() {
  cat <<'EOF'
用法：mmctl.sh <命令> [参数]

  status             查看服务状态
  start              启动服务
  stop               停止服务
  restart            重启服务
  logs               查看并持续跟踪日志
  doctor             执行部署诊断
  diagnostics [目录] 导出诊断包（不包含密码）
  backup [文件]      完整备份数据目录
  restore <文件>     安全恢复到新数据目录；失败自动切回
  rebuild-frontend   离线重新构建前端并原子切换
  version            查看当前版本/构建信息
EOF
}

need_root() {
  if [[ $EUID -eq 0 ]]; then "$@"; else sudo "$@"; fi
}

read_root() {
  local path="$1"
  if [[ -r "$path" ]]; then cat "$path"; else need_root cat "$path"; fi
}

read_env_value() {
  local file="$1" key="$2"
  read_root "$file" 2>/dev/null | sed -n "s/^${key}=//p" | tail -1 | sed "s/^'//;s/'$//"
}

data_dir() {
  local value
  value="$(read_env_value "$STORAGE_ENV" MATERIAL_MATCHER_DATA_DIR)"
  [[ -n "$value" ]] || { echo "无法从 $STORAGE_ENV 读取数据目录" >&2; return 2; }
  printf '%s\n' "$value"
}

port() {
  local value
  value="$(read_env_value "$SERVER_ENV" MATERIAL_MATCHER_PORT)"
  printf '%s\n' "${value:-18080}"
}

run_doctor() {
  [[ -x "$LAUNCHER" ]] || { echo "未找到运行入口：$LAUNCHER" >&2; return 2; }
  need_root bash -c '
    set -a
    source "$1"
    [[ -f "$2" ]] && source "$2"
    [[ -f "$3" ]] && source "$3"
    set +a
    export PYTHONPATH="$4"
    export MATERIAL_MATCHER_CONFIG_DIR="$5"
    export MATERIAL_MATCHER_LOG_DIR="/var/log/material_matcher"
    export MATERIAL_MATCHER_WEB_DIST_DIR="$6"
    export MATERIAL_MATCHER_RELEASE_MANIFEST="$7"
    exec "$8" doctor --require-frontend --require-release-manifest
  ' _ "$STORAGE_ENV" "$SERVER_ENV" "$PASSWORD_ENV" "$SOURCE_DIR" "$ETC" "$WEB_DIST" "$MANIFEST" "$LAUNCHER"
}

health_check() {
  python3 - "$(port)" <<'PY'
import json, sys, urllib.request
p=int(sys.argv[1])
with urllib.request.urlopen(f"http://127.0.0.1:{p}/api/health/ready", timeout=5) as response:
    payload=json.load(response)
if payload.get("status") != "ready":
    raise SystemExit(f"readiness 未通过: {payload}")
print("服务健康检查通过")
PY
}

export_diagnostics() {
  local out_dir="${1:-$PWD}" ts work archive
  ts="$(date +%Y%m%d_%H%M%S)"
  mkdir -p "$out_dir"
  work="$(mktemp -d)"
  archive="$out_dir/material_matcher_diagnostics_${ts}.tar.gz"
  trap 'rm -rf "$work"' RETURN
  systemctl status "$SERVICE" --no-pager >"$work/service-status.txt" 2>&1 || true
  journalctl -u "$SERVICE" -n 500 --no-pager >"$work/service-log.txt" 2>&1 || true
  run_doctor >"$work/doctor.txt" 2>&1 || true
  python3 - "$(port)" >"$work/health.txt" 2>&1 <<'PY' || true
import json, sys, urllib.request
for path in ("/api/health", "/api/health/ready"):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{sys.argv[1]}{path}", timeout=3) as response:
            print(path, json.dumps(json.load(response), ensure_ascii=False))
    except Exception as exc:
        print(path, "ERROR", exc)
PY
  [[ -f "$MANIFEST" ]] && cp "$MANIFEST" "$work/release-manifest.json"
  read_root "$STORAGE_ENV" >"$work/storage.env" 2>/dev/null || true
  read_root "$SERVER_ENV" >"$work/server.env" 2>/dev/null || true
  printf '说明：诊断包不包含 admin 密码文件。\n' >"$work/README.txt"
  tar -czf "$archive" -C "$work" .
  echo "诊断包已生成：$archive"
}

backup_data() {
  local data archive was_active=0
  data="$(data_dir)"
  archive="${1:-$PWD/material_matcher_backup_$(date +%Y%m%d_%H%M%S).tar.gz}"
  systemctl is-active --quiet "$SERVICE" && was_active=1 || true
  [[ $was_active -eq 1 ]] && need_root systemctl stop "$SERVICE"
  trap '[[ $was_active -eq 1 ]] && need_root systemctl start "$SERVICE" >/dev/null 2>&1 || true' RETURN
  need_root tar -czf "$archive" -C "$data" .
  need_root chmod a+r "$archive" || true
  [[ $was_active -eq 1 ]] && need_root systemctl start "$SERVICE"
  trap - RETURN
  echo "备份完成：$archive"
}

restore_data() {
  local archive="$1" old_data parent stage backup_env was_active=0
  [[ -f "$archive" ]] || { echo "备份文件不存在：$archive" >&2; return 2; }
  tar -tzf "$archive" | awk 'BEGIN{bad=0} /^\//{bad=1} /(^|\/)\.\.($|\/)/{bad=1} END{exit bad}' || {
    echo "备份包包含不安全路径，拒绝恢复" >&2; return 2;
  }
  old_data="$(data_dir)"
  parent="$(dirname "$old_data")"
  stage="$parent/material_matcher_restore_$(date +%Y%m%d_%H%M%S)"
  backup_env="$STORAGE_ENV.before_restore_$(date +%Y%m%d_%H%M%S)"
  need_root mkdir -p "$stage"
  need_root tar -xzf "$archive" -C "$stage"
  need_root test -f "$stage/meta/material_matcher.db" || {
    echo "备份中没有 meta/material_matcher.db，拒绝切换" >&2; return 2;
  }
  systemctl is-active --quiet "$SERVICE" && was_active=1 || true
  [[ $was_active -eq 1 ]] && need_root systemctl stop "$SERVICE"
  need_root cp "$STORAGE_ENV" "$backup_env"
  need_root bash -c 'printf "MATERIAL_MATCHER_DATA_MOUNT=%q\nMATERIAL_MATCHER_DATA_DIR=%q\n" "$1" "$2" >"$3"' _ "$parent" "$stage" "$STORAGE_ENV"
  need_root chown -R material_matcher:material_matcher "$stage"
  if ! need_root systemctl start "$SERVICE" || ! health_check; then
    echo "新数据目录启动失败，正在恢复原 storage.env……" >&2
    need_root cp "$backup_env" "$STORAGE_ENV"
    need_root systemctl restart "$SERVICE" || true
    return 2
  fi
  echo "恢复成功。旧数据目录仍保留：$old_data"
  echo "原 storage.env 备份：$backup_env"
}

show_version() {
  if [[ -f "$MANIFEST" ]]; then
    python3 - "$MANIFEST" <<'PY'
import json, sys
m=json.load(open(sys.argv[1], encoding="utf-8"))
print("版本：", m.get("release_version") or "-")
print("构建时间：", m.get("build_time") or m.get("created_at") or "-")
print("Git Commit：", m.get("git_commit") or "-")
mode={"native-source":"原生源码部署","docker-source":"Docker 源码部署"}.get(m.get("deployment_mode"), m.get("deployment_mode") or "-")
print("部署方式：", mode)
PY
  else
    echo "未找到 release-manifest.json：$MANIFEST"
  fi
}

cmd="${1:-}"
case "$cmd" in
  status) systemctl status "$SERVICE" --no-pager || true ;;
  start) need_root systemctl start "$SERVICE"; health_check ;;
  stop) need_root systemctl stop "$SERVICE" ;;
  restart) need_root systemctl restart "$SERVICE"; health_check ;;
  logs) need_root journalctl -u "$SERVICE" -n 200 -f ;;
  doctor) run_doctor ;;
  diagnostics) export_diagnostics "${2:-}" ;;
  backup) backup_data "${2:-}" ;;
  restore) [[ -n "${2:-}" ]] || { usage; exit 2; }; restore_data "$2" ;;
  rebuild-frontend) exec "$TOOL_DIR/rebuild_frontend.sh" ;;
  version) show_version ;;
  *) usage; [[ -n "$cmd" ]] && exit 2 || true ;;
esac
