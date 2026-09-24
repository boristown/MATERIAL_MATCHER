#!/usr/bin/env bash
# 现场补丁 r1：未定稿时点"下载/生成结果"不再 409，改为自动按当前判定生成后导出（支持中间结果）
# 用法（root，宿主机）：bash field-patch-r1.sh [容器名，默认 material_matcher-app]；NATIVE 机器加参数 native
set -euo pipefail
CTR="${1:-material_matcher-app}"
F=/opt/material_matcher/current/app/material_matcher/api/_legacy_app.py
if [ "$CTR" = "native" ]; then
  cp -n "$F" "$F.bak-r1"
  python3 - "$F" <<'PY'
import sys, pathlib
f = pathlib.Path(sys.argv[1]); s = f.read_text(encoding="utf-8")
old = 'if not file_id: raise DomainError("TASK_STATE_CONFLICT","任务尚未生成最终结果",status_code=409)'
new = 'if not file_id: file_id=matches.finalize(task_id,allow_unresolved_review=True).get("result_file_id")'
if new in s: print("ALREADY-PATCHED")
else:
    assert old in s, "目标行未找到（版本不匹配，中止）"
    f.write_text(s.replace(old, new), encoding="utf-8"); print("PATCHED")
PY
  /opt/material_matcher/current/runtime/bin/python3 -m py_compile "$F" || { cp "$F.bak-r1" "$F"; exit 1; }
  systemctl restart material_matcher
else
  docker exec -i "$CTR" /opt/material_matcher/current/runtime/bin/python3 - "$F" <<'PY'
import sys, pathlib, shutil
f = pathlib.Path(sys.argv[1]); shutil.copy2(f, "/tmp/_legacy_app.bak-r1")
s = f.read_text(encoding="utf-8")
old = 'if not file_id: raise DomainError("TASK_STATE_CONFLICT","任务尚未生成最终结果",status_code=409)'
new = 'if not file_id: file_id=matches.finalize(task_id,allow_unresolved_review=True).get("result_file_id")'
if new in s: print("ALREADY-PATCHED")
else:
    assert old in s, "目标行未找到（版本不匹配，中止）"
    f.write_text(s.replace(old, new), encoding="utf-8"); print("PATCHED")
PY
  docker exec "$CTR" /opt/material_matcher/current/runtime/bin/python3 -m py_compile "$F" || { docker exec "$CTR" cp /tmp/_legacy_app.bak-r1 "$F"; exit 1; }
  docker restart "$CTR"
fi
echo "等待服务..."; sleep 12
P=$(docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$CTR" 2>/dev/null | sed -n 's/^MATERIAL_MATCHER_PORT=//p' | head -1); P=${P:-18080}
curl -s --max-time 20 "http://127.0.0.1:${P}/api/health" && echo && echo "R1-DONE"
echo "回滚：docker exec $CTR cp /tmp/_legacy_app.bak-r1 $F && docker restart $CTR（native：cp \$F.bak-r1 \$F 后 systemctl restart）"
