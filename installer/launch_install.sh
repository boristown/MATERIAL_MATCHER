#!/usr/bin/env bash
# 双击/终端启动安装入口：普通安装人员只需要运行本脚本。
set -u
cd "$(dirname "$0")" || exit 1
if [[ ! -f install_wizard.sh ]]; then
  echo "缺少 install_wizard.sh：安装目录不完整，请重新复制完整安装介质。" >&2
  exit 1
fi
if command -v locale >/dev/null 2>&1 && locale -a 2>/dev/null | grep -qi '^C\.utf-\?8$'; then
  export LC_ALL=C.UTF-8
fi
if [[ $EUID -eq 0 ]]; then
  exec bash install_wizard.sh "$@"
fi
if command -v pkexec >/dev/null 2>&1; then
  exec pkexec env DISPLAY="${DISPLAY:-}" XAUTHORITY="${XAUTHORITY:-}" MM_MEDIA_ROOT="$PWD" bash "$PWD/install_wizard.sh" "$@"
fi
if command -v sudo >/dev/null 2>&1; then
  exec sudo env MM_MEDIA_ROOT="$PWD" bash "$PWD/install_wizard.sh" "$@"
fi
echo "当前账号没有系统管理员权限，无法安装。请联系管理员，使用具备 sudo/root 权限的账号重新运行。" >&2
exit 44
