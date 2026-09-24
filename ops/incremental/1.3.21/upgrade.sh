#!/usr/bin/env bash
# MATERIAL_MATCHER 增量升级 1.3.20-to-1.3.21（自动识别 Docker/Native；失败可用 rollback.sh 恢复）
set -uo pipefail
PKG="$(cd "$(dirname "$0")" && pwd)"; cd "$PKG"
MODE=auto; CTR=material_matcher-app
case "${1:-}" in
  --docker) MODE=docker; CTR="${2:-material_matcher-app}" ;;
  --native) MODE=native ;;
  "") ;;
  *) CTR="$1" ;;
esac
if [ "$MODE" = auto ]; then
  if command -v docker >/dev/null 2>&1 && docker ps --format '{{.Names}}' 2>/dev/null | grep -qx "$CTR"; then MODE=docker; else MODE=native; fi
fi
echo "== 模式: $MODE =="
./scripts/precheck $([ "$MODE" = docker ] && echo --docker "$CTR" || echo --native) || { rc=$?; [ $rc = 3 ] && exit 0; exit $rc; }
./scripts/backup "$MODE" "$CTR" || { echo "备份失败，中止（未做任何变更）"; exit 6; }
BK=$(ls -dt /var/lib/material_matcher/backups/incremental-1.3.21-* 2>/dev/null | head -1)
echo "备份目录: $BK"
echo "== 安装新增离线依赖 xlsxwriter（纯 Python wheel，不联网） =="
if [ "$MODE" = docker ]; then
  docker cp vendor "$CTR:/tmp/p7_vendor"
  docker exec "$CTR" /opt/material_matcher/current/runtime/bin/python3 -m pip install --no-index --find-links /tmp/p7_vendor xlsxwriter >/dev/null 2>&1
  docker exec "$CTR" /opt/material_matcher/current/runtime/bin/python3 -c "import xlsxwriter" || { echo "依赖安装失败，中止（未替换应用）"; exit 9; }
  docker exec "$CTR" rm -rf /tmp/p7_vendor
else
  /opt/material_matcher/current/runtime/bin/python3 -m pip install --no-index --find-links "$PKG/vendor" xlsxwriter >/dev/null 2>&1
  /opt/material_matcher/current/runtime/bin/python3 -c "import xlsxwriter" || { echo "依赖安装失败，中止（未替换应用）"; exit 9; }
fi
if [ "$MODE" = docker ]; then
  docker cp payload/backend/material_matcher "$CTR:/tmp/p7_material_matcher"
  docker cp payload/web "$CTR:/tmp/p7_dist"
  docker exec "$CTR" sh -c "rm -rf /tmp/p7_old && mv /opt/material_matcher/current/app/material_matcher /tmp/p7_old && mv /tmp/p7_material_matcher /opt/material_matcher/current/app/material_matcher && mv /opt/material_matcher/current/web/dist /tmp/p7_old_dist && mv /tmp/p7_dist /opt/material_matcher/current/web/dist"
  docker cp scripts/sync_meta.py "$CTR:/tmp/sync_meta.py"
  docker exec "$CTR" /opt/material_matcher/current/runtime/bin/python3 /tmp/sync_meta.py 1.3.21
  docker exec "$CTR" rm -f /tmp/sync_meta.py
  docker restart "$CTR"
  docker exec "$CTR" /opt/material_matcher/current/runtime/bin/python3 -m py_compile /opt/material_matcher/current/app/material_matcher/__init__.py || { echo "编译失败，自动回滚"; docker exec "$CTR" sh -c "rm -rf /opt/material_matcher/current/app/material_matcher /opt/material_matcher/current/web/dist && mv /tmp/p7_old /opt/material_matcher/current/app/material_matcher && mv /tmp/p7_old_dist /opt/material_matcher/current/web/dist"; docker restart "$CTR"; exit 7; }
else
  mv /opt/material_matcher/current/app/material_matcher "$BK/live_app"
  mv /opt/material_matcher/current/web/dist "$BK/live_dist"
  cp -a payload/backend/material_matcher /opt/material_matcher/current/app/material_matcher
  mkdir -p /opt/material_matcher/current/web/dist
  cp -a payload/web/. /opt/material_matcher/current/web/dist/
  /opt/material_matcher/current/runtime/bin/python3 scripts/sync_meta.py 1.3.21
  /opt/material_matcher/current/runtime/bin/python3 -m py_compile /opt/material_matcher/current/app/material_matcher/__init__.py || { echo "编译失败，自动回滚"; rm -rf /opt/material_matcher/current/app/material_matcher /opt/material_matcher/current/web/dist && mv "$BK/live_app" /opt/material_matcher/current/app/material_matcher && mv "$BK/live_dist" /opt/material_matcher/current/web/dist; systemctl restart material_matcher; exit 7; }
  systemctl restart material_matcher || service material_matcher restart
fi
echo "== 等待服务起来并做健康检查 =="
MATERIAL_MATCHER_PORT="" ./scripts/health-check $([ "$MODE" = docker ] && echo --docker "$CTR") || { echo "健康检查失败：执行 ./rollback.sh $([ "$MODE" = docker ] && echo --docker "$CTR") 回滚"; exit 8; }
echo "UPGRADE-SUCCESS 1.3.21（数据库为启动期自动前向迁移，无需手工动作）"
