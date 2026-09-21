#!/usr/bin/env bash
# PATCH2 极简手敲补丁（等价 v1.3.15 默认行为）：并列同分候选自动取第一条
# 用法（root）：
#   NATIVE：  bash PATCH2-MINIMAL.sh
#   DOCKER ：  docker cp PATCH2-MINIMAL.sh <容器>:/tmp/ && docker exec <容器> bash /tmp/PATCH2-MINIMAL.sh && docker restart <容器>
#   （容器默认名 material_matcher-app）
# 内容 = 2 条 sed（模式唯一性已扫描验证，仅命中 5+1 处目标判断）：
#   1) 阈值重判定路径：把 5 处“同分并列”判据 < 0.000001 改为 < -1（永假）
#   2) 新任务路径：引擎并列守卫 score == first 改为 score > first（降序候选下恒不成立）
# 回滚：git checkout 对应文件，或用完整介质重跑 run.sh 覆盖。
set -euo pipefail
APP=/opt/material_matcher/current/app/material_matcher
[ -d "$APP" ] || { echo "路径不存在：$APP（Docker 请在容器内执行）"; exit 2; }
cp "$APP/services/decision_calibration_service.py" "$APP/services/decision_calibration_service.py.bak-p2"
cp "$APP/matching/engine.py" "$APP/matching/engine.py.bak-p2"
sed -i 's/000001/-1/g'            "$APP/services/decision_calibration_service.py"
sed -i 's/score == first/score > first/' "$APP/matching/engine.py"
/opt/material_matcher/current/runtime/bin/python3 -m py_compile \
  "$APP/services/decision_calibration_service.py" "$APP/matching/engine.py" && echo "PATCH2-MINIMAL OK（重启服务后生效）"
