#!/usr/bin/env bash
# 卸载服务（Docker 方式）：仅卸载 MATERIAL_MATCHER 自身（容器、本项目镜像、compose 配置、定时备份）。
# 绝不卸载 Docker 软件；默认保留全部业务数据与配置（重装/升级可继续使用）。
# 用法：./卸载服务.sh              → 卸载应用，保留数据
#       ./卸载服务.sh --purge-data → 额外删除业务数据与配置（两次 yes 确认）
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "需要 root 或 sudo 权限。" >&2; exit 44; }
command -v docker >/dev/null 2>&1 || { echo "未检测到 Docker，本系统可能已卸载。" >&2; exit 1; }
PURGE=""
[[ "${1:-}" == "--purge-data" ]] && PURGE=1
IMAGE_TAG="$(grep -m1 '^MM_IMAGE=' /etc/material_matcher/docker.env 2>/dev/null | cut -d= -f2 || true)"
DATA_REAL="$(readlink -f /var/lib/material_matcher 2>/dev/null || true)"
LOG_REAL="$(readlink -f /var/log/material_matcher 2>/dev/null || true)"

if [ -d /opt/material_matcher/docker ]; then
  ( cd /opt/material_matcher/docker && docker compose --env-file /etc/material_matcher/docker.env -f compose.yaml down 2>/dev/null ) || true
fi
docker rm -f material_matcher-app >/dev/null 2>&1 || true
for tag in "${IMAGE_TAG:-}" material-matcher-app:previous; do
  [ -n "$tag" ] && docker rmi "$tag" >/dev/null 2>&1 || true
done
systemctl stop mm-backup.timer >/dev/null 2>&1 || true
systemctl disable mm-backup.timer mm-backup.service >/dev/null 2>&1 || true
rm -f /etc/systemd/system/mm-backup.timer /etc/systemd/system/mm-backup.service
systemctl daemon-reload >/dev/null 2>&1 || true
rm -rf /opt/material_matcher/docker

echo "应用已卸载。Docker 软件与其原有容器/镜像未受影响：$(docker --version)"
if [ -n "$PURGE" ]; then
  echo "！！警告：即将删除全部业务数据（账号、上传、任务、结果、索引）与配置，且不可恢复。"
  printf "确认删除请输入 yes（其它任意键放弃）："; read -r a1
  [ "${a1:-}" = "yes" ] || { echo "已放弃删除。数据保留在：$DATA_REAL"; exit 0; }
  printf "再次输入 yes 确认："; read -r a2
  [ "${a2:-}" = "yes" ] || { echo "已放弃删除。"; exit 0; }
  [ -n "$DATA_REAL" ] && rm -rf "$DATA_REAL"
  [ -n "$LOG_REAL" ] && rm -rf "$LOG_REAL"
  rm -rf /var/lib/material_matcher /var/log/material_matcher /etc/material_matcher
  echo "数据与配置已全部删除。"
else
  echo "数据保留：${DATA_REAL:-/var/lib/material_matcher}；配置保留：/etc/material_matcher。"
  echo "重新安装：运行介质内 ./启动Docker安装.sh 即可在原数据上恢复。"
fi
