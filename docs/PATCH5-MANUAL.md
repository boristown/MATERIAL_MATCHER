# PATCH5 手敲现场版（无文件导入时使用）
效果=patch5-1.3.16.tar.gz：①屏蔽 STEP2"未命名方案"空草稿 ②默认自动匹配阈值 88→50（后端）③版本标记 1.3.16。
原则：**每行敲完看结果，符合预期再下一行**；任何一步异常即停，回滚命令见文末。

## 0. 进容器（后续命令都很短）
```
docker exec -it material_matcher-app bash
```

## 1. 环境
```
A=/opt/material_matcher/current
cd $A/app/material_matcher
```

## 2. 屏蔽空草稿
```
sed -i 's|task_drafts ORDER|task_drafts WHERE source_file_id IS NOT NULL ORDER|' services/task_service.py
grep -c "IS NOT NULL" services/task_service.py        # 期望输出：1
```

## 3. 后端默认阈值 → 50
```
sed -i 's/default=88/default=50/' domain/models.py
sed -i 's/threshold", 88/threshold", 50/' services/decision_calibration_service.py
grep -c default=50 domain/models.py                   # 期望输出：≥1
```

## 4. 版本标记 → 1.3.16
```
sed -i 's/1.3.1[0-9]/1.3.16/' __init__.py
```

## 5. 语法保险（无输出=通过）
```
python3 -m py_compile services/task_service.py domain/models.py services/decision_calibration_service.py
```

## 6. 清理存量空草稿（python 里逐行敲）
```
python3
import sqlite3
c=sqlite3.connect('/var/lib/material_matcher/meta/material_matcher.db')
print(c.execute('DELETE FROM task_drafts WHERE source_file_id IS NULL').rowcount)
c.commit();print('ok')
exit
```

## 7. 回宿主机重启 + 终验
```
exit
docker restart material_matcher-app
sleep 15
curl -s http://127.0.0.1:18080/api/health            # 期望包含 1.3.16
```

## 8. 收尾（纯点击，2 分钟）
六个已发布方案里旧阈值 88：匹配方案→编辑→自动匹配阈值改 **50**→校验并发布（A001~A006 各一次）。
或跑任务时在 STEP3「全局判定调参」输 50 → 应用并生成版本（即时生效，不动方案）。

## 本手敲版与 patch5 的差异
- 不改前端打包文件：新建空草稿界面初值仍显示 88（仅显示，不影响引擎默认 50 的实际判定）。
- 不写入 seed（下次新装仍 88）——外网 v1.3.16 已修正，未来介质自然带上。

## 回滚
```
sed -i 's/ WHERE source_file_id IS NOT NULL ORDER/ ORDER/' services/task_service.py
sed -i 's/default=50/default=88/' domain/models.py
sed -i 's/threshold", 50/threshold", 88/' services/decision_calibration_service.py
sed -i 's/1.3.16/1.3.15/' __init__.py
```
然后 `docker restart material_matcher-app`。

---

## 9. 追加分支（2026-09-21 现场实测反馈后补充）
手敲完①-⑧后若仍见两处"没变化"，按下述处理（均为已预期行为，非敲错）：

### 9.1 新草稿界面仍显示 88 —— 前端打包文件未改所致
手敲版有意不动 dist；界面初值写死在打包 JS 内，且向导提交时会把界面值带上，故必须补这一条（容器内）：
```
cd /opt/material_matcher/current/web/dist/assets
grep -o "success_threshold:[0-9]*" index-*.js | sort | uniq -c   # 记录此处输出
sed -i 's/success_threshold:88/success_threshold:50/g' index-*.js
```
完成后浏览器必须 **Ctrl+F5 强刷**（打包文件指纹变了，旧缓存会骗人）。

### 9.2 第二步仍见"未命名方案" —— 两选一诊断
```
grep -c "IS NOT NULL" /opt/material_matcher/current/app/material_matcher/services/task_service.py
```
- 输出 `0`：②号 sed 未生效或未重启 → 宿主机 `docker restart material_matcher-app` 后复查。
- 输出 `1`：过滤器已生效，剩余行是**带文件的历史草稿**（过滤器只隐藏空壳）。交付阶段无进行中草稿时可一次性清空草稿表（任务历史在 tasks 表，完全不受影响）：
```
python3 -c "import sqlite3;c=sqlite3.connect('/var/lib/material_matcher/meta/material_matcher.db');print(c.execute('DELETE FROM task_drafts').rowcount);c.commit()"
```

### 9.3 终验标准（对齐外网 v1.3.16 全量版）
- 新建草稿阈值初值显示 `50`；
- STEP2 列表无"未命名方案"空壳；
- 跑一单样本：并列行自动落 Top1、大量"已自动匹配"；
- `curl -s http://127.0.0.1:18080/api/health` → `1.3.16`。

> 外网同步记录：v1.3.16 全量介质 `mm-1.3.16`（SHA 9b5af975…）已含本节全部效果（前端初值/过滤器/默认 50/种子），线上与客户测试床均已部署并清理历史空草稿（线上删 11 条）。后续新装一律用 v1.3.16 包，无需任何手敲。

## 10. 现有方案阈值改 50（已实测修订版，勿用早前草稿版）
> 早前给过的 B 方案 REPL 有一处 API 误用（`meta.connect()` 是上下文管理器，不能直接 .execute），
> 已于 2026-09-21 在线上/测试床实测后修正如下。**效果=在原方案上发布新版本，不新建方案、不动历史任务。**

容器内**必须用应用自带运行时**启动 REPL（系统 `python3` 无 pydantic 会报错）：
```
/opt/material_matcher/current/runtime/bin/python3
```
随后逐行（或整体粘贴，Python 3.11 新 REPL 支持多行块）：
```python
import sys
sys.path.insert(0,"/opt/material_matcher/current/app")
from material_matcher.settings import Settings
from material_matcher.storage.metadata import MetadataRepository as M
from material_matcher.services.profile_service import ProfileService as P
svc=P(M(Settings.load().data_dir/'meta'/'material_matcher.db'))
with svc.meta.connect() as cc:
    ids=[(str(r[0]),str(r[1])) for r in cc.execute("SELECT profile_id,name FROM profiles")]
for pid,name in ids:
    d=svc.get(pid)["latest_published"]["document"]
    if d.get("decision",{}).get("success_threshold")==88:
        d=dict(d); d["decision"]=dict(d["decision"]); d["decision"]["success_threshold"]=50
        svc.save_draft(pid,d); svc.publish(pid); print("已发布50:",name)
```
预期输出：每个仍是 88 的方案打印一行 `已发布50: 方案名`；已是 50 或被人改过的自动跳过。
实测记录（同日）：线上 7 案全部发布新版本（A001 v8→v9 等）；客户测试床 6 案（A001→v9、A002/3/5/6→v6、A007→v6）。复验 decision.success_threshold=50。

## 12. 短行手敲版（现场推荐；每行敲完看回显再下一行）
> 说明：编辑器"保存草稿"产生任务草稿的**根因修复在 v1.3.17 源码**（前端需重新构建，现场无法手敲替换打包文件）。
> 现场用本节两步维持：①确认列表过滤器生效 ②一键清草稿。每行都很短。

### 12.1 准备（一次性定义短变量）
```
A=/opt/material_matcher/current
```
```
cd $A/app/material_matcher
```

### 12.2 确认/补上"空草稿过滤"（每行看回显）
```
grep -c "IS NOT NULL" services/task_service.py
```
- 回显 ≥1 → 过滤已在，跳到 12.3
- 回显 0 → 依次敲：
```
cp services/task_service.py services/task_service.py.bak2
```
```
sed -i 's/task_drafts ORDER/task_drafts WHERE source_file_id IS NOT NULL ORDER/' services/task_service.py
```
```
grep -c "IS NOT NULL" services/task_service.py
```
```
python3 -m py_compile services/task_service.py
```
```
cd
```
```
exit
```
（然后宿主机 `docker restart material_matcher-app`）

### 12.3 清空草稿表（REPL 逐行，每行有回显）
```
python3
```
```
import sqlite3
```
```
c=sqlite3.connect('/var/lib/material_matcher/meta/material_matcher.db')
```
```
c.execute('select count(*) from task_drafts').fetchone()
```
（回显条数=将要删除的量，确认合理再继续）
```
print(c.execute('delete from task_drafts').rowcount)
```
```
c.commit()
```
```
print('done')
```
```
exit
```
页面刷新即净。以后每次大批量编辑方案后可重复 12.3（约 20 秒）。

## 13. 现场排障记录：过滤器"装了没生效"（2026-09-21，先存档再操作）
现象：客户机 `grep -n "FROM task_drafts" services/task_service.py` 显示两行，
**第一行（列表查询）没有 WHERE** —— 说明当初第 2 节那条 sed 实际没落上
（常见原因：当时在错误目录/错误文件敲、或敲后未重启容器）。
第二行是"按 draft_id 查单条"，本来就不应有过滤，忽略。

正确补法（容器内，逐行看回显）：
```
cd /opt/material_matcher/current/app/material_matcher
sed -i 's|task_drafts ORDER BY|task_drafts WHERE source_file_id IS NOT NULL ORDER BY|' services/task_service.py
grep -c "IS NOT NULL" services/task_service.py        # 必须回显 1
python3 -m py_compile services/task_service.py        # 必须无输出
```
回宿主机：
```
exit
docker restart material_matcher-app
```
浏览器 Ctrl+F5。此后 STEP2 列表接口层面不再返回空壳草稿；
编辑方案若做过"传文件试算"，产生的带文件草稿仍会短暂可见——用 12.3 的 REPL 清理即可（v1.3.17 根因修复后不再产生）。

注意：12.2 的旧 sed 模式串是 `task_drafts ORDER`（无 BY），若该字符串在目标文件出现于别处也可能误替换；
本节模式 `task_drafts ORDER BY` 更精确，以此为准。改错可用 services/task_service.py.bak2（12.2 有备份习惯）或重敲反向 sed 还原。
