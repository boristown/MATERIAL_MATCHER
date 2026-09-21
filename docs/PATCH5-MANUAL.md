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
