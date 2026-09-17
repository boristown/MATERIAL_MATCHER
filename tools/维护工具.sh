#!/usr/bin/env bash
set -euo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CTL="$DIR/mmctl.sh"

while true; do
  cat <<'EOF'

物料集团码智能匹配平台 · 维护工具
1. 查看状态
2. 启动服务
3. 停止服务
4. 重启服务
5. 查看日志
6. Doctor 诊断
7. 导出诊断包
8. 备份数据
9. 恢复数据
10. 离线重新构建前端
11. 查看版本
0. 退出
EOF
  read -r -p "请选择：" choice
  case "$choice" in
    1) "$CTL" status ;;
    2) "$CTL" start ;;
    3) "$CTL" stop ;;
    4) "$CTL" restart ;;
    5) "$CTL" logs ;;
    6) "$CTL" doctor ;;
    7) read -r -p "诊断包保存目录（回车=当前目录）：" p; "$CTL" diagnostics "${p:-$PWD}" ;;
    8) read -r -p "备份文件路径（回车=自动命名）：" p; "$CTL" backup "$p" ;;
    9) read -r -p "请输入备份文件完整路径：" p; [[ -n "$p" ]] && "$CTL" restore "$p" ;;
    10) "$CTL" rebuild-frontend ;;
    11) "$CTL" version ;;
    0) exit 0 ;;
    *) echo "输入无效，请重新选择。" ;;
  esac
  read -r -p "按回车继续……" _
done
