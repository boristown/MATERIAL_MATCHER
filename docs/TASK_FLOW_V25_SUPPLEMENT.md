# 物料集团码智能匹配平台 v3.1 四步工作台任务生命周期补充规范

> 状态：Normative  
> 日期：2026-09-16  
> 作用：定义“四步前端工作台”与后端任务草稿、计算、人工处理、结果生成之间的映射关系。  
> 兼容说明：文件名沿用 `TASK_FLOW_V25_SUPPLEMENT.md`，避免历史链接失效；正文用户可见命名已升级到 v3.1。

如本文与旧版 `IMPLEMENTATION_CONTRACT.md`、`API_UI_DEPLOYMENT_CONTRACT.md` 或历史五步 UI 描述存在冲突，以 `DEVELOPMENT_DESIGN.md` v3.0、`OPERATION_UI_DESIGN.md` v3.1 和本文为准。

---

## 1. 四步前端与后台生命周期

前端固定表达为：

```text
第一步 · 数据上传
第二步 · 进度监控
第三步 · 人工调整
第四步 · 输出结果
```

用户可见导航、页面标题、空状态、跳转提示和按钮说明不得再出现 `STEP 1/2/3/4`、`方案与配置`、`匹配计算` 等旧命名。

后台仍允许把第一步的任务草稿拆成两个内部子阶段：

```text
STEP1-A 数据选择
STEP1-B 规则确认
```

这两个标识仅是后端/草稿持久化内部名称，**不是用户可见侧栏步骤**。

后台正式任务阶段：

```text
CALCULATE → REVIEW → RESULT
```

映射：

```text
CALCULATE = 第二步 · 进度监控
REVIEW    = 第三步 · 人工调整
RESULT    = 第四步 · 输出结果
```

如果不存在待人工确认记录：

```text
CALCULATE → RESULT
```

允许直接跳过第三步的具体处理，但“第三步 · 人工调整”页面仍应正确显示“当前无待人工处理数据”。

---

## 2. 核心原则

1. 第一步直接面向本次任务数据：源 Excel + 目标集团码 Excel；集团码目录不再是普通用户必须先维护的前置步骤。
2. 匹配方案仍可作为可复用规则模板，但不是运行任务的强制业务前置。
3. “编辑方案”和“创建匹配任务”是两个不同操作模式。
4. 正式任务必须保存一份不可变的运行配置快照，保证结果可复现。
5. 如果任务来自已发布方案，同时记录方案 ID 和版本；如果使用临时规则，则方案引用可以为空。
6. 任务草稿必须后端持久化，浏览器刷新不能丢失第一步内部的数据选择/规则确认状态。
7. 人工调整和结果生成属于同一正式任务生命周期。
8. 页面上的任务状态、进度、结果数量必须来自后端，禁止前端伪造。
9. 后台自动形成的目录版本、字典版本和索引后续发生变化，不得改变已经启动任务的运行语义。

---

## 3. 第一步 · 数据上传

### 3.1 方案编辑模式

入口可以来自匹配方案管理：

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

方案编辑模式不应混入正式任务运行状态。

### 3.2 创建任务模式

目的：快速创建一次正式匹配任务。

用户主要完成：

- 任务名称；
- 本次 Source Excel；
- 本次 Target 集团码 Excel；
- 字段识别与映射；
- 规则摘要确认；
- 启动。

如果从已发布方案进入，可以预载规则，但不得要求用户先去独立“集团码目录”页面维护 Target。后端可以把本次 Target Excel 自动固化为内部目录版本/索引对象。

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
    current_step: int           # 1 | 2，仅表示第一步内部子阶段
    created_at: str
    updated_at: str
```

其中内部值可以继续表示：

```text
current_step = 1 → STEP1-A 数据选择
current_step = 2 → STEP1-B 规则确认
```

不得把 `current_step` 直接渲染成用户侧栏的第二步。用户侧栏的“第二步 · 进度监控”只代表正式任务已经进入计算阶段。

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
- `config_sha256` 用于审计和导出摘要，不应直接展示给普通业务用户；
- `catalog_version_id` 可以作为后台自动固化本次 Target Excel 的内部版本标识；
- 后续后台 active 目录切换不得改变历史任务。

---

## 6. 第一步草稿 API

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

用于刷新或重新登录后恢复“第一步 · 数据上传”。

### 6.3 保存数据选择

```text
PUT /api/task-drafts/{draft_id}/data
```

现有后端如果仍使用内部 `catalog_version_id`，前端上传 Target Excel 后由后端自动产生/绑定该内部版本。用户不需要手工理解目录版本。

示例：

```json
{
  "source_file_id": "...",
  "catalog_version_id": "...",
  "template_profile_id": "...",
  "template_profile_version": 3
}
```

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
3. 固定本次 Target 对应的内部版本；
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

前端跳转“第二步 · 进度监控”。

---

## 7. 第二步 · 进度监控

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

用于“第二步 · 进度监控”的最近处理结果预览。

中间结果必须显式标识为“运行中/预览”，不能当正式结果下载。

### 7.4 页面状态

有运行任务：显示顶部实时操作框。

无运行任务：显示：

```text
无正在进行的任务
[前往第一步 · 数据上传]
```

历史任务和草稿放在下方列表。

---

## 8. 第三步 · 人工调整入口状态

“第三步 · 人工调整”页面不能单纯过滤 `stage == REVIEW` 后显示一张表，还必须判断当前整体任务状态。

### 8.1 有可人工处理任务

条件：存在真实可处理的 REVIEW 数据。

顶部显示：

- 任务名称；
- 待确认数量；
- 摘要；
- `[进入人工调整]`。

### 8.2 第二步仍在计算

条件：没有可处理 REVIEW，但存在运行/准备/排队/恢复任务。

顶部显示：

```text
正在等待“第二步 · 进度监控”中的计算完成
当前任务 + 当前进度
```

不可显示“进入人工调整”。

### 8.3 没有完成数据

条件：既无 REVIEW，又无运行任务。

显示：

```text
当前没有计算完成的数据，请先在“第一步 · 数据上传”启动任务，并在“第二步 · 进度监控”等待计算完成。
```

提供返回“第二步 · 进度监控”/“第一步 · 数据上传”的入口。

---

## 9. 第三步人工工作台 API

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

## 10. 第四步 · 输出结果

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

### 10.3 最新结果工作台

“第四步 · 输出结果”应从任务/结果接口找到最近一次正式完成结果，展示：

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

- 第一步任务草稿由后端恢复；
- 第二步刷新后重新读取真实 progress；
- 服务重启后任务可以标记 RECOVERING；
- 若恢复策略是安全重跑，必须先清理本任务未完成残留；
- 人工 confirm/reject 应具备防重复提交语义；
- finalize 失败允许单独重试，不要求重跑匹配。

---

## 14. 开发验收

必须覆盖：

1. 第一步可以直接处理 Source Excel + Target 集团码 Excel，不依赖普通用户预维护集团码目录；
2. 方案编辑与创建任务界面语义分离；
3. 任务启动后配置快照不可变；
4. 浏览器刷新后第一步草稿可恢复；
5. 第二步运行态来自真实 progress；
6. 第三步有可处理/等待计算/无数据三种状态正确；
7. 工作台确认后记录立即退出默认待处理列表；
8. 人工确认保留审计；
9. 有未处理 REVIEW 时 finalize 需要显式确认；
10. 未处理 REVIEW 的最终集团码为空；
11. 第四步能显示最近正式结果和真实下载；
12. 结果生成失败可重试，不重新执行完整匹配；
13. 修改方案、字典或后台目标版本后，历史任务仍按原快照复现；
14. 用户可见界面不出现旧 `STEP 1/2/3/4` 导航命名；
15. 页面不使用 Mock 数据伪造成功状态。
