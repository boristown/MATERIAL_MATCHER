#!/usr/bin/env bash
# clean.sh —— 物料集团码智能匹配平台 磁盘清理工具（以 root 运行）
# 用途：回收“不再被任何任务/目录/草稿引用的上传与结果文件”、过期临时分块、过旧的自动备份。
# 安全：默认 dry-run 只报告不删除；实际删除需显式 --apply。只操作数据目录内部文件，绝不触碰程序与数据库。
# Docker 方式与 Native 方式通用（数据都在宿主机 /var/lib/material_matcher）。
set -euo pipefail
APPLY=0
TMP_DAYS=7
KEEP_BACKUPS=7
DATA="${MM_DATA_DIR:-/var/lib/material_matcher}"
for a in "$@"; do
  case "$a" in
    --apply) APPLY=1 ;;
    --tmp-days=*) TMP_DAYS="${a#*=}" ;;
    --keep-backups=*) KEEP_BACKUPS="${a#*=}" ;;
    --data=*) DATA="${a#*=}" ;;
    -h|--help) sed -n '2,8p' "$0"; exit 0 ;;
    *) echo "未知参数：$a（支持 --apply --tmp-days=N --keep-backups=N --data=PATH）"; exit 2 ;;
  esac
done
DB="$DATA/meta/material_matcher.db"
[[ -f "$DB" ]] || { echo "未找到数据库：$DB（确认以 root 运行且系统已安装本平台）"; exit 3; }
PY="$(command -v /opt/material_matcher/current/runtime/bin/python3 || command -v "$(dirname "$0")/bootstrap/python/bin/python3" || command -v python3)"
[[ "$APPLY" == "1" ]] && echo ">>> 模式：实际删除（--apply）" || echo ">>> 模式：预演（dry-run，未删除任何文件；确认后加 --apply）"
"$PY" - "$DB" "$DATA" "$APPLY" "$TMP_DAYS" "$KEEP_BACKUPS" <<'PY'
import json, sqlite3, sys, time
from pathlib import Path
db, data, apply_, tmp_days, keep_b = sys.argv[1], Path(sys.argv[2]), sys.argv[3] == "1", int(sys.argv[4]), int(sys.argv[5])
c = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
referenced = set()
for sql in (
    "SELECT source_file_id FROM tasks",
    "SELECT source_file_id FROM task_drafts",
    "SELECT file_id FROM task_input_assets",
    "SELECT source_file_id FROM catalog_versions",
):
    try:
        referenced |= {str(r[0]) for r in c.execute(sql) if r[0]}
    except sqlite3.Error:
        pass
# workspace_target / 结果导出引用藏在 JSON 文本里：按 file_id 十六进制串扫一遍
hexids = {r[0] for r in c.execute("SELECT file_id FROM files")}
jsonblobs = []
for sql in ("SELECT config_document FROM task_drafts", "SELECT document FROM profile_versions", "SELECT source_payload FROM match_items LIMIT 20000"):
    try:
        jsonblobs += [str(r[0] or "") for r in c.execute(sql)]
    except sqlite3.Error:
        pass
for blob in jsonblobs:
    for fid in hexids:
        if fid in referenced:
            continue
        if fid in blob:
            referenced.add(fid)
files = c.execute("SELECT file_id, original_name, stored_path, size_bytes, created_at FROM files").fetchall()
trash = data / ".trash" / time.strftime("%Y%m%d-%H%M%S")
freed = 0; kept_missing = 0
paths = {}
for fid, name, sp, size, created in files:
    if fid in referenced:
        continue
    p = Path(str(sp))
    try:
        p.resolve().relative_to(data.resolve())
    except Exception:
        continue
    if not p.is_file():
        kept_missing += 1
        continue
    # 同一路径可能已被多条“去重引用”行共享：只要还有一个被引用者就保留
    shared_referenced = any(str(o[2]) == str(p) and o[0] in referenced for o in files)
    if shared_referenced:
        continue
    freed += int(size or 0)
    print(f"  孤立文件 {name}  {int(size or 0):,}B  {p.name}")
    if apply_:
        trash.mkdir(parents=True, exist_ok=True)
        p.rename(trash / p.name)
print(f"孤立文件: {'移入回收目录 ' + str(trash) if apply_ else '待回收'} {freed:,} 字节（回收目录内的内容可在确认无误后由管理员删除）" if apply_ else f"可回收约 {freed:,} 字节（--apply 将移入 .trash 回收目录，不直接物理删除）")
# 过期临时分块
n = 0
for base in (data / "tmp", data / "uploads" / "tmp", data / "results" / "tmp"):
    if base.is_dir():
        for f in base.iterdir():
            if f.is_file() and time.time() - f.stat().st_mtime > tmp_days * 86400:
                n += 1
                if apply_:
                    f.unlink()
print(f"超过 {tmp_days} 天的上传临时分块: {n} 个（{'已删除' if apply_ else '可删除，--apply 生效'}）")
# 旧备份轮转（保留最近 keep_b 份）
bdir = data / "backups"
if bdir.is_dir():
    bl = sorted([f for f in bdir.iterdir() if f.is_file() and f.suffix == ".db"], key=lambda x: x.name, reverse=True)
    for old in bl[keep_b:]:
        print(f"  旧备份 {old.name}")
        if apply_:
            old.unlink()
    print(f"备份目录保留最近 {keep_b} 份（当前 {len(bl)} 份）")
try:
    du = c.execute("SELECT count(*) FROM files WHERE status='UPLOADING'").fetchone()[0]
    if du:
        print(f"提示：仍有 {du} 条未完成上传记录（在系统内重新上传即可完成，不占额外空间——相同内容不会再重复存储）")
except sqlite3.Error:
    pass
if not apply_:
    print("以上为预演结果。确认无误后执行：./clean.sh --apply")
PY
df -h "$DATA" | tail -1
echo "完成。建议频率：每季度一次；先不带 --apply 看清单。"
