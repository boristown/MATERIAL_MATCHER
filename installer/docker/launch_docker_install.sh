#!/usr/bin/env bash
# Docker 方式安装入口：终端执行 ./run.sh（CLI-first）。
set -u
cd "$(dirname "$0")" || exit 1
if [[ ! -f docker_wizard.sh ]]; then
  echo "缺少 docker_wizard.sh：d 目录不完整，请重新完整复制。" >&2
  exit 1
fi
if command -v locale >/dev/null 2>&1 && locale -a 2>/dev/null | grep -qi '^C\.utf-\?8$'; then
  export LC_ALL=C.UTF-8
fi
if [[ $EUID -eq 0 ]]; then
  exec bash docker_wizard.sh "$@"
fi
if command -v sudo >/dev/null 2>&1; then
  exec sudo env MM_MEDIA_ROOT="$PWD" bash "$PWD/docker_wizard.sh" "$@"
fi
if command -v pkexec >/dev/null 2>&1; then
  exec pkexec env DISPLAY="${DISPLAY:-}" MM_MEDIA_ROOT="$PWD" bash "$PWD/docker_wizard.sh" "$@"
fi
echo "需要 root 或 sudo 管理员权限。请用管理员账号运行：sudo ./run.sh" >&2
exit 44
