#!/usr/bin/env bash
# r2（最终版·无缩进手敲友好）：启动过的草稿不再出现在第二步，编辑中的草稿不受影响
# 手敲 4 步见 README；本脚本为等价自动版。用法：bash field-patch-r2.sh [容器名]；native 传 native
set -euo pipefail
CTR="${1:-material_matcher-app}"
F=/opt/material_matcher/current/app/material_matcher/services/task_service.py
O='WHERE source_file_id IS NOT NULL OR catalog_version_id IS NOT NULL ORDER'
N='WHERE (source_file_id IS NOT NULL OR catalog_version_id IS NOT NULL) AND NOT EXISTS(SELECT 1 FROM tasks t WHERE t.source_file_id=task_drafts.source_file_id AND t.created_at>=task_drafts.created_at) ORDER'
RUN() { if [ "${1:-}" = "host" ]; then python3 - "$F" "$O" "$N" <<'PY'
import sys, shutil
p, o, n = sys.argv[1:4]
s = open(p).read()
if "NOT EXISTS" in s: print("ALREADY")
else:
    assert s.count(o) == 1
    shutil.copy(p, p + ".bak-r2"); open(p, "w").write(s.replace(o, n, 1)); print("R2-OK")
PY
else
    docker exec "$CTR" /opt/material_matcher/current/runtime/bin/python3 - "$F" "$O" "$N" <<'PY'
import sys, shutil
p, o, n = sys.argv[1:4]
s = open(p).read()
if "NOT EXISTS" in s: print("ALREADY")
else:
    assert s.count(o) == 1
    shutil.copy(p, p + ".bak-r2"); open(p, "w").write(s.replace(o, n, 1)); print("R2-OK")
PY
fi; }
if [ "$CTR" = "native" ]; then RUN host; systemctl restart material_matcher; else docker cp "$0" "$CTR:/tmp/r2.sh" 2>/dev/null || true; RUN docker; docker restart "$CTR"; fi
sleep 12; PORT=$(docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$CTR" 2>/dev/null | sed -n 's/^MATERIAL_MATCHER_PORT=//p' | head -1); PORT=${PORT:-18080}
curl -s --max-time 20 "http://127.0.0.1:${PORT}/api/health" && echo && echo "R2-DONE"
