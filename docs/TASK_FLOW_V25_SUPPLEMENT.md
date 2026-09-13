# 物料集团码匹配引擎 v2.5 五步任务主流程补充规范

> 状态：Normative  
> 日期：2026-09-13  
> 作用：为“选择数据 → 确认匹配规则 → 比对计算 → 人工处理 → 生成结果”的统一任务流程补充数据模型和接口契约。

如本文与旧版 `IMPLEMENTATION_CONTRACT.md` 24.5、`API_UI_DEPLOYMENT_CONTRACT.md` 42.9～42.11 或第 44 章存在冲突，以本文和 `OPERATION_UI_DESIGN.md` v2.5 为准。

## 1. 核心原则

1. 匹配方案是可复用模板，不是运行任务的强制前置条件。
2. 正式任务必须保存一份不可变的**运行配置快照**，保证结果可复现。
3. 如果任务来自已发布方案，同时记录方案 ID 和版本；如果用户临时配置，则方案引用可以为空。
4. 任务草稿必须后端持久化，浏览器刷新不能丢失 Step 1/2 配置。
5. 人工处理和结果生成属于同一任务生命周期，不建立独立结果管理对象作为必经流程。

## 2. 任务草稿

```python
class TaskDraft:
    draft_id: str
    name: str
    source_file_id: str | None
    catalog_version_id: str | None
    template_profile_id: str | None
    template_profile_version: int | None
    config_document: dict
    current_step: int           # 1 | 2
    created_at: str
    updated_at: str
```

`config_document` 保存当前规则编辑器的完整配置。

## 3. 正式任务对象修订

正式任务对象必须至少包含：

```python
class MatchTask:
    task_id: str
    name: str

    source_file_id: str
    catalog_version_id: str

    # 可选模板来源
    profile_id: str | None
    profile_version: int | None

    # 真正的运行依据，必须不可变
    config_snapshot: dict
    config_sha256: str

    stage: str                 # CALCULATE | REVIEW | RESULT
    status: str
    progress: float
    processed_rows: int
    total_rows: int

    created_at: str
    started_at: str | None
    finished_at: str | None
    error_code: str | None
    error_message: str | None
    result_file_id: str | None
```

规则：

- `config_snapshot` 是任务启动时冻结的配置；
- 后续修改模板方案不得改变已启动任务；
- `profile_id/profile_version` 只用于追溯模板来源；
- 临时规则任务允许二者为空；
- `config_sha256` 必须参与任务审计和结果导出摘要。

## 4. 任务草稿 API

### 4.1 创建草稿

`POST /api/task-drafts`

请求：

```json
{
  "name": "2026年9月集团码匹配"
}
```

响应：

```json
{
  "draft_id": "...",
  "current_step": 1
}
```

### 4.2 读取草稿

`GET /api/task-drafts/{draft_id}`

用于刷新或重新登录后恢复。

### 4.3 保存 Step 1 数据选择

`PUT /api/task-drafts/{draft_id}/data`

```json
{
  "source_file_id": "...",
  "catalog_version_id": "...",
  "template_profile_id": null,
  "template_profile_version": null
}
```

如果选择已有方案模板，后端将其配置复制到 `config_document`，后续调整只影响该草稿，不直接修改原方案。

### 4.4 保存 Step 2 匹配规则

`PUT /api/task-drafts/{draft_id}/rules`

请求体是当前完整配置文档。

必须执行 schema 校验，但允许尚未满足“可正式运行”的中间草稿状态。

### 4.5 试算

`POST /api/task-drafts/{draft_id}/dry-run`

默认样本 100 条，复用正式匹配算法和候选详情组件。

### 4.6 启动正式任务

`POST /api/task-drafts/{draft_id}/start`

启动前必须执行完整校验并冻结 `config_snapshot`。

成功返回 HTTP 202：

```json
{
  "task_id": "...",
  "stage": "CALCULATE",
  "status": "PENDING"
}
```

## 5. 正式任务查询与阶段

`GET /api/tasks/{task_id}` 必须返回：

```json
{
  "task_id": "...",
  "stage": "CALCULATE",
  "status": "RUNNING",
  "progress": 37.5,
  "processed_rows": 37500,
  "total_rows": 100000,
  "elapsed_seconds": 1234,
  "estimated_remaining_seconds": 2088
}
```

`stage` 只表示业务界面所在阶段，不替代底层任务状态机。

## 6. 比对计算进度

`GET /api/tasks/{task_id}/progress`

必须返回五个业务阶段：

```json
{
  "steps": [
    {"key": "prepare", "label": "数据准备", "status": "DONE"},
    {"key": "embedding", "label": "向量化处理", "status": "DONE"},
    {"key": "retrieve", "label": "候选比对", "status": "RUNNING"},
    {"key": "rerank", "label": "精细评分", "status": "WAITING"},
    {"key": "prepare_result", "label": "结果整理", "status": "WAITING"}
  ]
}
```

普通 UI 只显示 `label`，技术日志可保留底层模块名。

## 7. 人工处理工作台 API

### 7.1 汇总

`GET /api/tasks/{task_id}/workbench/summary`

返回：待确认、已人工确认、未匹配、自动匹配等数量。

### 7.2 列表

`GET /api/tasks/{task_id}/workbench/items`

支持参数：

```text
category
first_score_min / first_score_max
second_score_min / second_score_max
gap_min / gap_max
critical_conflict
page
page_size
```

默认只返回 `REVIEW` 且未人工处理记录。

### 7.3 候选详情

`GET /api/tasks/{task_id}/items/{source_row_id}/candidates`

返回 TopN 和每个候选的字段级解释。

### 7.4 单条确认

`POST /api/tasks/{task_id}/items/{source_row_id}/confirm`

```json
{
  "target_id": "...",
  "comment": ""
}
```

### 7.5 单条标记未匹配

`POST /api/tasks/{task_id}/items/{source_row_id}/reject`

### 7.6 批量确认第一候选

`POST /api/tasks/{task_id}/workbench/batch-confirm-top1`

```json
{
  "source_row_ids": ["...", "..."]
}
```

响应必须返回成功和失败明细，不得只返回布尔值。

### 7.7 批量标记未匹配

`POST /api/tasks/{task_id}/workbench/batch-reject`

## 8. 生成最终结果

`POST /api/tasks/{task_id}/finalize`

如果仍有 `REVIEW` 记录，请求必须显式带：

```json
{
  "allow_unresolved_review": true
}
```

否则返回 409。

生成结果时未处理 REVIEW 的最终集团码保持为空，不允许自动回填第一候选。

`GET /api/tasks/{task_id}/exports`

返回：

- 最终结果 Excel；
- TopN 候选；
- 人工确认记录；
- 未匹配清单。

## 9. 保存临时规则为方案

任务 Step 2 或结果页都可以调用：

`POST /api/tasks/{task_id}/save-config-as-profile`

该操作基于任务 `config_snapshot` 创建新的方案草稿/版本，不得反向修改任务快照。

## 10. 开发验收

必须覆盖：

1. 未选择匹配方案也能完整创建并运行任务；
2. 选择已有方案后可以在任务内临时调整，且不修改原方案；
3. 浏览器刷新后 Step 1/2 草稿可恢复；
4. 启动后配置快照不可变；
5. 计算完成后自动进入人工处理或直接结果阶段；
6. 工作台批量确认后记录立即退出默认列表；
7. 候选抽屉确认后自动定位下一条；
8. 有未处理 REVIEW 时生成结果必须二次确认；
9. 未处理 REVIEW 的最终集团码保持为空；
10. 结果生成失败可重试，不重复执行匹配计算。
