# 13 所现场热修与 1.3.22 基线（2026-09-28）

## 背景

2026-09-28 现场对大批量人工复核流程继续验证，确认并处理以下两类问题：

1. 自动匹配分数已经超过阈值，但部分记录仍因 `minimum_score_gap` 分差保护停留在人工处理状态；
2. “人工匹配 Excel”把已经自动匹配的 `MATCHED` 记录也导出，导致人工工作集过大、语义不清，同时放大导出耗时。

相关 Issue：

- #204：1.5 万条人工匹配 Excel 导出耗时与进度反馈
- #205：人工匹配 Excel 不应包含已自动匹配记录
- #206：超过自动匹配阈值仍未自动匹配、阻断条件不透明

## 现场已验证热修

### 1. 禁用 minimum_score_gap 阻断

现场临时将匹配主链路中的 `minimum_score_gap` 判定设为 0。

正式代码基线采用更完整的兼容实现：

- 保留历史配置键 `advanced.matching_safety.minimum_score_gap`，避免冻结方案/旧任务反序列化失败；
- `minimum_score_gap(config)` 固定返回 `0.0`；
- 普通方案与组合方案统一失效，不再因 Top1/Top2 分差小而阻断自动匹配；
- `critical_conflict`、`auto_match_safe`、显式 `tie_break=review` 等其它安全逻辑保持不变。

### 2. 人工匹配 Excel 排除自动匹配记录

`ManualReviewService.export_workbook()` 的总数与主数据游标统一增加：

```sql
current_status <> 'MATCHED'
```

因此人工 Excel 不再导出自动匹配成功的记录。

当前保留状态：

- REVIEW
- UNMATCHED
- CONFIRMED

后续若要将“完整结果导出”与“人工工作集导出”进一步拆分，单独迭代，不在本次现场热修扩大范围。

## 一次性现场数据刷新

为了避免对约 1.5 万条任务重新执行数小时的向量召回/候选评分，现场对**指定任务**做了一次数据库状态修复：

- 只处理已有 `top1_group_code` 的记录；
- 将高于现场自动阈值的 `UNMATCHED/REVIEW` 状态直接刷新为 `MATCHED`；
- `final_group_code = top1_group_code`；
- 该操作是**现场任务数据修复**，不是数据库 schema migration，也不应作为安装/升级脚本对历史任务批量执行。

边界说明：STEP3 目前按 1 位小数显示分数，例如数据库中的 49.96 会显示为 50.0；数据库阈值判断仍使用原始分数。本次没有改变这一显示/判定语义。

## 正式代码基线

- 版本：**1.3.22**
- 计划 tag：**v1.3.22**
- 基线分支：合并到 `main` 后，以 `v1.3.22` 所指向的 main commit 为唯一基线。
- 下一增量补丁：必须从 **v1.3.22** 起算，不再从 v1.3.21 或现场容器手改文件反推差异。

正式涉及文件：

- `src/material_matcher/matching/scorer.py`
- `src/material_matcher/services/manual_review_service.py`
- `tests/test_matching_calibration.py`
- `tests/test_composite_match_service.py`
- `tests/test_manual_review_collaboration.py`
- `src/material_matcher/VERSION`

## 现场部署路径确认

Docker/Native 当前正式后端源码位置：

```text
/opt/material_matcher/current/app/material_matcher/
```

运行时 Python：

```text
/opt/material_matcher/current/runtime/bin/python3
```

现场容器手工修改仅用于紧急处置；容器被 recreate 或后续介质升级后，应以仓库 `v1.3.22` 基线内容为准。

## 下一增量补丁要求

1. 以 `v1.3.22` 为 base；
2. 不重复携带现场手改逻辑之外的旧版本差异；
3. 升级后验证：
   - health/version = 1.3.22 或更高目标版本；
   - 自动匹配不再受 minimum_score_gap 阻断；
   - 人工匹配 Excel 不含 `MATCHED`；
   - 旧方案中存在 minimum_score_gap 字段仍可正常加载；
4. 不把本次一次性 SQL 数据修复做成全局迁移；
5. 现场数据库更新前仍需备份。
