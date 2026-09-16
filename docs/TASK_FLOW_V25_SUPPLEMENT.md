# 物料集团码智能匹配平台 v3.0 四步工作台任务生命周期补充规范

> 状态：Normative  
> 日期：2026-09-16  
> 作用：定义“四步前端工作台”与后端任务草稿、计算、人工处理、结果生成之间的映射关系。  
> 兼容说明：文件名沿用 `TASK_FLOW_V25_SUPPLEMENT.md`，避免历史链接失效；正文规范已升级到 v3.0。

如本文与旧版 `IMPLEMENTATION_CONTRACT.md`、`API_UI_DEPLOYMENT_CONTRACT.md` 或历史五步 UI 描述存在冲突，以 `DEVELOPMENT_DESIGN.md` v3.0、`OPERATION_UI_DESIGN.md` v3.0 和本文为准。

---

## 1. 四步前端与后台生命周期

前端固定表达为：

```text
STEP 1 · 方案与配置
STEP 2 · 匹配计算
STEP 3 · 人工调整
STEP 4 · 输出结果
```

后台仍允许把 STEP1 的任务草稿拆成两个内部子阶段：

```text
STEP1-A 数据选择
STEP1-B 规则确认
```

这两个子阶段**不是侧栏步骤**，只用于草稿持久化和恢复。

后台正式任务阶段：

```text
CALCULATE → REVIEW → RESULT
```

映射：

```text
CALCULATE = STEP2
REVIEW    = STEP3
RESULT    = STEP4
```

如果不存在待人工确认记录：

```text
CALCULATE → RESULT
```

允许直接跳过 STEP3 的具体处理，但 STEP3 页面仍应正确显示“当前无待人工处理数据”。

---

## 2. 核心原则

1. 匹配方案是可复用模板，不是运行任务的强制技术前置；但当前产品主入口鼓励用户从已发布方案快速创建任务。
2. “编辑方案”和“用方案建任务”是两个不同操作模式。
3. 正式任务必须保存一份不可变的运行配置快照，保证结果可复现。
4. 如果任务来自已发布方案，同时记录方案 ID 和版本；如果使用临时规则，则方案引用可以为空。
5. 任务草稿必须后端持久化，浏览器刷新不能丢失 STEP1 内部数据选择/规则确认状态。
6. 人工调整和结果生成属于同一正式任务生命周期。
7. 页面上的任务状态、进度、结果数量必须来自后端，禁止前端伪造。
8. 集团码目录、字典、方案激活版本后续发生变化，不得改变已经启动任务的运行语义。

---

## 3. STEP1 的两种模式

### 3.1 方案编辑模式

入口：

```text
匹配方案卡片 → 编辑
```

目的：维护可复用匹配规则。

允许：

- 字段映射；
- 组合方式；
- matcher；
- 权重；
- 关键字段；
- scope；
- 阈值；
- TopN；
- 处理流水线；
- 保存草稿；
- 发布；
- 版本回滚。

不应出现：

- 本次正式任务名称；
- 本次 Source 数据上传；
- 启动正式匹配任务按钮。

### 3.2 创建任务模式

入口：

```text
匹配方案卡片 → 用此方案建任务
```

目的：快速创建一次正式匹配任务。

默认载入：

- 最新已发布方案 ID；
- 发布版本；
- 只读规则摘要；
- 方案绑定/推荐的 Target 目录信息（如有）。

用户主要完成：

- 任务名称；
- 本次 Source 数据；
- Target 目录版本确认；
- 启动。

如果允许“仅本任务调整”，最终仍必须冻结新的 `config_snapshot`，且不得修改原发布方案。

---

## 4. 任务草稿

```python
class TaskDraft:
    draft_id: str
    name: str
    source_file_id: str | None
    catalog_version_id: str | None
    template_profile_id: str | None
    template_profile_version: int | None
    config_document: dict
    current_step: int           # 1 | 2，仅表示 STEP1 内部子阶段
    created_at: str
    updated_at: str
```

其中：

```text
current_step = 1 → STEP1-A 数据选择
current_step = 2 → STEP1-B 规则确认
```

不得把 `current_step` 直接渲染成侧栏的 STEP2，因为前端 STEP2 已固定代表“匹配计算”。

`config_document` 保存当前任务草稿完整配置。

---

## 5. 正式任务对象

正式任务至少包含：

```python
class MatchTask:
    task_id: str
    name: str

    source_file_id: str
    catalog_version_id: str

    profile_id: str | None
    profile_version: int | None

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

- `config_snapshot` 是真正运行依据；
- 启动后不可修改；
- `profile_id/profile_version` 只记录模板来源；
- `config_sha256` 用于审计和导出摘要；
- `catalog_version_id` 固定本次使用的集团码目录版本；
- 后续 active 目录切换不得改变历史任务。

---

## 6. STEP1 草稿 API

### 6.1 创建草稿

```text
POST /api/task-drafts
```

示例：

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

### 6.2 读取草稿

```text
GET /api/task-drafts/{draft_id}
```

用于刷新或重新登录后恢复 STEP1。

### 6.3 保存数据选择

```text
PUT /api/task-drafts/{draft_id}/data
```

示例：

```json
{
  "source_file_id": "...",
  "catalog_version_id": "...",
  "template_profile_id": "...",
  "template_profile_version": 3
}
```

如果用户通过“用此方案建任务”进入，后端可把发布方案配置复制进 `config_document`，之后本任务调整与原方案解耦。

### 6.4 保存本任务规则

```text
PUT /api/task-drafts/{draft_id}/rules
```

请求体是当前完整配置文档。

中间草稿可以允许尚未达到“可正式运行”的完整度，但必须通过基础 schema 校验。

### 6.5 试算

```text
POST /api/task-drafts/{draft_id}/dry-run
```

默认可取 100 条样本，复用正式匹配逻辑，不开发第二套“演示算法”。

### 6.6 启动正式任务

```text
POST /api/task-drafts/{draft_id}/start
```

启动前：

1. 完整校验；
2. 固定 Source；
3. 固定 Target 目录版本；
4. 固定配置快照；
5. 计算配置哈希；
6. 创建正式任务。

成功返回 HTTP 202：

```json
{
  "task_id": "...",
  "stage": "CALCULATE",
  "status": "PENDING"
}
```

前端跳转 STEP2。

---

## 7. STEP2：匹配计算

### 7.1 任务查询

```text
GET /api/tasks
GET /api/tasks/{task_id}
```

任务详情至少返回：

```json
{
  "task_id": "...",
  "stage": "CALCULATE",
  "status": "RUNNING",
  "progress": 37.5,
  "processed_rows": 37500,
  "total_rows": 100000
}
```

### 7.2 实时进度

```text
GET /api/tasks/{task_id}/progress
```

可以包含：

- `current_phase`；
- `progress`；
- `processed_rows`；
- `total_rows`；
- `live_counts`；
- `estimate`；
- `steps`；
- `interim`。

普通 UI 只显示业务可理解标签。

### 7.3 实时中间结果

```text
GET /api/tasks/{task_id}/live-results
```

用于 STEP2 最近处理结果预览。

中间结果必须显式标识为“运行中/预览”，不能当正式结果下载。

### 7.4 STEP2 页面状态

有运行任务：显示顶部实时操作框。

无运行任务：显示：

```text
无正在进行的任务
[前往 STEP1 配置并启动]
```

历史任务和草稿放在下方列表。

---

## 8. STEP3：人工调整入口状态

STEP3 页面不能单纯过滤 `stage == REVIEW` 后显示一张表，还必须判断当前整体任务状态。

### 8.1 有可人工处理任务

条件：存在真实可处理的 REVIEW 数据。

顶部显示：

- 任务名称；
- 待确认数量；
- 摘要；
- `[进入人工调整]`。

### 8.2 STEP2 正在计算

条件：没有可处理 REVIEW，但存在运行/准备/排队/恢复任务。

顶部显示：

```text
正在等待 STEP2 计算完成
当前任务 + 当前进度
```

不可显示“进入人工调整”。

### 8.3 没有完成数据

条件：既无 REVIEW，又无运行任务。

显示：

```text
当前没有计算完成的数据，请先启动 STEP2 的数据计算。
```

提供返回 STEP2/STEP1 的入口。

---

## 9. STEP3 人工工作台 API

### 9.1 汇总

```text
GET /api/tasks/{task_id}/workbench/summary
```

返回：

- 待确认；
- 已人工确认；
- 未匹配；
- 自动匹配；
- 必要进度上下文。

### 9.2 列表

```text
GET /api/tasks/{task_id}/workbench/items
```

支持：

```text
category
first_score_min / first_score_max
second_score_min / second_score_max
gap_min / gap_max
critical_conflict
page
page_size
```

默认只返回未处理 REVIEW。

### 9.3 候选详情

```text
GET /api/tasks/{task_id}/items/{source_row_id}/candidates
```

返回 TopN 和字段级解释。

### 9.4 单条确认

```text
POST /api/tasks/{task_id}/items/{source_row_id}/confirm
```

```json
{
  "target_id": "...",
  "comment": ""
}
```

### 9.5 标记未匹配

```text
POST /api/tasks/{task_id}/items/{source_row_id}/reject
```

### 9.6 批量确认第一候选

```text
POST /api/tasks/{task_id}/workbench/batch-confirm-top1
```

必须返回成功/失败明细。

### 9.7 批量未匹配

```text
POST /api/tasks/{task_id}/workbench/batch-reject
```

---

## 10. STEP4：结果生成

### 10.1 Finalize

```text
POST /api/tasks/{task_id}/finalize
```

如果仍存在未处理 REVIEW，调用方必须显式确认：

```json
{
  "allow_unresolved_review": true
}
```

否则返回 409。

未处理 REVIEW 的最终集团码保持为空。

### 10.2 导出列表

```text
GET /api/tasks/{task_id}/exports
```

至少可返回：

- 最终结果 Excel；
- TopN 候选；
- 人工确认记录；
- 未匹配清单。

### 10.3 STEP4 最新结果工作台

页面应从任务/结果接口找到最近一次正式完成结果，展示：

- 任务名称；
- 完成时间；
- 总行数；
- 自动匹配；
- 人工确认；
- 未匹配；
- 结果预览；
- 查看完整结果；
- 真实下载。

如果没有结果，必须区分“前一步仍在进行”和“从未生成结果”。

---

## 11. 保存本任务规则为方案

如产品允许从正式任务保存规则：

```text
POST /api/tasks/{task_id}/save-config-as-profile
```

该操作以 `config_snapshot` 创建新的方案草稿/版本，不得反向修改任务快照。

---

## 12. 任务状态与页面行为

正式底层状态可包括：

```text
PENDING
PREPARING
RUNNING
EXPORTING
COMPLETED
FAILED
CANCELLING
CANCELLED
RECOVERING
```

前端业务阶段和底层状态是两个维度：

```text
stage  = CALCULATE / REVIEW / RESULT
status = RUNNING / COMPLETED / FAILED / ...
```

页面不得只看 stage 就假定任务可操作。例如：

- `stage=CALCULATE + status=FAILED` 必须显示失败；
- `stage=RESULT + status=EXPORTING` 不能显示“可下载完成”；
- `stage=REVIEW` 但 summary 待确认为 0 时不能制造虚假待处理数量。

---

## 13. 重启恢复与幂等

- STEP1 草稿由后端恢复；
- STEP2 刷新后重新读取真实 progress；
- 服务重启后任务可以标记 RECOVERING；
- 若恢复策略是安全重跑，必须先清理本任务未完成残留；
- 人工 confirm/reject 应具备防重复提交语义；
- finalize 失败允许单独重试，不要求重跑匹配。

---

## 14. 开发验收

必须覆盖：

1. 方案编辑与创建任务界面语义分离；
2. “用此方案建任务”正确引用发布版本；
3. 任务启动后配置快照不可变；
4. 浏览器刷新后 STEP1 草稿可恢复；
5. STEP2 运行态来自真实 progress；
6. STEP3 有可处理/等待计算/无数据三种状态正确；
7. 工作台确认后记录立即退出默认待处理列表；
8. 人工确认保留审计；
9. 有未处理 REVIEW 时 finalize 需要显式确认；
10. 未处理 REVIEW 的最终集团码为空；
11. STEP4 能显示最近正式结果和真实下载；
12. 结果生成失败可重试，不重新执行完整匹配；
13. 修改方案、字典或 active 目录后，历史任务仍按原快照复现；
14. 页面不使用 Mock 数据伪造成功状态。
