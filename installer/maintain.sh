#!/usr/bin/env bash
# 维护入口：图形菜单（zenity/kdialog）或终端中文菜单。
set -u
MMCTL="/opt/material_matcher/bin/mmctl"
[[ -x "$MMCTL" ]] || MMCTL="$(command -v mmctl || true)"
[[ -n "$MMCTL" ]] || { echo "未找到维护工具：系统可能尚未安装。请先运行 启动安装.sh 完成安装。" >&2; exit 1; }
if [[ $EUID -ne 0 ]]; then
  if command -v pkexec >/dev/null 2>&1; then
    exec pkexec env DISPLAY="${DISPLAY:-}" XAUTHORITY="${XAUTHORITY:-}" bash "$0" "$@"
  fi
  exec sudo bash "$0" "$@"
fi

GUI=""
if [[ -n "${DISPLAY:-}" ]]; then
  command -v zenity >/dev/null 2>&1 && GUI=zenity
  [[ -z "$GUI" ]] && command -v kdialog >/dev/null 2>&1 && GUI=kdialog
fi

run_menu_entry() {  # $1 名称 $2 命令串
  local out
  out="$(eval "$2" 2>&1)"; local rc=$?
  echo "----- $1 -----" >&2; echo "$out" >&2
  case "$GUI" in
    zenity) zenity --info --title="$1" --text="$out" --width=700 ;;
    kdialog) kdialog --title "$1" --passiveinfo "$out" ;;
    *) echo "$out"; printf '按回车返回菜单…' >&2; read -r _ ;;
  esac
  return $rc
}

if [[ -n "$GUI" ]]; then
  while :; do
    choice=$(case "$GUI" in
      zenity) zenity --list --title="物料集团码智能匹配平台 · 维护" --width=520 --height=420 --column=操作 \
        "查看状态" "启动服务" "停止服务" "重启服务" "查看最近日志" "健康诊断" "查看版本" "备份数据" "验证最近备份" "导出诊断包" "退出" ;;
      kdialog) kdialog --menu "请选择维护操作" "status" "查看状态" "start" "启动服务" "stop" "停止服务" "restart" "重启服务" "logs" "查看最近日志" "doctor" "健康诊断" "version" "查看版本" "backup" "备份数据" "export" "导出诊断包" "quit" "退出" ;;
    esac) || break
    case "${choice##*|}" in
      查看状态|status) run_menu_entry "查看状态" "$MMCTL status" ;;
      启动服务|start) run_menu_entry "启动服务" "$MMCTL start" ;;
      停止服务|stop) run_menu_entry "停止服务" "$MMCTL stop" ;;
      重启服务|restart) run_menu_entry "重启服务" "$MMCTL restart" ;;
      查看最近日志|logs) run_menu_entry "最近日志" "$MMCTL logs 120" ;;
      健康诊断|doctor) run_menu_entry "健康诊断" "$MMCTL doctor" ;;
      查看版本|version) run_menu_entry "版本" "$MMCTL version" ;;
      备份数据|backup) run_menu_entry "备份" "$MMCTL backup" ;;
      验证最近备份) latest=$(ls -1t /var/backups/material_matcher/mm-backup-*.tar.gz 2>/dev/null | head -1); [[ -n "$latest" ]] && run_menu_entry "验证备份" "$MMCTL verify $latest" ;;
      导出诊断包|export) run_menu_entry "诊断包" "$MMCTL export" ;;
      退出|quit) break ;;
    esac
  done
  exit 0
fi

while :; do
  cat >&2 <<'EOF'
==== 物料集团码智能匹配平台 · 维护菜单 ====
 1) 查看状态        2) 启动服务
 3) 停止服务        4) 重启服务
 5) 查看最近日志    6) 健康诊断
 7) 查看版本        8) 备份数据
 9) 验证最近备份   10) 从备份恢复（需备份文件路径）
11) 导出诊断包     12) 前端离线重建（高级）
 0) 退出
EOF
  printf '请选择：' >&2; read -r c
  case "$c" in
    1) run_menu_entry "状态" "$MMCTL status" ;;
    2) run_menu_entry "启动" "$MMCTL start" ;;
    3) run_menu_entry "停止" "$MMCTL stop" ;;
    4) run_menu_entry "重启" "$MMCTL restart" ;;
    5) run_menu_entry "日志" "$MMCTL logs 120" ;;
    6) run_menu_entry "诊断" "$MMCTL doctor" ;;
    7) run_menu_entry "版本" "$MMCTL version" ;;
    8) run_menu_entry "备份" "$MMCTL backup" ;;
    9) latest=$(ls -1t /var/backups/material_matcher/mm-backup-*.tar.gz 2>/dev/null | head -1)
       [[ -n "$latest" ]] && "$MMCTL" verify "$latest" || echo "暂无备份。" ;;
    10) printf '备份文件路径：' >&2; read -r f; [[ -n "$f" ]] && "$MMCTL" restore "$f" ;;
    11) run_menu_entry "诊断包" "$MMCTL export" ;;
    12) run_menu_entry "前端重建" "$MMCTL rebuild-frontend" ;;
    0) break ;;
  esac
done
