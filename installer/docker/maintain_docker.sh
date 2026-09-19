#!/usr/bin/env bash
# 物料集团码智能匹配平台（Docker 方式）维护工具：中文菜单。
# 只操作 material_matcher 项目自身容器/镜像/目录；绝不触碰其它容器，不做任何 prune。
set -uo pipefail

CONTAINER="material_matcher-app"
COMPOSE_HOME="/opt/material_matcher/docker"
OPT="/opt/material_matcher"
ETC="/etc/material_matcher"
VAR="/var/lib/material_matcher"
LOG="/var/log/material_matcher"
RUNTIME="/opt/material_matcher/current/runtime/bin"

[[ $EUID -eq 0 ]] || { echo "请用 root 或 sudo 运行维护工具。" >&2; exit 44; }
docker ps >/dev/null 2>&1 || { echo "无法连接 Docker 守护进程。" >&2; exit 1; }

IMAGE() { grep -m1 '^MM_IMAGE=' "$ETC/docker.env" | cut -d= -f2; }
PORT() { grep -m1 '^MM_HOST_PORT=' "$ETC/docker.env" | cut -d= -f2; }

cmd_status() {
  echo "容器状态：$(docker inspect -f '{{.State.Status}}（开机重启策略 {{.HostConfig.RestartPolicy.Name}}）' "$CONTAINER" 2>/dev/null || echo 未找到)"
  echo "镜像：$(IMAGE)"
  echo "地址：http://127.0.0.1:$(PORT)"
  curl -s --max-time 3 "http://127.0.0.1:$(PORT)/api/health" || echo "health 请求失败：服务可能未启动"
}
cmd_version() { curl -s --max-time 5 "http://127.0.0.1:$(PORT)/api/health"; echo; readlink -f "$OPT/current" 2>/dev/null; }
cmd_doctor() {
  docker exec -e MATERIAL_MATCHER_MODEL_ROOT=/opt/material_matcher/model \
    "$CONTAINER" "$RUNTIME/material-matcher" doctor --require-frontend --require-embedding --require-release-manifest
}
cmd_backup() {
  local out="${1:-/var/backups/material_matcher}" ts dir stage
  mkdir -p "$out"
  ts="$(date +%Y%m%d-%H%M%S)"; dir="mm-docker-backup-$ts"; stage="$(mktemp -d)"
  mkdir -p "$stage/$dir"
  docker exec -i "$CONTAINER" "$RUNTIME/python3" - "$VAR/tmp/backup-$ts.db" <<'PY' || { rm -rf "$stage"; echo "备份失败：容器内数据库一致性备份未完成"; return 1; }
import sqlite3, sys
dst = sqlite3.connect(sys.argv[1])
sqlite3.connect("/var/lib/material_matcher/meta/material_matcher.db").backup(dst)
PY
  [[ -s "$VAR/tmp/backup-$ts.db" ]] || { rm -rf "$stage"; echo "备份失败：容器内未生成一致性备份"; return 1; }
  cp -f "$VAR/tmp/backup-$ts.db" "$stage/$dir/material_matcher.db"
  rm -f "$VAR/tmp/backup-$ts.db"
  cp -a "$ETC" "$stage/$dir/etc-material_matcher" 2>/dev/null || true
  chmod 600 "$stage/$dir/etc-material_matcher/secret/admin_password.env" 2>/dev/null || true
  ( cd "$stage" && tar -czf "$out/$dir.tar.gz" "$dir" )
  rm -rf "$stage"; chmod 600 "$out/$dir.tar.gz"
  echo "备份完成：$out/$dir.tar.gz"
}
cmd_verify() {
  local file="${1:-}" stage db
  [[ -n "$file" && -f "$file" ]] || { echo "请提供备份文件路径" >&2; return 1; }
  stage="$(mktemp -d)"; tar -xzf "$file" -C "$stage" || { rm -rf "$stage"; echo "备份包解压失败"; return 1; }
  db="$(find "$stage" -name material_matcher.db | head -1)"
  [[ -n "$db" ]] || { rm -rf "$stage"; echo "备份包中未找到数据库"; return 1; }
  cp -f "$db" "$VAR/tmp/verify-$$.db"
  docker exec -i "$CONTAINER" "$RUNTIME/python3" - "$VAR/tmp/verify-$$.db" <<'PY'
import sqlite3, sys
con = sqlite3.connect(sys.argv[1])
ok = con.execute("PRAGMA integrity_check").fetchone()[0]
tables = len(list(con.execute("SELECT name FROM sqlite_master WHERE type='table'")))
assert ok == "ok", ok
print(f"备份验证通过：integrity=ok，表数量={tables}")
PY
  rc=$?
  rm -f "$VAR/tmp/verify-$$.db"; rm -rf "$stage"
  return $rc
}
cmd_restore() {
  local file="$1" stage db ts
  [[ -f "$file" ]] || { echo "备份文件不存在" >&2; return 1; }
  cmd_verify "$file" || { echo "备份验证未通过，拒绝恢复"; return 1; }
  stage="$(mktemp -d)"; tar -xzf "$file" -C "$stage"
  db="$(find "$stage" -name material_matcher.db | head -1)"
  ts="$(date +%Y%m%d-%H%M%S)"
  [[ -f "$VAR/meta/material_matcher.db" ]] && cp -a "$VAR/meta/material_matcher.db" "$VAR/meta/material_matcher.db.pre-restore-$ts"
  docker stop "$CONTAINER" >/dev/null 2>&1 || true
  cp -f "$db" "$VAR/meta/material_matcher.db"
  local cfg; cfg="$(find "$stage" -maxdepth 2 -type d -name 'etc-material_matcher' | head -1)"
  if [[ -n "$cfg" ]]; then
    cp -a "$cfg/." "$ETC/" 2>/dev/null || true
    chmod 700 "$ETC/secret" 2>/dev/null || true
    chmod 600 "$ETC/secret/admin_password.env" 2>/dev/null || true
  fi
  rm -rf "$stage"
  docker rm -f "$CONTAINER" >/dev/null 2>&1 || true
  if ! ( cd "$COMPOSE_HOME" && docker compose --env-file "$ETC/docker.env" -f compose.yaml up -d ); then
    echo "恢复后启动失败；恢复前数据库已留存为 $VAR/meta/material_matcher.db.pre-restore-$ts"; return 1
  fi
  echo "恢复完成；恢复前数据库已留存为 material_matcher.db.pre-restore-$ts"
}
cmd_export_diag() {
  local out="${1:-/var/tmp}" ts dir stage
  ts="$(date +%Y%m%d-%H%M%S)"; dir="mm-docker-diagnostics-$ts"; stage="/var/tmp/$dir"; mkdir -p "$stage"
  {
    date '+%F %T'
    docker ps -a --filter "name=$CONTAINER" --format '{{.Names}} | {{.Status}} | {{.Image}}'
    docker logs --tail 300 "$CONTAINER" 2>&1
    echo "端口：$(PORT)"
    curl -s --max-time 3 "http://127.0.0.1:$(PORT)/api/health/ready" || true
    df -h "$OPT" "$VAR" 2>/dev/null
  } >"$stage/diagnostics.txt" 2>&1
  cp "$ETC/docker.env" "$ETC/storage.env" "$stage/" 2>/dev/null || true
  [[ -d "$LOG/install-reports" ]] && cp "$LOG/install-reports"/docker-install-*.txt "$stage/" 2>/dev/null || true
  chmod -R go-rwx "$stage"
  tar -C /var/tmp -czf "$out/$dir.tar.gz" "$dir"; rm -rf "$stage"
  echo "诊断包已导出：$out/$dir.tar.gz（不含密码/会话/客户文件）"
}

menu_loop() {
  while :; do
    cat >&2 <<'EOF'
==== 物料集团码智能匹配平台 · 维护（Docker 方式）====
 1) 查看状态    2) 启动服务    3) 停止服务    4) 重启服务
 5) 查看日志    6) 健康诊断    7) 查看版本    8) 备份数据
 9) 验证最近备份 10) 从备份恢复（输入文件路径）
11) 导出诊断包   0) 退出
EOF
    printf '请选择：' >&2; read -r c
    case "$c" in
      1) cmd_status; read -r -p "回车返回菜单…" _ ;;
      2) docker start "$CONTAINER" ;;
      3) docker stop "$CONTAINER" ;;
      4) docker restart "$CONTAINER" ;;
      5) docker logs --tail 120 "$CONTAINER" 2>&1 | tail -60; read -r -p "回车返回菜单…" _ ;;
      6) cmd_doctor; read -r -p "回车返回菜单…" _ ;;
      7) cmd_version ;;
      8) cmd_backup ;;
      9) latest=$(ls -1t /var/backups/material_matcher/mm-docker-backup-*.tar.gz 2>/dev/null | head -1)
         [[ -n "$latest" ]] && cmd_verify "$latest" || echo "暂无备份" ;;
      10) printf '备份文件完整路径：' >&2; read -r f; [[ -n "$f" ]] && cmd_restore "$f" ;;
      11) cmd_export_diag ;;
      0) break ;;
    esac
  done
}

if [[ -n "${1:-}" ]]; then
  case "$1" in
    status) cmd_status ;;
    start) docker start "$CONTAINER" ;;
    stop) docker stop "$CONTAINER" ;;
    restart) docker restart "$CONTAINER" ;;
    logs) docker logs --tail "${2:-120}" "$CONTAINER" 2>&1 ;;
    doctor) cmd_doctor ;;
    version) cmd_version ;;
    backup) cmd_backup "${2:-}" ;;
    verify) cmd_verify "${2:-}" ;;
    restore) cmd_restore "${2:-}" ;;
    export) cmd_export_diag "${2:-}" ;;
    menu) menu_loop ;;
    *) echo "用法：menu.sh {menu|status|start|stop|restart|logs|doctor|version|backup|verify|restore|export}" >&2; exit 1 ;;
  esac
else
  menu_loop
fi
