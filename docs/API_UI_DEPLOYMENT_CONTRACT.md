# 物料集团码匹配引擎：核心函数、接口、UI、部署与验收规范

> 文档版本：2.2
> 日期：2026-09-13

## 41. 核心函数输入输出定义

以下接口是核心开发契约。实现文件位置可以调整，但行为不得变化。

### 41.1 表格检查

```python
def inspect_tabular_file(
    file_path: Path,
    *,
    max_scan_rows: int = 30,
    sample_data_rows: int = 20,
) -> InspectionResult:
    """只读检查，不修改文件。解析失败抛 InputFileError。"""
```

### 41.2 数据集加载

```python
def load_dataset(
    spec: DatasetSpec,
    *,
    chunk_size: int = 5000,
) -> DatasetHandle:
    """返回可迭代数据集句柄；编码字段必须保持字符串语义。"""
```

### 41.3 数据关联

```python
def join_datasets(
    left: DatasetHandle,
    right: DatasetHandle,
    spec: JoinSpec,
) -> DatasetHandle:
    """严格执行重复键策略；发生 join explosion 时抛 JoinExplosionError。"""
```

### 41.4 转换

```python
def apply_transform(
    row: Mapping[str, object],
    spec: TransformSpec,
    context: TransformContext,
) -> object:
    """不得读取客户名进行分支。"""
```

### 41.5 方案编译

```python
def compile_profile(
    document: dict[str, object],
    catalog_registry: CatalogRegistry,
    matcher_registry: MatcherRegistry,
) -> CompiledProfile:
    """发布和任务启动前都必须执行；返回不可变的运行期方案。"""
```

必须校验：

- 引用字段存在；
- 路由引用的目录存在；
- 权重 0~100；
- 阈值关系合法；
- matcher 存在；
- 同义词无冲突；
- 输出 TopN 合法；
- 关联关系无循环。

### 41.6 字段组合

```python
def compose_value(
    row: Mapping[str, object],
    fields: list[FieldRef],
    combine: CombineSpec,
) -> ComposedValue:
    ...
```

输出必须包含：

```python
class ComposedValue:
    raw_parts: list[str]
    normalized_parts: list[str]
    value: str
    is_empty: bool
```

### 41.7 单字段匹配

```python
def score_field_rule(
    source_row: Mapping[str, object],
    target_row: Mapping[str, object],
    rule: CompiledFieldRule,
    context: MatchContext,
) -> RuleScore | None:
    """任一侧无可比较值时返回 None，而不是 0。"""
```

### 41.8 候选综合评分

```python
def score_candidate(
    source_row: Mapping[str, object],
    target_row: Mapping[str, object],
    rules: list[CompiledFieldRule],
    scoring_policy: ScoringPolicy,
) -> CandidateScore:
    ...
```

```python
class CandidateScore:
    raw_score: float
    display_score: float
    rule_scores: list[RuleScore]
    caps_applied: list[str]
    matched_weight: float
    reason_codes: list[str]
```

### 41.9 决策

```python
def decide_match(
    best: CandidateScore | None,
    policy: DecisionPolicy,
) -> MatchDecision:
    ...
```

```python
class MatchDecision:
    status: str
    final_group_code: str | None
    raw_score: float
    display_score: float
    reason: str
```

### 41.10 批量召回

```python
def retrieve_candidates_batch(
    query_rows: list[Mapping[str, object]],
    compiled_profile: CompiledProfile,
    catalog: CatalogHandle,
) -> list[list[CandidateRef]]:
    ...
```

输入和输出索引必须一一对应，某条无候选返回空列表，不得丢行。

### 41.11 正式任务

```python
def run_match_task(task_id: str) -> None:
    """
    从元数据库加载不可变任务快照；
    分批匹配；
    持久化进度；
    生成结果；
    原子切换 COMPLETED。
    """
```

---

## 42. HTTP 接口规范

所有业务接口以 `/api` 开头。除健康检查和登录外均要求管理员登录。

统一错误响应：

```json
{
  "error": {
    "code": "INVALID_PROFILE",
    "message": "成功阈值必须大于复核阈值",
    "details": {},
    "request_id": "..."
  }
}
```

### 42.1 登录

`POST /api/auth/login`

请求：

```json
{
  "username": "admin",
  "password": "Ab3dEf7Gh9"
}
```

成功：

```json
{
  "ok": true,
  "expires_at": "2026-09-13T07:00:00+08:00"
}
```

建议正式版使用 HttpOnly Cookie 保存会话，前端不得把管理员密码写入本地存储。

### 42.2 退出

`POST /api/auth/logout`

返回：

```json
{"ok": true}
```

### 42.3 健康检查

`GET /api/health`

```json
{
  "status": "ok",
  "version": "1.0.0"
}
```

`GET /api/health/ready`

必须额外检查：

- 密码已配置；
- 元数据库可读写；
- 数据目录可读写；
- 当前活动集团码索引可加载（若存在）；
- 临时目录可写。

### 42.4 文件上传

小文件：

`POST /api/files/upload?role=source`

返回：

```json
{
  "file_id": "32位ID",
  "name": "source.xlsx",
  "size_bytes": 123456,
  "sha256": "...",
  "status": "READY",
  "inspection": {}
}
```

### 42.5 大文件分块

- `POST /api/uploads/init`
- `PUT /api/uploads/{upload_id}/chunks/{index}`
- `POST /api/uploads/{upload_id}/complete`
- `GET /api/uploads/{upload_id}`

`complete` 必须验证总大小和 SHA-256。

### 42.6 集团码目录

- `GET /api/catalogs`
- `POST /api/catalogs`
- `GET /api/catalogs/{catalog_id}`
- `POST /api/catalogs/{catalog_id}/versions`
- `POST /api/catalogs/{catalog_id}/versions/{version_id}/activate`
- `POST /api/catalogs/{catalog_id}/versions/{version_id}/build-index`
- `GET /api/catalogs/{catalog_id}/versions/{version_id}/index-status`

### 42.7 方案

- `GET /api/profiles`
- `POST /api/profiles`
- `GET /api/profiles/{profile_id}`
- `PUT /api/profiles/{profile_id}/draft`
- `POST /api/profiles/{profile_id}/validate`
- `POST /api/profiles/{profile_id}/dry-run`
- `POST /api/profiles/{profile_id}/publish`
- `GET /api/profiles/{profile_id}/versions`
- `POST /api/profiles/{profile_id}/rollback/{version_no}`

### 42.8 Dry Run

`POST /api/profiles/{profile_id}/dry-run`

请求：

```json
{
  "source_file_id": "...",
  "sample_mode": "first",
  "sample_rows": 100
}
```

响应：

```json
{
  "summary": {
    "total": 100,
    "matched": 62,
    "review": 21,
    "unmatched": 17
  },
  "rows": []
}
```

最大样本默认 1000；普通 UI 默认 100。

### 42.9 正式任务

`POST /api/tasks`

请求：

```json
{
  "name": "2026年9月批量匹配",
  "profile_id": "...",
  "profile_version": 3,
  "source_file_id": "...",
  "catalog_version_id": "..."
}
```

响应 HTTP 202：

```json
{
  "task_id": "...",
  "status": "PENDING"
}
```

### 42.10 任务查询

- `GET /api/tasks`
- `GET /api/tasks/{task_id}`
- `POST /api/tasks/{task_id}/cancel`
- `GET /api/tasks/{task_id}/result`

### 42.11 人工复核

- `GET /api/tasks/{task_id}/reviews`
- `POST /api/tasks/{task_id}/reviews/{source_row_id}/confirm`
- `POST /api/tasks/{task_id}/reviews/{source_row_id}/reject`

确认请求：

```json
{
  "group_code": "HTWZ...",
  "comment": "人工核对型号与标准一致"
}
```

### 42.12 临时文件

- `GET /api/temp-files`
- `POST /api/temp-files/cleanup`

请求只能传业务条件：

```json
{
  "older_than_days": 7,
  "task_ids": []
}
```

禁止由前端传任意文件系统路径。

---

## 43. 错误码

最低必须实现以下错误码：

| 错误码 | HTTP | 含义 |
|---|---:|---|
| AUTH_REQUIRED | 401 | 未登录 |
| AUTH_FAILED | 401 | 密码错误 |
| FILE_TOO_LARGE | 413 | 文件超限 |
| UNSUPPORTED_FILE | 400 | 文件类型不支持 |
| FILE_PARSE_FAILED | 400 | 表格无法解析 |
| HEADER_NOT_FOUND | 400 | 无法识别/指定表头不存在 |
| COLUMN_NOT_FOUND | 400 | 配置字段不存在 |
| LEADING_ZERO_RISK | 422 | 编码存在不可恢复前导零风险，需要确认 |
| INVALID_PROFILE | 422 | 方案校验失败 |
| INVALID_WEIGHT | 422 | 权重越界 |
| INVALID_THRESHOLD | 422 | 阈值关系错误 |
| JOIN_DUPLICATE_KEY | 422 | 关联重复键不符合策略 |
| JOIN_EXPLOSION | 422 | 关联行数爆炸 |
| ROUTE_NOT_FOUND | 422 | 无业务路由 |
| GROUP_MAPPING_NOT_FOUND | 422 | 分类映射不存在 |
| CATALOG_NOT_READY | 409 | 集团码目录未就绪 |
| INDEX_NOT_READY | 409 | 索引未就绪 |
| TASK_NOT_FOUND | 404 | 任务不存在 |
| TASK_STATE_CONFLICT | 409 | 当前状态不允许该操作 |
| NO_CANDIDATE | 200 | 业务结果：无候选，不是 HTTP 错误 |
| DISK_SPACE_LOW | 507 | 磁盘空间不足 |
| INTERNAL_ERROR | 500 | 未分类内部错误 |

界面不得直接显示 Python traceback；详细 traceback 仅写日志。

---

## 44. 操作界面详细规格

本章是前端开发的**唯一开发级 UI 契约**。业务说明见主设计书第 13 章。二者不一致时必须先修订文档，不允许开发人员自行选择其中一版。

### 44.1 一级导航与路由

一级导航固定 4 项：

| 导航 | 路由 | 说明 |
|---|---|---|
| 匹配任务 | `/tasks` | 登录后默认页 |
| 匹配方案 | `/profiles` | 方案列表与方案配置 |
| 数据配置 | `/data` | 集团码目录、模板、字典、索引 |
| 系统设置 | `/system` | 服务、存储、临时文件、诊断 |

完整允许路由：

```text
/login
/tasks
/tasks/new
/tasks/:taskId
/tasks/:taskId/workbench
/tasks/:taskId/items/:sourceRowId
/profiles
/profiles/new?step=1
/profiles/:profileId/edit?step=1..7
/data?tab=catalogs
/data?tab=templates
/data?tab=dictionaries
/data?tab=indexes
/system?tab=service
/system?tab=storage
/system?tab=temp
/system?tab=diagnostics
```

禁止新增以下一级路由：

```text
/
/home
/reviews
/results
/temp-files
/catalogs
/dictionaries
/match-workbench
```

如需兼容旧链接，只允许重定向至上述正式路由。

### 44.2 全局布局

最低支持 `1366×768`。

左侧导航：

- 展开宽度：176 px；
- 收起宽度：56 px；
- 默认展开；
- 固定定位；
- 仅显示 4 个一级菜单。

顶部栏：

- 高度：52 px；
- 左侧：产品名称；
- 中间：当前页面标题；
- 右侧：服务状态、`admin` 菜单；
- 不设计全局搜索框。

内容区：

- 统一内边距 20 px；
- 内容区独立滚动；
- 表格区域允许横向滚动；
- 关键列使用 sticky。

### 44.3 登录页

字段：

```text
账号：admin（固定、不可编辑）
密码：password
[登录]
```

行为：

- 密码为空前端阻止提交；
- 登录失败统一提示“用户名或密码错误”；
- 不把密码写入 localStorage/sessionStorage；
- 登录成功必须跳转 `/tasks`。

### 44.4 匹配任务列表 `/tasks`

页面组件：

```text
T01 页面标题：匹配任务
T02 [新建匹配任务]
T03 任务搜索输入
T04 状态筛选
T05 日期范围
T06 [查询]
T07 任务表格
```

任务表固定列：

```text
任务编号
任务名称
匹配方案
客户数据
进度
状态
创建时间
操作
```

操作列只显示 `[查看]`。

不在任务列表直接堆叠“导出、临时文件、目录版本、人工复核”等动作。

### 44.5 新建任务 `/tasks/new`

字段：

| 字段 | 必填 | 规则 |
|---|---:|---|
| 任务名称 | 是 | 1～100 字 |
| 匹配方案 | 是 | 只能选已发布版本 |
| 客户数据 | 是 | 上传或选择已上传数据 |
| 集团码目录版本 | 默认 | 由方案自动带出；允许管理员确认 |
| 任务备注 | 否 | 0～500 字 |

按钮：

```text
[取消] [创建并开始]
```

创建成功跳转 `/tasks/{taskId}`。

### 44.6 任务详情 `/tasks/:taskId`

顶部显示：任务编号、任务名称、方案名称+版本、客户数据、集团码目录+版本、状态、进度、已处理/总数、开始时间、结束时间。

运行中：`[取消任务] [刷新]`

失败：`[查看错误摘要] [重试]`

已完成：

```text
[进入匹配结果工作台]
[下载最终结果]
[下载TopN]
[下载人工确认记录]
[下载未匹配清单]
```

### 44.7 匹配结果工作台 `/tasks/:taskId/workbench`

#### 44.7.1 页面上下文

标题必须包含当前任务名称；页面固定显示任务编号，防止误处理其他任务。

#### 44.7.2 汇总卡片

固定顺序：总物料数、自动匹配、待人工确认、未匹配、已人工确认。

#### 44.7.3 筛选控件

| 编号 | 字段 | 类型 | 默认 |
|---|---|---|---|
| F01 | 物料类别 | 多选下拉 | 全部 |
| F02 | 处理状态 | 多选下拉 | 未处理状态 |
| F03 | 第一候选分 | min/max 数字框 | 空 |
| F04 | 第二候选分 | min/max 数字框 | 空 |
| F05 | 分差 | min/max 数字框 | 空 |
| F06 | 关键字段冲突 | 全部/有/无 | 全部 |
| F07 | 仅看未处理 | Switch | 开 |

分数输入范围 `0～100`，允许 1 位小数。

快捷筛选严格等价于：

```text
90分以上且无冲突: F03.min=90, F06=无, F07=开
80～90分: F03.min=80, F03.max=90
分差<5: F05.max=5
存在冲突: F06=有
仅待确认: F02=[待人工确认], F07=开
```

快捷筛选只修改 F01～F07，不维护第二套隐藏状态。

#### 44.7.4 结果表

固定列：

```text
checkbox
物料编码
物料名称
类别
第一候选集团码
第一候选分
第二候选分
分差
关键字段冲突
状态
操作
```

不显示“处理人”列，因为系统只有固定 `admin`。处理人保留在审计记录中。

操作：`[查看候选] [确认第一候选] [标记未匹配]`

状态中文显示：自动匹配 / 待人工确认 / 未匹配 / 人工确认。

默认排序：未处理优先 -> 第一候选分 DESC -> 分差 DESC -> 物料编码 ASC。

#### 44.7.5 批量操作

只支持：

```text
[批量确认第一候选]
[批量转待人工确认]
[批量标记未匹配]
```

确认第一候选前必须校验所选记录都存在 Top1，且不包含已人工确认记录。

确认框必须显示影响数量，例如：

```text
将确认所选 126 条物料的第一候选集团码。
确认后会写入人工确认记录，并从“仅看未处理”列表中移除。
[取消] [确认126条]
```

后端部分失败时必须返回成功列表和失败列表，前端不得错误显示为全成功。

### 44.8 候选对比 `/tasks/:taskId/items/:sourceRowId`

不采用三个候选横向固定并排作为正式布局。

页面结构：来源物料摘要、TopN 候选标签、当前候选摘要、字段对比表、推荐/冲突说明、操作按钮。

TopN 标签：

```text
候选1 92.0
候选2 78.0
候选3 56.0
更多...
```

字段对比固定列：

```text
字段
客户值
集团值
字段得分
权重
关键字段
比较结果
```

比较结果枚举：一致 / 接近 / 冲突 / 缺失 / 不参与。

按钮：`[上一条] [标记未匹配] [确认当前候选] [下一条]`

确认后写 `ReviewRecord`、更新最终集团码和记录状态；若来自“仅看未处理”，返回后该行不得再出现。

### 44.9 匹配方案列表 `/profiles`

固定列：方案名称、当前发布版本、适用说明、状态、最近发布时间、操作。

操作：`[编辑] [复制] [版本] [创建任务] [归档]`

### 44.10 方案配置向导

新建：`/profiles/new?step=1`

编辑：`/profiles/:profileId/edit?step=1..7`

固定步骤：

```text
1 客户物料
2 集团码数据
3 分类范围
4 字段对应
5 权重与阈值
6 试跑验证
7 发布方案
```

底部固定按钮：`[上一步] [保存草稿] [下一步]`

自动保存：停止输入 5 秒后执行；同时最多一个保存请求；页面显示“已保存/保存中/保存失败”。

### 44.11 步骤 1：客户物料

显示：上传区域、工作表选择、表头行、字段预览表。

字段预览列：列序号、原始列名、样例1、样例2、推测用途、风险。

修改 Sheet 或表头行后 500 ms 防抖重新预览。

### 44.12 步骤 2：集团码数据

只提供：

```text
○ 使用已有集团码目录版本
○ 上传新集团码目录版本
```

目录版本显示：目录名称、版本、记录数、集团码字段、索引状态。

### 44.13 步骤 3：分类范围

模式：全局匹配 / 同组严格匹配 / 分类映射匹配。

映射模式表：客户分类、允许的集团分类、状态。

### 44.14 步骤 4：字段对应

正式实现采用映射表，不采用拖拽连线画布。

表格列：

```text
序号
客户字段组合
集团字段组合
组合方式
匹配方式
权重
关键字段
操作
```

字段组合通过“选择字段 + Tag 顺序”完成；Tag 可拖动调整拼接顺序。

组合方式：直接 / 拼接 / 第一个有效值 / 多个比较取最高分。

匹配方式：完全一致 / 清洗后完全一致 / 包含 / 字符串相似 / 关键词相似 / 数值尺寸 / 标准号 / 向量语义 / 综合匹配。

权重：`0～100` 整数。

### 44.15 步骤 5：权重与阈值

字段权重直接复用步骤 4 的权重，不再提供第二套独立权重编辑区域，只做汇总检查。

阈值：

```text
自动匹配成功阈值 [88]
启用人工确认     [开关]
人工确认下限     [75]
显示相似度系数   [1.00]
前N名输出         [5]
```

校验：`1 <= success <= 100`、`0 <= review < success`、`0.1 <= display_coefficient <= 3.0`、`1 <= top_n <= 50`。

### 44.16 步骤 6：试跑

按钮：`[试跑100条] [重新试跑]`

统计：总数、自动匹配、待人工确认、未匹配。

结果表：客户物料号、客户描述、第一候选集团码、第一候选分、第二候选分、分差、状态、查看候选。

“查看候选”复用第 44.8 节候选对比组件，不开发另一套试跑详情 UI。

### 44.17 步骤 7：发布

发布校验：客户数据结构、集团码数据、分类路由、字段规则、权重、阈值、试跑、索引全部有效。

发布成功显示方案名称、版本号、发布时间和 `[立即创建匹配任务]`。

### 44.18 数据配置 `/data`

只使用页签：

```text
集团码目录
客户数据模板
同义词/字典
索引状态
```

不创建新的左侧子菜单。

集团码目录列：目录名称、活动版本、记录数、索引状态、更新时间、占用空间、操作。

客户数据模板维护：模板名称、表头识别规则、字段别名、特殊空值、默认字段用途。

同义词/字典维护：标准值、别名、作用字段、作用类别、状态。

索引状态普通模式只显示目录版本、状态、构建进度、记录数、占用空间、最后更新时间。

### 44.19 系统设置 `/system`

只使用页签：

```text
服务状态
存储空间
临时文件
系统诊断
```

临时文件列：来源任务、类型、大小、创建时间、最后访问、使用状态、可清理。只有 `可清理=是` 才显示清理操作。

### 44.20 UI 状态与一致性要求

所有异步区域必须有加载态、空数据态、失败态、成功反馈。

所有提交按钮必须在提交中禁用、防重复点击，失败后保留用户输入。

长任务第一阶段允许 2 秒轮询；刷新后必须从后端恢复，前端不得自行推测任务已完成。

工作台筛选写入 URL query；刷新和返回后恢复原筛选条件和页码。

### 44.21 开发验收红线

以下任一项不满足即判定 UI 实现不符合设计：

1. 左侧出现超过 4 个一级菜单；
2. 登录后进入独立首页而不是 `/tasks`；
3. 人工确认被实现成独立一级菜单；
4. 临时文件被实现成独立一级菜单；
5. 任务列表页混入临时文件/目录版本管理；
6. 字段映射被强制实现成复杂连线画布且没有表格方式；
7. 候选详情只能三列横排导致字段信息不可读；
8. 工作台缺少第二候选分或分差筛选；
9. 工作台不能批量确认第一候选；
10. 快捷筛选维护独立隐藏状态，与正式筛选条件不一致。

## 45. 安装和运行详细规范

### 45.1 固定路径

```text
/opt/material_matcher
/etc/material_matcher
/var/lib/material_matcher
/var/log/material_matcher
```

不得按客户名变更。

### 45.2 最大数据盘

安装器：枚举本地持久化可写文件系统，排除 `/boot`、临时文件系统、只读和可移动介质，按可用空间降序选择推荐数据盘；应用仍统一通过 `/var/lib/material_matcher` 访问。

### 45.3 端口

默认范围 `12000~29999`。最多随机尝试 200 次，检查监听占用；找不到时顺序扫描；选定后写 `/etc/material_matcher/server.env`；升级不得重新随机。

### 45.4 管理员密码

用户名固定 `admin`。首次安装生成 10 位随机字母数字密码，写入：

```text
/etc/material_matcher/secret/admin_password.env
```

权限 `0600`，升级不重置密码。

### 45.5 systemd

服务名：`material_matcher.service`。

安装必须执行：

```bash
systemctl daemon-reload
systemctl enable --now material_matcher.service
```

安装成功判定以 `/api/health/ready` 通过为准。

### 45.6 生产运行用户

建议创建系统用户 `material_matcher`，无登录 shell；服务进程不得长期以 root 运行。

### 45.7 离线包

正式发布包必须包含 Python 运行时、Python 依赖、native 库、Vue 已构建静态文件、单比特索引引擎、默认配置模板、数据库迁移脚本、安装/升级/卸载/健康检查脚本。
