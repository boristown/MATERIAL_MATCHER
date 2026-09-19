#!/usr/bin/env bash
# 停用服务（非 Docker 方式）：停止 systemd 服务并取消开机自启；保留程序、数据与配置。
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "需要 root 或 sudo 权限。" >&2; exit 44; }
systemctl stop material_matcher.service 2>/dev/null || true
systemctl disable material_matcher.service 2>/dev/null || true
echo "已停用：服务停止且不再开机自启。数据保留在 /var/lib/material_matcher，配置保留在 /etc/material_matcher。"
echo "恢复运行：./rst.sh 或运行介质内 ./run.sh（升级模式原地恢复自启）。"
