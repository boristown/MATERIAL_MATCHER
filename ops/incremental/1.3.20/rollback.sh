#!/usr/bin/env bash
set -uo pipefail
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
BK=$(ls -dt /var/lib/material_matcher/backups/incremental-1.3.20-* 2>/dev/null | head -1)
[ -n "$BK" ] || { echo "未找到增量备份目录"; exit 2; }
echo "回滚自: $BK (模式 $MODE)"
if [ "$MODE" = docker ]; then
  docker exec "$CTR" sh -c "rm -rf /opt/material_matcher/current/app/material_matcher /opt/material_matcher/current/web/dist && cp -a $BK/material_matcher /opt/material_matcher/current/app/material_matcher && cp -a $BK/dist /opt/material_matcher/current/web/dist"
  docker restart "$CTR"
else
  rm -rf /opt/material_matcher/current/app/material_matcher /opt/material_matcher/current/web/dist
  cp -a "$BK/material_matcher" /opt/material_matcher/current/app/ 2>/dev/null || cp -a "$BK/live_app" /opt/material_matcher/current/app/material_matcher
  cp -a "$BK/dist/." /opt/material_matcher/current/web/dist/ 2>/dev/null || cp -a "$BK/live_dist/." /opt/material_matcher/current/web/dist/
  systemctl restart material_matcher
fi
sleep 12
V=$("$PKG_DIR/scripts/version-check" $([ "$MODE" = docker ] && echo --docker "$CTR" || echo --native) 2>/dev/null || true); [ -z "$V" ] && V=UNKNOWN
echo "已回滚到版本: ${V:-UNKNOWN}"
