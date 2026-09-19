#!/usr/bin/env bash
# 停用服务（Docker 方式）：只停止并取消本系统自启动，保留数据、镜像与 Docker 软件。
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "需要 root 或 sudo 权限。" >&2; exit 44; }
command -v docker >/dev/null 2>&1 || { echo "未检测到 Docker。" >&2; exit 1; }
PORT="$(grep -m1 '^MM_HOST_PORT=' /etc/material_matcher/docker.env | cut -d= -f2)"
docker update --restart=no material_matcher-app >/dev/null 2>&1 || true
docker stop material_matcher-app >/dev/null 2>&1 || true
if [ -d /opt/material_matcher/docker ]; then
  ( cd /opt/material_matcher/docker && docker compose --env-file /etc/material_matcher/docker.env -f compose.yaml down --no-deps >/dev/null 2>&1 ) || true
fi
echo "已停用：服务已停止且不再随开机启动。数据、镜像与 Docker 软件均未改动。"
echo "恢复运行：在介质 01-Docker方式 目录运行 ./启动Docker安装.sh（升级模式会原地恢复），或 ./重启服务.sh。"
