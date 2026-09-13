# 物料集团码匹配引擎：开发实施强制规范

## 21. 规范使用规则

### 21.1 关键用词

为避免“建议”和“必须”混用，本部分采用以下约定：

- **必须**：实现时不可省略，测试必须覆盖。
- **不得**：明确禁止，代码评审发现后必须修改。
- **建议**：默认应采用；如不采用，需在代码评审中说明原因。
- **可选**：不影响第一阶段上线，可在后续版本实现。
- **默认值**：新建方案时系统自动填入的值，用户可修改。
- **内部值**：服务端内部使用，普通业务界面不直接展示。
- **显示值**：业务界面显示给用户的值。

### 21.2 冲突优先级

设计资料出现冲突时，按以下优先级执行：

1. 本文；
2. 主开发设计书；
3. `OPERATION_UI_DESIGN.md`；
4. 其他专项设计文档；
5. 当前代码中的临时实现。

当前代码如果与本规范冲突，视为“待改造”，不得反过来修改规范以迁就临时代码。

### 21.3 第一阶段产品边界

第一阶段必须完成：

- 浏览器端上传客户物料与集团码数据；
- Excel/CSV 数据识别和预览；
- 多表关联；
- 字段一对一、一对多、多对一、多对多配置；
- 标准化和同义词；
- 数字权重；
- 物料分类/物料组范围配置；
- 小批量试跑；
- 正式批量匹配任务；
- 前 N 名候选；
- 人工复核；
- 匹配结果 Excel 导出；
- 集团码数据版本管理；
- 单比特向量索引构建与候选召回；
- 银河麒麟 Linux V10 无 Docker 一键安装；
- 固定 `admin` 账号和随机 10 位密码；
- 临时文件管理；
- 配置版本和回滚。

第一阶段不建设：

- 多租户；
- 多角色用户权限；
- 复杂审批流；
- 云端依赖；
- 必须依赖 Docker 的组件；
- 针对某一家客户硬编码的分支。

---

## 22. 技术栈与工程约束

### 22.1 服务端

第一阶段固定采用：

| 项目 | 规范 |
|---|---|
| 语言 | Python 3.10 及以上，发布包固定携带自有 Python 运行时 |
| Web 框架 | FastAPI |
| 数据校验 | Pydantic 2 |
| Excel | openpyxl；大文件读取必须使用只读/流式模式 |
| 数值计算 | NumPy |
| 配置格式 | YAML；业务用户不直接编辑 |
| 元数据存储 | SQLite，单机内嵌，不新增独立数据库服务 |
| 大文件存储 | 本地文件系统，统一逻辑路径 |
| 向量索引 | 内置单比特向量索引；接口允许替换 |
| 服务管理 | systemd |
| 部署 | 离线安装包，不依赖 Docker |

当前工程依赖版本范围以 `pyproject.toml` 为准；发布前必须锁定依赖并生成离线 wheelhouse。

### 22.2 前端

第一阶段固定采用：

| 项目 | 规范 |
|---|---|
| 框架 | Vue 3 |
| 语言 | TypeScript |
| 构建 | Vite |
| UI 组件 | Element Plus |
| HTTP | Axios |
| 路由 | vue-router，必须拆分为独立页面路由 |
| 图表 | ECharts，可用于任务统计和试跑分布 |
| 生产部署 | 构建为静态文件，由服务端同端口提供 |

现场服务器不得执行 `npm install`、`npm run build`。

### 22.3 编码与时间

- 所有文本统一 UTF-8。
- 服务端时间统一使用服务器本地时区保存 ISO 8601，同时数据库额外保存 Unix 时间戳。
- 所有 ID、物料号、集团码、分类码按**字符串**处理。
- 禁止把物料号、集团码转换为整数或浮点数。
- Excel 导出编码类字段必须设置为文本格式，避免科学计数法和前导零丢失。

---

## 23. 推荐代码目录与模块职责

正式工程目录按以下结构收敛：

```text
src/material_matcher/
├── api/
│   ├── auth.py
│   ├── files.py
│   ├── profiles.py
│   ├── catalogs.py
│   ├── tasks.py
│   ├── reviews.py
│   ├── dictionaries.py
│   └── system.py
├── domain/
│   ├── models.py
│   ├── enums.py
│   └── errors.py
├── ingestion/
│   ├── excel.py
│   ├── csv.py
│   ├── inspector.py
│   └── joins.py
├── config/
│   ├── schema.py
│   ├── compiler.py
│   └── validator.py
├── normalize/
│   ├── pipeline.py
│   ├── synonym.py
│   ├── standard_code.py
│   ├── dimension.py
│   └── unit.py
├── matching/
│   ├── exact.py
│   ├── fuzzy.py
│   ├── token.py
│   ├── numeric.py
│   ├── semantic.py
│   ├── hybrid.py
│   ├── scorer.py
│   └── decision.py
├── retrieval/
│   ├── interface.py
│   ├── inverted.py
│   ├── bbq.py
│   └── auto.py
├── embedding/
│   ├── interface.py
│   ├── local_model.py
│   └── hashing_fallback.py
├── tasks/
│   ├── queue.py
│   ├── worker.py
│   ├── progress.py
│   └── recovery.py
├── storage/
│   ├── metadata.py
│   ├── files.py
│   └── layout.py
├── export/
│   ├── xlsx.py
│   └── csv.py
├── security/
│   ├── auth.py
│   └── session.py
├── services/
│   ├── match_service.py
│   ├── catalog_service.py
│   └── profile_service.py
├── settings.py
└── cli.py
```

要求：

- API 层不得实现匹配算法。
- 前端不得实现客户专属匹配规则。
- 核心匹配代码不得出现 `if customer == ...`、`if institute == ...`。
- 13 所的 A001/A002/A003/A005/A006/A007 只能出现在业务配置或测试样例中。

---

## 24. 核心业务对象定义

### 24.1 文件对象

```python
class FileRecord:
    file_id: str               # 32 位小写十六进制 UUID4
    role: str                  # source | target | supplement
    original_name: str
    stored_path: str
    size_bytes: int
    sha256: str
    created_at: str
    status: str                # UPLOADING | READY | INVALID | DELETED
```

约束：

- `file_id` 必须唯一；
- `sha256` 以完整文件内容计算；
- 正式持久化后不得用原始文件名作为存储主键；
- 删除时只能删除系统登记过的路径。

### 24.2 数据集对象

```python
class Dataset:
    dataset_id: str
    name: str
    columns: list[str]
    row_count: int
    rows: Iterable[dict[str, object]]
    source_file_id: str | None
```

大数据场景不得要求一次性把百万行全部复制为多份 Python `dict` 常驻内存；接口允许流式、分块或列式实现。

### 24.3 集团码目录对象

集团码目录是可重复使用的目标数据版本。

```python
class CatalogVersion:
    catalog_id: str
    version_id: str
    name: str
    source_file_id: str
    row_count: int
    group_code_column: str
    status: str              # IMPORTING | READY | INDEXING | READY_INDEXED | FAILED
    sha256: str
    created_at: str
    active: bool
```

目录版本发布后不可原地修改；更新数据必须创建新版本。

### 24.4 匹配方案对象

```python
class ProfileVersion:
    profile_id: str
    version_no: int
    name: str
    status: str              # DRAFT | PUBLISHED | ARCHIVED
    schema_version: int
    document: dict
    sha256: str
    created_at: str
    published_at: str | None
```

发布版本必须不可变。任何修改生成新版本。

### 24.5 任务对象

```python
class MatchTask:
    task_id: str
    name: str
    profile_id: str
    profile_version: int
    source_file_id: str
    catalog_version_id: str
    status: str
    progress: float          # 0.0 ~ 100.0
    processed_rows: int
    total_rows: int
    created_at: str
    started_at: str | None
    finished_at: str | None
    error_code: str | None
    error_message: str | None
    result_file_id: str | None
```

任务必须记录所使用的**精确方案版本和集团码数据版本**，保证结果可复现。

### 24.6 人工复核记录

```python
class ReviewRecord:
    review_id: str
    task_id: str
    source_row_id: str
    original_status: str
    selected_group_code: str | None
    action: str              # CONFIRM_CANDIDATE | REJECT_ALL | MANUAL_INPUT
    operator: str            # 固定 admin
    comment: str
    created_at: str
```

---

## 25. 元数据持久化设计

### 25.1 SQLite 位置

固定：

```text
/var/lib/material_matcher/meta/material_matcher.db
```

必须启用：

```sql
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;
```

### 25.2 最低表集合

必须至少包含：

- `files`
- `catalogs`
- `catalog_versions`
- `profiles`
- `profile_versions`
- `tasks`
- `reviews`
- `dictionaries`
- `dictionary_versions`
- `index_versions`
- `audit_events`

大体量物料明细、向量和结果文件不得全部塞入 SQLite BLOB。

### 25.3 崩溃恢复

服务启动时：

1. 查询状态为 `RUNNING/PREPARING/EXPORTING` 的任务；
2. 将其改为 `RECOVERING`；
3. 根据任务阶段决定重新入队或标记失败；
4. 不允许任务永远停留在“运行中”。

---

## 26. 文件上传与表格识别契约

### 26.1 文件类型

第一阶段：

- `.xlsx`
- `.xlsm`
- `.csv`

`.xls` 第一阶段不支持；界面必须明确提示转换为 `.xlsx`，不得静默失败。

### 26.2 文件大小

分两种路径：

1. **配置样表快速上传**：默认上限 120 MB；
2. **正式数据文件**：必须支持大文件分块上传，默认总上限 2 GB，可在系统配置中调整。

超过 120 MB 时前端自动切换为分块上传，不要求用户手工选择模式。

### 26.3 分块上传

默认：

- 分块大小：8 MB；
- 每块携带序号和整体上传 ID；
- 服务端按序写临时文件；
- 完成后计算 SHA-256；
- 校验通过后原子移动到正式上传目录。

中断后允许续传。

### 26.4 表头识别

函数：

```python
inspect_tabular_file(
    file_path: Path,
    *,
    max_scan_rows: int = 30,
    sample_data_rows: int = 20
) -> InspectionResult
```

输出：

```python
class InspectionResult:
    file_type: str
    sheets: list[SheetInspection]
    recommended_sheet: str | None
    warnings: list[InspectionWarning]
```

工作表：

```python
class SheetInspection:
    sheet_name: str
    recommended_header_row: int       # 1-based
    header_confidence: float           # 0~1
    row_count_estimate: int
    column_count: int
    columns: list[ColumnInspection]
```

字段：

```python
class ColumnInspection:
    index: int                         # 1-based
    header: str
    samples: list[str]
    inferred_type: str                 # TEXT | NUMBER | DATE | MIXED
    business_hint: str | None
    hint_confidence: float
    null_rate_sample: float
    unique_rate_sample: float
    leading_zero_risk: bool
```

### 26.5 前导零

物料号/集团码的处理规则：

- Excel 单元格为文本：原样读取；
- Excel 单元格为数字但单元格格式为 `000000` 等固定零格式：允许根据格式恢复前导零；
- Excel 已经以普通数字保存且无格式信息：无法可靠恢复，必须产生风险提示；
- 不得擅自猜测需要补多少位零。

---

## 27. 数据集读取与多表关联

### 27.1 数据源规范

```yaml
datasets:
  主表:
    adapter: excel
    file_ref: "FILE_ID"
    options:
      sheet: "Sheet1"
      header_row: 1

  补充表:
    adapter: excel
    file_ref: "FILE_ID"
    options:
      sheet: "数据"
      header_row: 2
```

运行时业务配置只保存 `file_ref/catalog_ref`，不得长期依赖浏览器本地路径。

### 27.2 关联类型

第一阶段只允许：

- `left` 左关联；
- `inner` 内关联。

不实现隐式笛卡尔积。

### 27.3 关联键

```yaml
joins:
  - id: "主表_补充表"
    left: "主表"
    right: "补充表"
    type: left
    keys:
      - left: "物料"
        right: "MATNR"
```

所有关联键在比较前执行最小标准化：

- 字符串化；
- 去前后空格；
- 不改变中间字符；
- 不删除前导零。

### 27.4 重复键策略

每个 Join 必须显式配置：

```yaml
duplicate_policy: error
```

允许：

- `error`：右表同键多行时停止并提示；
- `first`：按原始顺序取第一行；
- `aggregate`：按指定字段聚合；
- `explode`：生成多行，仅高级模式允许。

默认 `error`。

`explode` 必须设置 `max_matches_per_left`，默认 20；超过时任务失败并给出业务可读错误。

---

## 28. 字段引用、组合与转换

### 28.1 字段引用

字段引用使用业务配置内的数据集别名和列名，不要求全局固定逻辑字段。

示例：

```yaml
source_fields:
  - dataset: "客户物料"
    column: "物料名称"
```

### 28.2 组合策略

每一侧字段组合只允许以下三类，避免语义模糊：

#### `concat`

按顺序拼接有效字段：

```text
名称 + 型号 + 规格
```

参数：

```yaml
combine:
  type: concat
  separator: " "
  skip_empty: true
  deduplicate: true
```

#### `coalesce`

按顺序取第一个非空字段：

```text
型号 → 型号(牌号) → 型号规格
```

#### `best_of`

不先拼接；对多个字段组合分别计算匹配分，取最高分。适用于“标准号可能落在多个列”的情况。

### 28.3 转换操作

第一阶段转换操作及其精确定义：

| 操作 | 输入 | 输出 | 说明 |
|---|---|---|---|
| copy | 1 字段 | 原值 | 不改变 |
| constant | 常量 | 常量 | 补固定业务值 |
| concat | 多字段 | 字符串 | 顺序拼接 |
| coalesce | 多字段 | 单值 | 第一非空 |
| trim | 1 字段 | 字符串 | 去首尾空格 |
| lower | 1 字段 | 字符串 | 英文转小写 |
| upper | 1 字段 | 字符串 | 英文转大写 |
| replace | 1 字段 | 字符串 | 普通替换 |
| regex_replace | 1 字段 | 字符串 | 正则替换 |
| regex_extract | 1 字段 | 字符串 | 正则提取 |
| value_map | 1 字段 | 任意 | 显式值映射 |
| dictionary_map | 1 字段 | 字符串 | 使用业务词典 |
| nullify | 1 字段 | 原值/空 | 指定占位值转空 |
| join_unique | 多字段 | 字符串 | 去重后拼接 |

任何新转换必须作为通用操作增加，禁止在转换函数中写某个客户名称。

---

## 29. 标准化流水线

### 29.1 默认顺序

同一个字段的标准化必须固定顺序：

```text
原值
→ 字符串化
→ 空值识别
→ 首尾空格
→ 全角/半角
→ 大小写
→ 标点/空白规范
→ 同义词映射
→ 字段专用规范化
→ 输出标准化值
```

### 29.2 空值

全局默认空值：

```text
""、仅空格、<NULL>、NULL、N/A
```

`88`、`-`、`/` 是否为空**不得全局写死**，必须由客户/字段配置。

原因：这些字符串在某些客户数据中可能是真实业务值。

### 29.3 标准号规范化

标准号比较至少处理：

- `GB/T5133-1985` 与 `GB/T 5133-1985`；
- 全角/半角；
- 多余空格；
- 大小写；
- 连字符差异。

不得删除标准号中的年份或版本号。

### 29.4 尺寸规范化

第一阶段必须识别常见符号：

- `Φ`、`φ`、`Ø` 统一；
- `×`、`x`、`X` 统一；
- `δ` 保留其“厚度”含义；
- 数字和单位允许分离解析。

数值相似度默认允许的相对误差为 `2%`，但必须可在规则中配置。

---

## 30. 同义词词典

### 30.1 作用域优先级

从高到低：

1. 当前字段；
2. 当前物料类别；
3. 当前匹配方案；
4. 客户全局；
5. 系统全局。

高优先级覆盖低优先级。

### 30.2 词典结构

```yaml
- canonical: "北京某电子有限公司"
  aliases:
    - "北京某电子"
    - "某电子"
  enabled: true
```

同一个别名不得同时指向两个启用状态的标准词；保存时必须校验冲突。

### 30.3 词典命中

默认采用标准化后**完全命中别名**再替换，不默认做子串替换，避免把型号内部片段误改。

---

## 31. 字段匹配算法契约

### 31.1 统一接口

```python
class FieldMatcher(Protocol):
    matcher_id: str

    def score(
        self,
        source_value: str,
        target_value: str,
        options: dict[str, object]
    ) -> "FieldScore":
        ...
```

输出：

```python
class FieldScore:
    score: float              # 必须在 0.0~1.0
    source_normalized: str
    target_normalized: str
    explanation: str
    details: dict[str, object]
```

### 31.2 第一阶段算法

#### 完全一致

- 双方标准化后相同：`1.0`
- 否则：`0.0`
- 任一为空：不参与评分，而不是记 `0.0`，由缺失字段策略决定。

#### 包含关系

- A 包含 B 或 B 包含 A：`1.0`
- 否则 `0.0`

只建议用于描述类字段，不建议用于短型号。

#### 字符串模糊

使用稳定的字符序列相似度实现，结果范围 `0~1`。算法实现更换时必须通过回归集。

#### 关键词相似

默认 Jaccard：

```text
score = |A ∩ B| / |A ∪ B|
```

若两边 token 集合都为空，字段视为不可比较。

#### 数值/尺寸相似

1. 提取数值序列和单位；
2. 单位能够换算时先统一；
3. 一一匹配数值；
4. 相对误差不超过配置值视为数值命中；
5. 数值分和文本分按规则配置合成。

#### 标准号比较

先执行标准号规范化，再：

- 完全一致优先为 1；
- 主编号一致、年份不同不得自动视为完全一致；
- 具体部分号不同不得忽略。

#### 向量语义相似

输出经映射后的 `0~1` 分值。Embedding 提供器和向量模型是配置，不写死客户。

### 31.3 综合匹配

综合匹配不能写死 `70% + 30%`。

配置示例：

```yaml
method:
  type: hybrid
  components:
    - matcher: fuzzy
      weight: 70
    - matcher: semantic
      weight: 30
```

子算法权重同样按数值归一化。

---

## 32. 字段权重与综合分公式

### 32.1 业务权重

业务界面输入：

```text
0~100 整数
```

服务端请求和配置文件也保存 `0~100`，禁止前端提前除以 100 后再传，以免不同客户端产生两套口径。

### 32.2 有效字段集合

对于某个候选对，定义有效规则集合：

```text
A = {规则 r | source_value 非空 且 target_value 非空 且 weight_r > 0}
```

默认缺失字段策略为 `dynamic_weight`。

### 32.3 综合分

若 `A` 非空：

```text
raw_score =
    Σ(score_r × weight_r)
    ---------------------
       Σ(weight_r)
```

`raw_score` 范围必须裁剪到 `[0,1]`。

若 `A` 为空：

```text
raw_score = 0
reason = NO_COMPARABLE_FIELDS
```

### 32.4 固定权重模式

只有方案显式选择 `fixed_weight` 时：

```text
raw_score =
    Σ(score_r × weight_r)
    ---------------------
      Σ(全部启用 weight)
```

缺失字段按 0 分参与。

### 32.5 关键字段

关键字段不使用底层固定常量，规则配置必须包含：

```yaml
critical:
  enabled: true
  conflict_below: 25
  score_cap: 79
```

含义：

- 字段得分 `< 25分` 视为明显冲突；
- 冲突后综合显示分上限为 `79分`；
- 内部上限为 `0.79`。

`conflict_below` 和 `score_cap` 均可配置。

多个关键规则同时触发时取**最低上限**。

---

## 33. 显示分与判定分

### 33.1 默认显示

```text
display_score = round(raw_score × 100, 2)
```

### 33.2 显示系数

若客户配置显示系数：

```text
display_score =
  clamp(round(raw_score × 100 × display_coefficient, 2), 0, 100)
```

默认：

```text
display_coefficient = 1.0
```

允许范围建议 `0.1~3.0`。

### 33.3 重要约束

**所有自动匹配判断必须使用 `raw_score` 与内部阈值，不得使用经过显示系数调整后的分数。**

UI 必须在配置显示系数时提示：

> 该参数只改变界面展示分值，不改变是否匹配成功的判断。

---

## 34. 分类/物料组范围规则

### 34.1 三种模式

枚举固定为：

```text
GLOBAL   全局范围
STRICT   同组严格
MAPPED   映射范围
```

这三个是引擎能力，不是客户物料类别。

### 34.2 全局

不按物料组过滤，但仍受当前路由选择的集团码目录限制。

### 34.3 同组严格

```text
normalize(source_group) == normalize(target_group)
```

才允许进入候选。

### 34.4 映射范围

示例：

```yaml
mapping:
  "客户组A": ["集团分类1", "集团分类2"]
```

没有映射时默认：

```text
0 个候选
reason = GROUP_MAPPING_NOT_FOUND
```

不得自动退回全局搜索，除非方案显式配置：

```yaml
unmapped_policy: global
```

### 34.5 路由优先级

多物料类别路由按 `priority` 从小到大匹配，首个命中即停止。

每个方案必须有明确 `default_route`：

- `reject`：未命中任何分类时不自动匹配；
- `catalog`：进入指定默认集团码目录。

---

## 35. 单比特向量候选召回规范

### 35.1 职责边界

向量召回只负责：

> 尽量让正确集团物料进入候选集合。

不得直接把向量第一名视为最终集团码。

### 35.2 目标向量

目标向量按每维均值中心化后保存符号位：

```text
bit_i = 1, vector_i >= center_i
bit_i = 0, vector_i <  center_i
```

主体空间：

```text
ceil(dimensions / 8) bytes / vector
```

512 维时为 64 字节/条。

### 35.3 查询量化

查询向量标准化：

```text
z_i = (q_i - center_i) / scale_i
```

裁剪到：

```text
[-2.5, +2.5]
```

再量化到有符号 4 比特幅度范围：

```text
[-7, +7]
```

实现上是 1 个符号 + 3 个幅度 bit-plane。

### 35.4 索引文件格式

每个索引版本目录：

```text
/var/lib/material_matcher/indexes/<catalog_version>/<model_id>/
├── meta.json
├── packed.npy
├── center.npy
├── scale.npy
├── ids.json
└── rerank_f16.npy       # 可选
```

`meta.json` 至少包含：

```json
{
  "format": "bbq-flat-v1",
  "dimensions": 512,
  "count": 1000000,
  "embedding_provider": "xxx",
  "catalog_version": "xxx",
  "created_at": "..."
}
```

### 35.5 检索接口

```python
search_batch(
    queries: np.ndarray,
    top_k: int,
    *,
    candidate_indices: np.ndarray | None = None,
    rerank: bool = False,
    oversample: int = 4
) -> list[list[SearchHit]]
```

`SearchHit`：

```python
class SearchHit:
    index: int
    item_id: str
    score: float
```

### 35.6 分批原则

必须提供真正的 `search_batch`，不得在 API 层用 Python 循环反复调用单条接口。

默认批量大小由内存和 CPU 自适应；初始默认可设为 256，配置范围 `16~4096`。

### 35.7 高精度重排

可选 `rerank_f16.npy`。启用时：

1. BBQ 先取 `top_k × oversample`；
2. 对这些候选用 float16/float32 余弦重排；
3. 再进入字段级业务精排。

是否启用由目录索引配置决定。

---

## 36. 候选召回策略

### 36.1 召回顺序

默认：

```text
分类/物料组范围过滤
→ 精确强字段预过滤（如配置）
→ 倒排关键词召回
→ BBQ 向量召回
→ 候选并集去重
→ 限制 candidate_limit
→ 完整字段精排
```

### 36.2 候选上限

业务配置中区分：

- `retrieval_top_k`：召回给精排的候选数；
- `output_top_n`：最终输出的候选数。

两者不得混用。

推荐初值：

```text
retrieval_top_k = 200
output_top_n = 5
```

这只是方案初值，可配置，不属于底层固定业务规则。

### 36.3 无候选

若过滤后无候选：

```text
status = UNMATCHED
score = 0
reason = NO_CANDIDATE
```

不得从其他类别偷偷补候选。

---

## 37. 决策规则

### 37.1 UI 阈值

业务界面：

```text
success_threshold: 0~100
review_threshold: 0~100 或关闭人工复核
```

必须满足：

```text
0 <= review_threshold < success_threshold <= 100
```

### 37.2 内部阈值

```text
success_raw = success_threshold / 100
review_raw  = review_threshold / 100
```

### 37.3 判定

必须严格按：

```text
raw_score > success_raw
    => MATCHED

review_enabled
and raw_score > review_raw
and raw_score <= success_raw
    => REVIEW

其他
    => UNMATCHED
```

因此：

- 恰好等于成功阈值：**不是自动匹配成功**；
- 恰好等于复核阈值：**不是人工复核**。

### 37.4 集团码填写

正式结果：

- `MATCHED`：填写最终集团码；
- `REVIEW`：最终集团码留空，只保留候选；
- `UNMATCHED`：最终集团码留空；
- 人工确认后状态改为 `MANUAL_MATCHED`，填写人工确认集团码。

这条规则必须在前端、后端、Excel 导出三处保持一致。

---

## 38. 匹配任务状态机

### 38.1 状态

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

### 38.2 合法迁移

```text
PENDING -> PREPARING
PREPARING -> RUNNING
RUNNING -> EXPORTING
EXPORTING -> COMPLETED

PENDING/PREPARING/RUNNING/EXPORTING -> FAILED
PENDING/PREPARING/RUNNING -> CANCELLING -> CANCELLED
RUNNING/PREPARING/EXPORTING -> RECOVERING -> PENDING/FAILED
```

其他迁移一律拒绝。

### 38.3 进度

进度 `0~100`，只能单调递增，阶段建议：

```text
0~5      准备
5~90     匹配
90~98    输出
98~100   收尾
```

进度必须持久化，浏览器刷新后可以恢复。

### 38.4 取消

取消是协作式：

- 每处理一个批次检查取消标志；
- 已进入最终文件原子写入阶段时可延迟取消；
- 取消后不得留下“已完成”结果。

---

## 39. 输出 Excel 精确定义

### 39.1 工作簿

正式输出至少包含：

1. `任务摘要`
2. `匹配结果`
3. `TopN候选`
4. `人工复核记录`（存在人工复核时）

### 39.2 任务摘要

固定字段：

| 字段 | 内容 |
|---|---|
| 任务编号 | task_id |
| 任务名称 | 用户输入 |
| 匹配方案 | 名称 + 版本 |
| 集团码数据 | 名称 + 版本 |
| 开始时间 | ISO 时间 |
| 完成时间 | ISO 时间 |
| 客户物料数 | 整数 |
| 自动匹配数 | 整数 |
| 人工复核数 | 整数 |
| 未匹配数 | 整数 |
| 自动匹配率 | 百分比 |
| 前 N 名数量 | 整数 |

### 39.3 匹配结果

先保留客户原始列，再追加固定列：

```text
匹配状态
最终集团码
内部相似度
显示相似度
第一候选集团码
第一候选相似度
匹配原因
匹配方案版本
集团码数据版本
```

编码字段写为 Excel 文本类型。

### 39.4 TopN 候选

固定列：

```text
客户源行号
客户物料号
候选排名
候选集团码
内部相似度
显示相似度
字段得分明细
关键命中
关键冲突
```

### 39.5 超过 Excel 行数

Excel 单 Sheet 最大 1,048,576 行。

当 TopN 数据超过 1,000,000 行时，自动拆分为：

```text
TopN候选_1
TopN候选_2
...
```

每个 Sheet 最多 1,000,000 条数据加 1 行表头。

---

## 40. 匹配方案配置模型

### 40.1 配置版本

```yaml
schema_version: 1
```

服务端遇到不支持的更高版本必须拒绝加载，不得部分忽略后继续运行。

### 40.2 完整骨架

```yaml
schema_version: 1

profile:
  name: "示例方案"
  description: "业务说明"

source:
  dataset: "客户物料"
  id_column: "物料"

datasets: {}
joins: []

routing:
  by_source_field: "物料类型/一层分类"
  routes: []
  default:
    action: reject

target_catalogs: {}

normalization:
  null_tokens: ["", "<NULL>", "NULL"]

dictionaries: {}

rule_sets: {}

retrieval:
  type: auto
  retrieval_top_k: 200
  output_top_n: 5

decision:
  success_threshold: 88
  review_enabled: true
  review_threshold: 75
  display_coefficient: 1.0

output:
  format: xlsx
  keep_source_columns: true
```

### 40.3 权重

方案文件保存的业务权重仍然是 `0~100`，不保存前端归一化后的值。
