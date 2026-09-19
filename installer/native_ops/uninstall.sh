#!/usr/bin/env bash
# 卸载服务（非 Docker 方式）：仅卸载 MATERIAL_MATCHER 自身（systemd 单元与程序目录），
# 默认保留全部业务数据与配置（重装可继续使用）。
# 用法：./卸载服务.sh              → 卸载应用，保留数据
#       ./卸载服务.sh --purge-data → 额外删除业务数据与配置（两次 yes 确认）
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "需要 root 或 sudo 权限。" >&2; exit 44; }
PURGE=""
[[ "${1:-}" == "--purge-data" ]] && PURGE=1
DATA_DIR="$(grep -m1 '^MATERIAL_MATCHER_DATA_DIR=' /etc/material_matcher/storage.env 2>/dev/null | cut -d= -f2 | tr -d '"' || true)"
VAR_REAL="$(readlink -f /var/lib/material_matcher 2>/dev/null || true)"
systemctl disable --now material_matcher.service >/dev/null 2>&1 || true
systemctl disable --now mm-backup-native.timer mm-backup-native.service >/dev/null 2>&1 || true
rm -f /etc/systemd/system/material_matcher.service /etc/systemd/system/mm-backup-native.timer /etc/systemd/system/mm-backup-native.service
systemctl daemon-reload >/dev/null 2>&1 || true
rm -rf /opt/material_matcher
echo "应用已卸载（系统服务与程序文件）。"
if [ -n "$PURGE" ]; then
  echo "！！警告：即将删除全部业务数据与配置，且不可恢复。"
  printf "确认删除请输入 yes（其它任意键放弃）："; read -r a1
  [ "${a1:-}" = "yes" ] || { echo "已放弃删除。"; exit 0; }
  printf "再次输入 yes 确认："; read -r a2
  [ "${a2:-}" = "yes" ] || { echo "已放弃删除。"; exit 0; }
  [ -n "$VAR_REAL" ] && rm -rf "$VAR_REAL"
  rm -rf /var/lib/material_matcher /var/log/material_matcher /etc/material_matcher
  echo "数据与配置已全部删除。"
else
  echo "数据保留：${VAR_REAL:-/var/lib/material_matcher}；配置保留：/etc/material_matcher。"
  echo "重新安装：运行 ./启动本地安装.sh 即可在原数据上恢复。"
fi
