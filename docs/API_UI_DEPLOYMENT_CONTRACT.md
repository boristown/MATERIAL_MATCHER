# 物料集团码匹配引擎：核心函数、接口、UI、部署与验收规范

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

### 44.1 路由

前端必须拆分为以下路由：

```text
/login
/
/tasks
/tasks/:taskId
/profiles
/profiles/new
/profiles/:profileId/edit
/catalogs
/catalogs/:catalogId
/dictionaries
/reviews
/temp-files
/system
```

### 44.2 全局布局

最低支持 `1366×768`。

左侧导航：

- 展开宽度：220 px；
- 收起宽度：64 px；
- 桌面端默认展开。

顶部栏高度约 56 px，包含：

- 页面标题；
- 当前匹配方案（在方案编辑页显示）；
- 服务状态；
- `admin` 菜单。

主要内容区滚动，不允许整个侧边栏随页面滚动消失。

### 44.3 登录页

字段：

- 账号：固定显示 `admin`，不可编辑；
- 密码：必填；
- 登录按钮；
- 错误信息区域。

行为：

- 密码为空时前端阻止提交；
- 失败不清空账号；
- 连续失败只显示“用户名或密码错误”，不泄露更多信息；
- 登录成功跳首页。

### 44.4 首页

卡片固定顺序：

1. 新建匹配任务；
2. 新建匹配方案；
3. 待复核数量；
4. 最近任务；
5. 集团码数据状态；
6. 数据磁盘使用量。

不得在首页放高级索引参数。

### 44.5 配置方案列表

列：

```text
方案名称
当前版本
适用类别
状态
最近发布时间
最近试跑
操作
```

操作：

- 编辑草稿；
- 复制；
- 查看版本；
- 新建任务；
- 归档。

已发布版本不可直接编辑。

### 44.6 七步配置向导

顶部步骤固定：

```text
1 客户物料
2 集团码数据
3 分类范围
4 字段对应
5 权重与阈值
6 试跑验证
7 发布方案
```

底部固定按钮区域：

```text
[上一步]              [保存草稿] [下一步]
```

离开页面前如果存在未保存变化必须提示。

草稿自动保存：用户停止操作 5 秒后保存；同一时刻最多一个保存请求。

### 44.7 第一步：客户物料

上传区域完成后显示：

- 文件名称；
- 大小；
- SHA-256 前 8 位；
- 工作表选择；
- 表头行；
- 记录数估计；
- 字段表。

字段表列：

```text
列序号
原始列名
样例1
样例2
推测用途
风险
```

用户修改 Sheet 或表头行后，500 ms 防抖重新预览。

### 44.8 第二步：集团码数据

两种卡片：

- 选择已有集团码目录；
- 上传新目录版本。

选择已有目录时展示：

- 名称；
- 版本；
- 行数；
- 集团码字段；
- 索引状态。

索引未完成时允许继续配置，但发布前必须校验是否满足当前召回策略。

### 44.9 第三步：分类范围

首先选择：

```text
○ 全局匹配
○ 同组严格匹配
○ 分类映射匹配
```

严格/映射模式必须选择：

- 客户分类字段；
- 集团分类字段。

映射模式显示二维表：

```text
客户分类      允许的集团分类                状态
A             分类1、分类2                  已配置
B             分类3                         已配置
C             -                             未配置
```

存在未配置且 `unmapped_policy=reject` 时允许保存，但发布前明确提示这些类别将不自动匹配。

### 44.10 第四步：字段对应

表格固定列：

```text
序号
客户字段组合
集团字段组合
组合方式
匹配方式
关键字段
操作
```

客户字段组合和集团字段组合使用“标签 + 添加”组件。

点击添加字段弹出字段选择器；选中多个字段后按拖动顺序保存。

组合方式：

- 拼接；
- 依次取第一个有效值；
- 多个比较取最高分。

匹配方式：

- 完全一致；
- 清洗后完全一致；
- 包含；
- 字符串相似；
- 关键词相似；
- 数值/尺寸；
- 标准号；
- 向量语义；
- 综合匹配。

### 44.11 第五步：权重与阈值

每条规则显示：

```text
规则名 | 权重数字框(0-100) | 滑块 | 实际占比 | 关键冲突设置
```

权重只允许整数。

实际占比：

```text
weight_i / sum(enabled_weights)
```

保留 1 位小数显示。

阈值区：

```text
自动匹配成功阈值  [88]
启用人工复核      [开关]
人工复核下限      [75]
显示分系数        [1.00]
前 N 名输出        [5]
```

校验：

- success 1~100；
- review 0~99；
- review < success；
- display coefficient 0.1~3.0；
- TopN 1~50。

### 44.12 第六步：试跑

顶部：

```text
[试跑100条] [重新试跑]
```

统计卡片：

- 总数；
- 自动匹配；
- 待复核；
- 未匹配。

结果表：

```text
客户物料号
客户描述
第一候选集团码
显示相似度
状态
操作
```

“查看详情”打开右侧抽屉，宽度不小于 720 px，含：

- 客户原始字段；
- TopN 候选标签页；
- 每个候选的字段得分条；
- 关键冲突；
- 标准化前后值；
- 原始分/显示分。

### 44.13 第七步：发布

发布前校验列表必须逐项显示：

```text
✓ 客户数据结构有效
✓ 集团码数据有效
✓ 分类路由完整
✓ 字段规则有效
✓ 权重有效
✓ 阈值有效
✓ 已完成试跑
✓ 索引可用或允许自动构建
```

任何红色错误项存在时禁用“发布”。

发布成功后显示：

- 方案名称；
- 版本号；
- 发布时间；
- “立即创建匹配任务”。

### 44.14 任务详情

顶部进度区：

```text
状态
百分比
已处理/总数
开始时间
预计剩余
```

运行中按钮：

- 取消任务；
- 刷新。

完成后：

- 下载结果；
- 查看在线结果；
- 查看人工复核。

### 44.15 人工复核

左表、右详情布局：

左侧记录列表支持：

- 仅看待复核；
- 相似度排序；
- 分类筛选；
- 关键冲突筛选。

右侧候选列表每个候选显示：

- 集团码；
- 总分；
- 字段明细；
- `[确认此候选]`。

底部另有：

- `[所有候选都不正确]`
- `备注`

人工确认后立即移出待复核队列，并记录审计。

### 44.16 集团码数据页

目录列表列：

```text
目录名称
活动版本
记录数
索引状态
更新时间
占用空间
操作
```

新版本上传后不自动替换活动版本；索引成功并经用户确认后才可激活。

### 44.17 临时文件

列：

```text
来源任务
类型
大小
创建时间
最后访问时间
使用状态
可清理
```

只有 `可清理=是` 才出现删除按钮。

### 44.18 UI 状态要求

所有请求必须有：

- 加载态；
- 空数据态；
- 失败态；
- 成功反馈。

按钮提交中必须防重复点击。

长任务状态由轮询或服务端事件更新；第一阶段允许 2 秒轮询。

---

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

安装器：

1. 枚举本地持久化可写文件系统；
2. 排除 `/boot`、临时文件系统、只读、可移动介质；
3. 按可用空间降序；
4. 选择第一名作为推荐；
5. 若用户非交互安装则采用推荐；
6. 应用仍通过 `/var/lib/material_matcher` 访问。

### 45.3 端口

默认范围：

```text
12000~29999
```

算法：

1. 最多随机尝试 200 次；
2. 使用系统随机源；
3. 检查监听占用；
4. 找不到时顺序扫描；
5. 选定后写 `/etc/material_matcher/server.env`；
6. 升级不得重新随机。

### 45.4 管理员密码

- 用户名固定：`admin`
- 首次安装生成 10 位随机字母数字密码；
- 密码文件：

```text
/etc/material_matcher/secret/admin_password.env
```

- 权限：`0600`
- 升级不重置密码；
- 提供维护命令重置密码，但不得自动改。

### 45.5 systemd

服务名：

```text
material_matcher.service
```

安装必须执行：

```bash
systemctl daemon-reload
systemctl enable --now material_matcher.service
```

安装成功判定不是 `systemctl start` 返回 0，而是 `/api/health/ready` 通过。

### 45.6 生产运行用户

建议创建：

```text
material_matcher
```

系统用户，无登录 shell。

服务进程不得以 root 长期运行。

### 45.7 离线包

正式发布包必须包含：

- Python 运行时；
- Python 依赖；
- native 库；
- Vue 已构建静态文件；
- 单比特索引引擎；
- 默认配置模板；
- 数据库迁移脚本；
- 安装/升级/卸载/健康检查脚本。

---

## 46. 临时文件生命周期

### 46.1 目录

```text
/var/lib/material_matcher/tmp/
├── upload_chunks/
├── previews/
├── dry_runs/
├── job_work/
└── exports_tmp/
```

### 46.2 Manifest

每个临时对象必须登记：

```python
class TempArtifact:
    artifact_id: str
    task_id: str | None
    category: str
    path: str
    size_bytes: int
    created_at: str
    last_access_at: str
    in_use: bool
    safe_to_delete: bool
```

清理逻辑只能根据登记的 artifact 删除，禁止接受前端任意路径。

### 46.3 自动清理

默认建议：

- 分块上传失败：24 小时；
- 预览：3 天；
- Dry Run 中间数据：7 天；
- 失败任务工作区：7 天；
- 已完成任务工作区：结果成功落盘后即可标记可清理。

具体天数可在系统管理页调整。

---

## 47. 日志、审计与诊断

### 47.1 日志文件

```text
/var/log/material_matcher/app.log
/var/log/material_matcher/task.log
/var/log/material_matcher/audit.log
```

### 47.2 每条业务日志最少字段

```text
timestamp
level
request_id
task_id
module
message
```

不得记录管理员明文密码。

### 47.3 审计事件

必须记录：

- 登录成功/失败；
- 发布方案；
- 回滚方案；
- 激活集团码版本；
- 人工确认；
- 删除/清理；
- 取消任务；
- 重置密码。

### 47.4 诊断信息

UI“复制诊断信息”输出：

- 程序版本；
- OS；
- CPU 架构；
- 端口；
- 数据盘；
- 磁盘剩余；
- 当前活动目录版本；
- 索引状态；
- 最近 20 条错误摘要。

不包含密码和数据内容。

---

## 48. 性能与资源约束

### 48.1 算法复杂度

正式匹配不得执行：

```text
100,000 × 1,000,000
```

完整字段精排。

必须先将候选缩小到可配置 `retrieval_top_k`。

### 48.2 内存

读取百万级集团码数据时应采用：

- 只读/分块；
- mmap 索引；
- 避免重复字符串副本；
- 可复用目录索引。

任务结束必须释放批次内存。

### 48.3 并发

第一阶段默认：

- 允许多个浏览器请求；
- 同时只运行 1 个重型匹配/索引任务；
- 其他任务排队。

后续可通过配置提高重型任务并发数。

这样优先保证客户服务器稳定，不因并发把内存耗尽。

### 48.4 磁盘空间保护

任务启动前估算：

```text
临时空间 + 结果空间 + 安全余量
```

不足时直接返回 `DISK_SPACE_LOW`，不得运行到一半写满系统盘。

---

## 49. 安全要求

- 固定 admin，不建设其他用户；
- 密码不得写入前端包；
- 密码不得写日志；
- 会话失效默认 8 小时，可配置；
- 文件名必须净化，实际路径使用系统生成 ID；
- 所有下载必须根据数据库记录解析文件，禁止用户提交任意服务器路径；
- ZIP/压缩包导入必须防路径穿越；
- Excel 预览不得执行宏；
- `.xlsm` 只读取数据，不执行 VBA；
- 导出以 `= + - @` 开头的用户文本时应防止公式注入，必要时写为文本；
- systemd 开启 `NoNewPrivileges=true` 等安全选项。

---

## 50. 测试与验收

### 50.1 单元测试

必须覆盖：

- 归一化；
- 空值规则；
- 同义词优先级；
- concat/coalesce/best_of；
- 各字段 matcher；
- 动态权重公式；
- 固定权重公式；
- 关键字段封顶；
- 阈值边界；
- 分类路由；
- 分类映射无命中；
- BBQ build/save/load/search；
- Excel 前导零；
- Join 重复键和爆炸。

### 50.2 阈值边界用例

若：

```text
success = 88
review = 75
```

必须测试：

| raw | 预期 |
|---:|---|
| 0.880001 | MATCHED |
| 0.880000 | REVIEW |
| 0.750001 | REVIEW |
| 0.750000 | UNMATCHED |
| 0.749999 | UNMATCHED |

### 50.3 端到端

至少：

1. 上传客户 Excel；
2. 上传集团码 Excel；
3. 生成方案；
4. Dry Run；
5. 发布；
6. 创建正式任务；
7. 完成；
8. 下载；
9. 校验 Excel；
10. 人工复核。

### 50.4 零代码客户验收

准备 3 套结构完全不同的数据：

- 单表；
- 多表 Join；
- 多目录/多类别。

同一程序二进制运行。

验收时执行：

```text
git diff 核心代码 = 0
```

客户差异只允许出现在配置/字典/数据文件。

### 50.5 安装测试

必须在干净银河麒麟 V10 环境至少验证：

- x86_64；
- 若客户使用 ARM，则增加 aarch64；
- 无 Docker；
- 无互联网；
- 无预装 Python 依赖。

安装后：

```text
systemctl is-enabled material_matcher.service
systemctl is-active material_matcher.service
/api/health/ready
```

三项均通过。
