#!/usr/bin/env bash
# 定时备份（Docker 方式）：为 MATERIAL_MATCHER 安装/管理每日自动备份（systemd timer）。
# 用法：
#   ./定时备份.sh enable [HH:MM]   开启每日备份（默认 02:30），保留最近 14 份
#   ./定时备份.sh disable          关闭并移除定时任务（已生成的备份文件保留）
#   ./定时备份.sh run              立即执行一次备份
#   ./定时备份.sh list             查看已有备份
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "需要 root 或 sudo 权限。" >&2; exit 44; }
OUT_DIR="/var/backups/material_matcher"
RUNNER="/opt/material_matcher/backup-run.sh"
CMD="${1:-}"

write_runner() {
  cat > "$RUNNER" <<'EOS'
#!/usr/bin/env bash
set -euo pipefail
OUT="/var/backups/material_matcher"; mkdir -p "$OUT"
ts="$(date +%Y%m%d-%H%M%S)"; dir="mm-auto-backup-$ts"; stage="$(mktemp -d)"
mkdir -p "$stage/$dir"
docker exec -i material_matcher-app /opt/material_matcher/current/runtime/bin/python3 - "$dir.sqlite" <<'PY'
import sqlite3, sys
dst = sqlite3.connect("/tmp/" + sys.argv[1])
sqlite3.connect("/var/lib/material_matcher/meta/material_matcher.db").backup(dst)
PY
docker cp "material_matcher-app:/tmp/$dir.sqlite" "$stage/$dir/material_matcher.db"
docker exec material_matcher-app rm -f "/tmp/$dir.sqlite"
cp -a /etc/material_matcher "$stage/$dir/etc-material_matcher" 2>/dev/null || true
chmod 600 "$stage/$dir/etc-material_matcher/secret/admin_password.env" 2>/dev/null || true
( cd "$stage" && tar -czf "$OUT/$dir.tar.gz" "$dir" )
chmod 600 "$OUT/$dir.tar.gz"; rm -rf "$stage"
ls -1t "$OUT"/mm-auto-backup-*.tar.gz "$OUT"/mm-docker-backup-*.tar.gz 2>/dev/null | tail -n +15 | xargs -r rm -f
echo "$(date '+%F %T') 备份完成：$OUT/$dir.tar.gz" >> /var/log/material_matcher/backup.log
EOS
  chmod 700 "$RUNNER"
}

case "$CMD" in
  enable)
    TIME="${2:-02:30}"
    [[ "$TIME" =~ ^[0-2][0-9]:[0-5][0-9]$ ]] || { echo "时间格式应为 HH:MM，例如 02:30"; exit 1; }
    docker inspect material_matcher-app >/dev/null 2>&1 || { echo "服务未安装/未运行，请先完成安装。"; exit 1; }
    mkdir -p "$OUT_DIR" /var/log/material_matcher
    write_runner
    cat > /etc/systemd/system/mm-backup.service <<'EOF'
[Unit]
Description=MATERIAL_MATCHER daily backup

[Service]
Type=oneshot
ExecStart=/opt/material_matcher/backup-run.sh
EOF
    cat > /etc/systemd/system/mm-backup.timer <<EOF
[Unit]
Description=MATERIAL_MATCHER daily backup timer

[Timer]
OnCalendar=*-*-* $TIME:00
Persistent=true

[Install]
WantedBy=timers.target
EOF
    systemctl daemon-reload
    systemctl enable --now mm-backup.timer >/dev/null
    echo "已开启每日备份（$TIME），保留最近 14 份，目录：$OUT_DIR（root-only）。"
    ;;
  disable)
    systemctl disable --now mm-backup.timer >/dev/null 2>&1 || true
    rm -f /etc/systemd/system/mm-backup.timer /etc/systemd/system/mm-backup.service
    systemctl daemon-reload >/dev/null 2>&1 || true
    echo "定时备份已关闭（历史备份文件保留在 $OUT_DIR）。"
    ;;
  run)
    [ -x "$RUNNER" ] || write_runner
    "$RUNNER"
    echo "立即备份完成。"
    ;;
  list)
    ls -1t "$OUT_DIR"/*.tar.gz 2>/dev/null | head -20 || echo "暂无备份"
    ;;
  *)
    sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'
    exit 1
    ;;
esac
