#!/usr/bin/env bash
# 定时备份（非 Docker 方式）：安装/管理每日自动备份（systemd timer）。
# 用法：
#   ./bk.sh enable [HH:MM]   开启每日备份（默认 02:30），保留最近 14 份
#   ./bk.sh disable          关闭并移除定时任务（已生成的备份文件保留）
#   ./bk.sh run              立即执行一次备份
#   ./bk.sh list             查看已有备份
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "需要 root 或 sudo 权限。" >&2; exit 44; }
OUT_DIR="/var/backups/material_matcher"
RUNNER="/opt/material_matcher/bin/auto-backup.sh"
CMD="${1:-}"

write_runner() {
  mkdir -p /opt/material_matcher/bin
  cat > "$RUNNER" <<'EOS'
#!/usr/bin/env bash
set -euo pipefail
source /etc/material_matcher/storage.env
DATA_DIR="${MATERIAL_MATCHER_DATA_DIR:-/var/lib/material_matcher}"
PY=/opt/material_matcher/current/runtime/bin/python3
OUT="/var/backups/material_matcher"; mkdir -p "$OUT"
ts="$(date +%Y%m%d-%H%M%S)"; dir="mm-auto-backup-$ts"; stage="$(mktemp -d)"
mkdir -p "$stage/$dir"
"$PY" - "$DATA_DIR/meta/material_matcher.db" "$stage/$dir/material_matcher.db" <<'PYX'
import sqlite3, sys
dst = sqlite3.connect(sys.argv[2])
sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True).backup(dst)
PYX
cp -a /etc/material_matcher "$stage/$dir/etc-material_matcher" 2>/dev/null || true
chmod 600 "$stage/$dir/etc-material_matcher/secret/admin_password.env" 2>/dev/null || true
( cd "$stage" && tar -czf "$OUT/$dir.tar.gz" "$dir" )
chmod 600 "$OUT/$dir.tar.gz"; rm -rf "$stage"
ls -1t "$OUT"/mm-auto-backup-*.tar.gz "$OUT"/mm-backup-*.tar.gz 2>/dev/null | tail -n +15 | xargs -r rm -f
echo "$(date '+%F %T') 备份完成：$OUT/$dir.tar.gz" >> /var/log/material_matcher/backup.log
EOS
  chmod 700 "$RUNNER"
}

case "$CMD" in
  enable)
    TIME="${2:-02:30}"
    [[ "$TIME" =~ ^[0-2][0-9]:[0-5][0-9]$ ]] || { echo "时间格式应为 HH:MM，例如 02:30"; exit 1; }
    [ -x "$RUNNER" ] || write_runner
    mkdir -p "$OUT_DIR" /var/log/material_matcher
    cat > /etc/systemd/system/mm-backup-native.service <<'EOF'
[Unit]
Description=MATERIAL_MATCHER daily backup (native)

[Service]
Type=oneshot
ExecStart=/opt/material_matcher/bin/auto-backup.sh
EOF
    cat > /etc/systemd/system/mm-backup-native.timer <<EOF
[Unit]
Description=MATERIAL_MATCHER daily backup timer (native)

[Timer]
OnCalendar=*-*-* $TIME:00
Persistent=true

[Install]
WantedBy=timers.target
EOF
    systemctl daemon-reload
    systemctl enable --now mm-backup-native.timer >/dev/null
    echo "已开启每日备份（$TIME），保留最近 14 份，目录：$OUT_DIR（root-only）。"
    ;;
  disable)
    systemctl disable --now mm-backup-native.timer >/dev/null 2>&1 || true
    rm -f /etc/systemd/system/mm-backup-native.timer /etc/systemd/system/mm-backup-native.service
    systemctl daemon-reload >/dev/null 2>&1 || true
    echo "定时备份已关闭（历史备份文件保留在 $OUT_DIR）。"
    ;;
  run)
    [ -x "$RUNNER" ] || write_runner
    "$RUNNER"; echo "立即备份完成。"
    ;;
  list)
    ls -1t "$OUT_DIR"/*.tar.gz 2>/dev/null | head -20 || echo "暂无备份"
    ;;
  *)
    sed -n '2,10p' "$0" | sed 's/^# \{0,1\}//'
    exit 1
    ;;
esac
