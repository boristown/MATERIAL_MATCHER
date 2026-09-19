#!/usr/bin/env bash
# 重启服务（Docker 方式）：重启 MATERIAL_MATCHER 应用容器并确认可用。不触碰 Docker 软件。
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "需要 root 或 sudo 权限。" >&2; exit 44; }
PORT="$(grep -m1 '^MM_HOST_PORT=' /etc/material_matcher/docker.env 2>/dev/null | cut -d= -f2 || true)"
[ -n "${PORT:-}" ] || { echo "未找到 /etc/material_matcher/docker.env，本系统可能未安装。" >&2; exit 1; }
if ! docker inspect material_matcher-app >/dev/null 2>&1; then
  echo "容器不存在，尝试经 compose 拉起…"
  ( cd /opt/material_matcher/docker && docker compose --env-file /etc/material_matcher/docker.env -f compose.yaml up -d )
else
  docker restart material_matcher-app >/dev/null
fi
for i in $(seq 1 60); do
  code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 "http://127.0.0.1:$PORT/api/health" || true)"
  [ "$code" = "200" ] && { echo "服务已重启并可访问：http://127.0.0.1:$PORT"; exit 0; }
  [ $((i % 10)) -eq 0 ] && echo "等待服务就绪…已 ${i} 秒"
  sleep 1
done
echo "服务重启后 60 秒内未就绪，请运行 ./维护工具-Docker.sh status 与 logs 查看，或导出诊断包联系维护人员。" >&2
exit 1
