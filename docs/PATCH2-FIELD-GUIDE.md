# PATCH2 现场修复手册：并列候选自动取第一条（解除同分封锁）

## ⚡ 极简版（手敲 ~70 字符，两条命令搞定）

Docker 客户机：
```bash
docker exec material_matcher-app sh -c 'cd /opt/material_matcher/current/app/material_matcher; sed -i s/000001/-1/g\ services/decision_calibration_service.py; sed -i s/score\ ==\ first/score\ >\ first/ matching/engine.py'
docker restart material_matcher-app
```
NATIVE 客户机（无容器）：
```bash
cd /opt/material_matcher/current/app/material_matcher
sed -i s/000001/-1/g services/decision_calibration_service.py
sed -i s/score\ ==\ first/score\ >\ first/ matching/engine.py
systemctl restart material_matcher
```
原理：前者把 5 处"同分并列"判据改成永假（`< -1`），后者把引擎并列守卫的 `score == first` 改成 `score > first`（降序下恒不成立）。只碰 2 个文件、纯字符级替换、可用 `.bak-mini` 或下方完整手册回滚。
（若嫌手敲引号转义麻烦：直接跑包内 `bash apply_mini.sh`，30 秒，自动备份+编译校验+失败回滚。）

完整分步流程（备份/编辑/回注/验证/回滚）如下 ↓

适用：客户机以 **Docker 介质安装**（V1.3.14 盘）后的修复；全程 root。
效果：新任务与阈值重判定中，"Top1/Top2 同分不同码"不再强制转人工，自动取第一条。
依赖：仅适用于 1.3.14/1.3.15 任一形态（若已打过则自动跳过，见第 6 步说明）。

## 0. 准备（运维机上）
把 patch2 包拷到客户服务器（U盘/光盘均可），例如放 /root：
```bash
cd /root && tar -xzf patch2-1.3.15.tar.gz -C /root/patch2 && cd /root/patch2
```

## 1. 定位容器
```bash
docker ps --format '{{.Names}}  {{.Image}}  {{.Status}}' | grep material
```
记下容器名，下文以 `CTR=material_matcher-app` 为例（安装介质默认此名）：
```bash
export CTR=material_matcher-app
```

## 2. 从容器拉出 4 个文件并备份（宿主机留存双份）
```bash
APP=/opt/material_matcher/current/app/material_matcher
BK=/root/patch2/backup-$(date +%Y%m%d-%H%M%S); mkdir -p $BK/{domain,matching,services}
for f in domain/models.py matching/engine.py services/decision_calibration_service.py services/match_service.py; do
  docker cp "$CTR:$APP/$f" "$BK/$f"
done
ls -R $BK    # 确认 4 个文件在
```

## 3. 编辑（在拉出的副本上做，共 4 个文件、3 类改动）
```bash
cd /root/patch2
# 3a. engine.py：并列守卫加一个条件（精确匹配替换，防止手误）
python3 - <<'PY'
import pathlib
p = pathlib.Path("work") ; 
PY
mkdir -p work/domain work/matching work/services
cp $BK/domain/models.py $BK/matching/engine.py 2>/dev/null; cp $BK/domain/models.py work/domain/ && cp $BK/matching/engine.py work/matching/ && cp $BK/services/decision_calibration_service.py $BK/services/match_service.py work/services/
python3 mini.py work
```
说明：`mini.py` 就是包内的自动编辑器，效果等价于手敲以下 4 处（想手敲就用 vi work/...）：
- `work/matching/engine.py`：`Backward-compatible ambiguity protection` 段的 `if ( status == "MATCHED"` 后插入一行
  `        and getattr(config.decision, "tie_break", "top1") == "review"`
- `work/services/decision_calibration_service.py`：全部 5 处 `... ) < 0.000001` 改成 `... ) < -1`
  （等价命令：`sed -i 's/\.000001/-1/; s/< -1\.000/ < -1/' ...` 不建议手打，直接跑 mini.py）
- `work/services/match_service.py`：`if ambiguous:` → `if False and ambiguous:`；`if critical or ambiguous:` → `if critical or (ambiguous and False):`
- `work/domain/models.py`（可选，保留后台开关）：DecisionConfig 里 `review_enabled: bool = True` 下一行加 `    tie_break: str = "top1"`
若某处提示"pattern missing / expect 不符"= 该机已打过补丁，**中止即可，无需再改**（第 6 步重启照常做也无害）。

## 4. 语法自检（宿主机没有 python3 时，第 5 步容器内还会再查一次）
```bash
python3 -m py_compile work/domain/models.py work/matching/engine.py work/services/decision_calibration_service.py work/services/match_service.py && echo SYNTAX-OK
```

## 5. 送回容器 + 重启
```bash
for f in domain/models.py matching/engine.py services/decision_calibration_service.py services/match_service.py; do
  docker cp "work/$f" "$CTR:$APP/$f"
done
docker exec "$CTR" /opt/material_matcher/current/runtime/bin/python3 -m py_compile \
  $APP/domain/models.py $APP/matching/engine.py $APP/services/decision_calibration_service.py $APP/services/match_service.py && echo CONTAINER-COMPILE-OK
docker restart "$CTR"
```

## 6. 验证生效
```bash
P=$(docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' "$CTR" | sed -n 's/^MATERIAL_MATCHER_PORT=//p' | head -1); P=${P:-18080}
sleep 10; curl -s http://127.0.0.1:$P/api/health
docker exec "$CTR" grep -c 'tie_break' $APP/matching/engine.py      # 输出 ≥1 即已生效
```
页面验证：发起匹配（方案阈值改为 ≤80，例如 73；最高分 83.9 时 65≈全自动）→ 第三步出现"已自动匹配"。
若输出 0：说明该机此前已用 patch1（5 文件版）修复过，功能已具备，不必重复操作。

## 7. 回滚（任何异常时）
```bash
for f in domain/models.py matching/engine.py services/decision_calibration_service.py services/match_service.py; do
  docker cp "$BK/$f" "$CTR:$APP/$f"
done
docker restart "$CTR"
```

## 8. 备注
- 本改动不动数据库、不动前端、不动种子；对历史任务可在第三步"全局判定调参"改阈值后点「应用并生成版本」立即生效。
- NATIVE（非 Docker）介质安装的客户机：把上面每条 `docker cp $CTR:`/`docker exec $CTR` 换成宿主机直接操作同路径（/opt/material_matcher/current/app/material_matcher），最后 `systemctl restart material_matcher`；或直接跑包内 `bash apply_mini.sh --native`。
