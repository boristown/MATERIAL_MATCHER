#!/usr/bin/env bash
# 重启服务（非 Docker 方式）：重启 systemd 服务并确认可用。
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "需要 root 或 sudo 权限。" >&2; exit 44; }
systemctl restart material_matcher.service
PORT="$(grep -m1 '^MATERIAL_MATCHER_PORT=' /etc/material_matcher/server.env | cut -d= -f2)"
for i in $(seq 1 60); do
  code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 3 "http://127.0.0.1:$PORT/api/health" || true)"
  [ "$code" = "200" ] && { echo "服务已重启并可访问：http://127.0.0.1:$PORT"; exit 0; }
  [ $((i % 10)) -eq 0 ] && echo "等待服务就绪…已 ${i} 秒"
  sleep 1
done
echo "服务重启后 60 秒内未就绪，请运行 ./维护工具.sh 查看状态与日志，或导出诊断包联系维护人员。" >&2
exit 1
