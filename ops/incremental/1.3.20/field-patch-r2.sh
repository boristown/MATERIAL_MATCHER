#!/usr/bin/env bash
# r2：启动成功的草稿不再出现在第二步（点"继续/草稿"落到上传页的问题）
# 用法：bash field-patch-r2.sh [容器名=material_matcher-app] ；NATIVE 用：bash field-patch-r2.sh native
set -euo pipefail
CTR="${1:-material_matcher-app}"
F=/opt/material_matcher/current/app/material_matcher/services/task_service.py
PATCHER='
import sys, pathlib
f = pathlib.Path(sys.argv[1]); s = f.read_text(encoding="utf-8")
a = "        return self.get_task(task_id)"
mark = "        with self.repo.connect() as consumed:\n            consumed.execute(\"UPDATE task_drafts SET current_step=99 WHERE draft_id=?\", (draft_id,))\n"
if mark in s: print("A-ALREADY")
else:
    assert s.count(a) == 1, "锚点异常"
    s = s.replace(a, mark + a, 1); print("A-OK")
import re
old = re.compile(r"SELECT \* FROM task_drafts WHERE (source_file_id IS NOT NULL(?: OR catalog_version_id IS NOT NULL)?) ORDER BY updated_at DESC")
if "current_step<90" in s: print("B-ALREADY")
else:
    assert old.search(s), "SQL 锚点未找到"
    s = old.sub(r"SELECT * FROM task_drafts WHERE current_step<90 AND (\1) ORDER BY updated_at DESC", s, count=1)
    print("B-OK")
f.write_text(s, encoding="utf-8")
'
if [ "$CTR" = "native" ]; then
  cp -n "$F" "$F.bak-r2"
  /opt/material_matcher/current/runtime/bin/python3 -c "$PATCHER" "$F" || { cp "$F.bak-r2" "$F"; exit 1; }
  /opt/material_matcher/current/runtime/bin/python3 -m py_compile "$F" || { cp "$F.bak-r2" "$F"; exit 1; }
  systemctl restart material_matcher; PORT=$(sed -n 's/^MATERIAL_MATCHER_PORT=//p' /etc/material_matcher/server.env | head -1); PORT=${PORT:-18080}
else
  docker exec "$CTR" cp "$F" "$F.bak-r2" 2>/dev/null || true
  docker exec -i "$CTR" /opt/material_matcher/current/runtime/bin/python3 -c "$PATCHER" "$F" < /dev/null || { docker exec "$CTR" cp "$F.bak-r2" "$F"; exit 1; }
  docker exec "$CTR" /opt/material_matcher/current/runtime/bin/python3 -m py_compile "$F" || { docker exec "$CTR" cp "$F.bak-r2" "$F"; exit 1; }
  docker restart "$CTR"; PORT=$(docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$CTR" | sed -n 's/^MATERIAL_MATCHER_PORT=//p' | head -1); PORT=${PORT:-18080}
fi
sleep 12
curl -s --max-time 20 "http://127.0.0.1:${PORT}/api/health" && echo && echo "R2-DONE（已启动过的草稿不再出现在第二步；历史遗留草稿行不受影响仍可继续）"
echo "回滚：docker exec $CTR cp $F.bak-r2 $F && docker restart $CTR（native 同理）"
