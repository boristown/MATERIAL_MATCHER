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
