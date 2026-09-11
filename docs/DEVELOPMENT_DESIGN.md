# MATERIAL_MATCHER 开发设计书

> 文档状态：Draft
>
> 目标：定义一个可配置、可扩展、可离线部署的通用物料/实体匹配引擎。13 所为首个落地客户，但本设计不绑定任何单一客户、单一表格格式、单一字段命名或单一匹配算法。

---

## 1. 设计目标

MATERIAL_MATCHER 的核心目标不是实现某一种固定格式的“集团码匹配脚本”，而是构建一个通用匹配引擎：

- 支持不同来源、不同结构的输入数据；
- 支持 SAP 表格、集团码表格及其他 Excel/CSV/数据库/API 数据；
- 支持可配置的字段对应关系；
- 支持一对一、一对多、多对一、多对多字段组合匹配；
- 支持字段级匹配方式和字段级权重配置；
- 支持同义词、别名、规范化规则；
- 支持按物料组约束匹配，也支持忽略物料组进行全局匹配；
- 支持匹配成功阈值配置；
- 支持相似度结果的显示系数/显示映射调整，但不改变内部原始得分；
- 输出“正式匹配结果表”和“最相似 Top-N 候选表”；
- 只有相似度严格超过配置阈值的候选才被认定为匹配成功；
- 所有关键行为尽量配置化，不在核心代码中硬编码客户字段。

---

## 2. 首个落地场景

当前首个落地客户为 13 所，典型场景为：

- 客户侧约 10 万条物料；
- 集团侧约 100 万条物料；
- 集团侧数据当前来自 SAP 表 `ZTMM_MARA`，以 Excel 形式提供；
- 需要为客户侧物料寻找最可能对应的集团物料，并获得集团码；
- 后续其他客户可能存在完全不同的字段名、文件格式、物料组体系和匹配规则。

因此 13 所配置只能作为一个 profile，不得成为核心代码假设。

示例：

```text
profiles/
├── default.yaml
├── institute_13.yaml
└── other_customer.yaml
```

---

## 3. 总体架构

建议将系统拆分为以下逻辑层：

```text
输入数据
  ↓
数据适配器 Input Adapter
  ↓
字段映射 Field Mapping
  ↓
标准化 Normalization
  ↓
候选召回 Candidate Retrieval
  ↓
字段级匹配 Field Matching
  ↓
加权评分 Weighted Scoring
  ↓
分组约束 Group Strategy
  ↓
决策 Decision / Threshold
  ↓
结果输出 Result Export
```

核心原则：

1. 输入格式与匹配逻辑解耦；
2. 业务字段与物理列名解耦；
3. 候选召回与最终评分解耦；
4. 内部原始得分与用户显示得分解耦；
5. 客户差异通过 profile/config 表达；
6. 匹配失败也是正常结果，不能强制给出集团码；
7. Top-N 候选始终保留，便于人工复核。

---

## 4. 输入数据设计

### 4.1 输入角色

一次匹配任务至少包含两个逻辑数据集：

- `source`：待匹配数据，例如客户 SAP 物料；
- `target`：基准数据，例如集团物料/集团码主数据。

系统不能假定 source 一定是 SAP，target 一定是集团码表。

### 4.2 支持的输入形式

第一阶段建议支持：

- Excel：`.xlsx`；
- CSV；

后续可扩展：

- SAP 导出表；
- 数据库；
- REST API；
- 内部数据中台；
- Parquet 等大规模离线格式。

### 4.3 输入格式配置

每个输入数据集通过配置描述，SAP 表格格式和集团码表格格式分别配置，不把任何列名写死在程序中。

```yaml
source:
  type: excel
  path: ./data/customer.xlsx
  sheet: Sheet1
  header_row: 1
  id_column: MATNR

target:
  type: excel
  path: ./data/group.xlsx
  sheet: ZTMM_MARA
  header_row: 1
  id_column: MATNR
  result_code_column: ZJTM
```

配置项至少应支持：

- 文件类型；
- 文件路径；
- sheet 名；
- 表头行；
- 编码；
- 主键列；
- 结果码列；
- 忽略列；
- 空值规则；
- 重复记录处理策略。

---

## 5. 统一业务字段模型

系统不直接依赖 Excel 原始列名，而应将不同来源映射到统一逻辑字段。

示例逻辑字段：

```text
material_id
material_name
short_name
model
specification
brand
manufacturer
standard
quality_grade
surface_treatment
material_group
product_code
drawing_no
purpose
```

某客户可能使用：

```text
物料描述
规格型号
生产厂家
```

另一个客户可能使用：

```text
MAKTX
ZXHGG
HERSTELLER
```

它们都可以映射到相同逻辑字段。

示例：

```yaml
fields:
  source:
    material_name: MAKTX
    specification: ZXHGG
    manufacturer: ZSCCJ
    material_group: MATKL

  target:
    material_name: ZNAME
    specification: ZXHGG
    manufacturer: ZSCCJ
    material_group: MATKL
    group_code: ZJTM
```

---

## 6. 字段匹配关系设计

字段关系不能只支持简单的一列对一列。

系统至少支持以下四类匹配关系。

### 6.1 一对一匹配

一个 source 字段对应一个 target 字段。

例如：

```text
source.material_name ↔ target.material_name
```

配置示例：

```yaml
- name: material_name
  source_fields: [material_name]
  target_fields: [material_name]
  combine: concat
  weight: 0.35
```

### 6.2 一对多匹配

source 的一个字段，对 target 的多个字段拼接后匹配。

例如：

```text
source.物料描述
    ↕
target.名称 + target.简称 + target.规格
```

配置：

```yaml
- name: description_to_target_composite
  source_fields: [material_name]
  target_fields: [material_name, short_name, specification]
  combine: concat
  separator: " "
  weight: 0.40
```

### 6.3 多对一匹配

source 多个字段拼接后，与 target 一个字段匹配。

例如：

```text
source.名称 + source.型号 + source.规格
    ↕
target.完整描述
```

配置：

```yaml
- name: source_composite_to_description
  source_fields: [material_name, model, specification]
  target_fields: [description]
  combine: concat
  separator: " "
  weight: 0.45
```

### 6.4 多对多匹配

source 多个字段拼接后，与 target 多个字段拼接后匹配。

例如：

```text
source.名称 + source.型号 + source.厂家
    ↕
target.名称 + target.规格 + target.厂家
```

配置：

```yaml
- name: composite_material_identity
  source_fields: [material_name, model, manufacturer]
  target_fields: [material_name, specification, manufacturer]
  combine: concat
  separator: " "
  weight: 0.50
```

### 6.5 拼接规则

拼接应支持：

- 拼接顺序；
- 分隔符；
- 空字段跳过；
- 重复值去重；
- 拼接前标准化；
- 可选字段和必选字段。

示例：

```yaml
combine_options:
  separator: " "
  skip_empty: true
  deduplicate: true
  trim: true
```

---

## 7. 字段匹配方式

每个字段关系可以配置不同的匹配算法。

第一阶段建议支持：

- `exact`：精确匹配；
- `normalized_exact`：标准化后精确匹配；
- `contains`：包含关系；
- `fuzzy`：模糊字符串相似度；
- `token`：分词/token 集合相似度；
- `numeric`：数值/规格数值匹配；
- `semantic`：向量语义相似度；
- `hybrid`：多算法融合。

示例：

```yaml
match_rules:
  - name: material_name
    source_fields: [material_name]
    target_fields: [material_name]
    method: semantic
    weight: 0.35

  - name: specification
    source_fields: [specification]
    target_fields: [specification]
    method: fuzzy
    weight: 0.40

  - name: manufacturer
    source_fields: [manufacturer]
    target_fields: [manufacturer]
    method: normalized_exact
    weight: 0.25
```

后续算法应通过统一 Matcher 接口扩展，而不是修改主流程。

---

## 8. 字段权重设计

每个匹配关系支持配置权重。

例如：

```yaml
match_rules:
  - name: name
    weight: 0.30
  - name: specification
    weight: 0.40
  - name: manufacturer
    weight: 0.20
  - name: standard
    weight: 0.10
```

默认建议权重总和为 1，但系统内部应允许自动归一化。

### 8.1 空字段处理

需要明确区分：

- 双方都有值；
- source 为空；
- target 为空；
- 双方都为空。

建议支持两种策略：

#### fixed_weight

无论字段是否为空，都使用固定权重。缺失字段可能降低总分。

#### dynamic_weight

仅对双方具备有效值的字段重新归一化权重。

示例：

```yaml
scoring:
  missing_field_strategy: dynamic_weight
```

默认建议 `dynamic_weight`，避免因为某客户没有某个字段而系统性压低全部匹配得分。

---

## 9. 标准化与同义词配置

### 9.1 标准化

匹配前建议统一执行标准化流水线。

可配置能力包括：

- 去首尾空格；
- 连续空格合并；
- 大小写统一；
- 全角/半角统一；
- 中文标点/英文标点统一；
- 特殊符号清洗；
- 单位统一；
- 数字格式统一；
- 型号分隔符统一；
- 常见噪声词删除。

示例：

```yaml
normalization:
  trim: true
  lowercase: true
  normalize_width: true
  collapse_spaces: true
  normalize_punctuation: true
```

### 9.2 同义词

系统必须支持客户可配置同义词词典。

例如：

```yaml
synonyms:
  - canonical: 不锈钢
    aliases: ["SUS", "不锈", "stainless steel"]

  - canonical: 有限责任公司
    aliases: ["有限公司", "有限责任公司"]
```

也可使用独立文件：

```text
config/
└── dictionaries/
    ├── synonyms.yaml
    ├── units.yaml
    └── manufacturer_aliases.yaml
```

同义词配置应支持：

- 全局词典；
- 客户 profile 私有词典；
- 字段专用词典；
- 一词多别名；
- 启用/禁用；
- 优先级。

---

## 10. 候选召回

面对 10 万 × 100 万规模时，不应进行完整笛卡尔积逐条比对。

建议分为两阶段：

### 第一阶段：高召回候选生成

可采用：

- 物料组过滤；
- 精确字段预过滤；
- 倒排索引；
- 关键词召回；
- 向量 ANN 召回；
- 多路召回合并。

例如先从 100 万集团物料中找出 Top-100 或 Top-200 候选。

### 第二阶段：精排

对候选使用完整的字段匹配规则、同义词规则和权重计算最终综合分。

候选召回只负责“尽量别漏掉正确答案”，最终是否匹配成功由精排和阈值决定。

---

## 11. 物料组匹配策略

系统至少支持以下三种模式。

### 11.1 strict：按物料组分组匹配

source 物料仅与 target 中相同物料组进行匹配。

例如：

```text
客户物料组 A → 集团物料组 A
```

配置：

```yaml
group_matching:
  mode: strict
  source_field: material_group
  target_field: material_group
```

这种模式可显著降低候选规模并降低跨类别误匹配。

### 11.2 global：不区分集团物料组匹配

SAP 的一个物料组可能对应集团侧多个物料组，或者集团码体系并不按同样的物料组划分。

此时 source 某物料组应允许在 target 全量数据中匹配，不以集团物料组作为候选限制条件。

配置：

```yaml
group_matching:
  mode: global
```

### 11.3 mapped：物料组映射后匹配

支持 SAP 一个物料组对应集团侧一个或多个物料组。

```yaml
group_matching:
  mode: mapped
  mappings:
    SAP_A: [GROUP_01, GROUP_02]
    SAP_B: [GROUP_03]
```

这样可以表达：

- 一对一物料组映射；
- 一对多物料组映射；
- 部分物料组全局匹配；
- 未配置物料组使用默认策略。

建议支持：

```yaml
group_matching:
  mode: mapped
  default: global
```

---

## 12. 综合相似度计算

字段级得分统一转换到内部标准范围：

```text
0.0 ~ 1.0
```

综合原始得分：

```text
raw_score = Σ(field_score_i × normalized_weight_i)
```

其中：

```text
0.0 <= raw_score <= 1.0
```

内部判断必须始终使用 `raw_score`，不能使用显示分。

---

## 13. 匹配成功阈值

系统支持全局阈值配置：

```yaml
decision:
  success_threshold: 0.82
```

按“超过阈值才认为匹配成功”的业务规则，判定采用严格大于：

```text
best_raw_score > success_threshold
    => MATCHED

best_raw_score <= success_threshold
    => UNMATCHED
```

只有 `MATCHED` 才可以正式输出集团码作为匹配结果。

`UNMATCHED` 状态下：

- 正式集团码字段必须为空；
- 仍然输出最相似候选；
- 仍然输出最高相似度；
- 便于人工复核和后续调参。

### 13.1 可扩展阈值

后续可支持：

- 全局阈值；
- 按物料组阈值；
- 按字段完整程度阈值；
- 自动匹配阈值；
- 人工复核阈值。

例如：

```text
> 0.90      自动确认
> 0.80~0.90 人工复核
<= 0.80     未匹配
```

第一阶段可以先实现单一 success threshold。

---

## 14. 相似度显示系数

实际内部算法的原始得分与业务人员希望看到的显示数值可能不完全一致。

因此系统支持“显示相似度”的数值调整，但必须与内部判断完全解耦。

例如：

```yaml
score_display:
  scale: 100
  coefficient: 1.0
  offset: 0.0
  min: 0
  max: 100
```

显示公式示例：

```text
display_score = clamp(raw_score × scale × coefficient + offset)
```

例如：

```text
raw_score = 0.856
scale = 100
coefficient = 1.0

display_score = 85.6
```

如果业务侧需要对显示结果进行适当拉伸，可配置 coefficient，但：

> 匹配成功与否必须始终基于 raw_score 与原始阈值，禁止基于经过显示系数修饰后的数值做判断。

这样可以避免“为了让数字更好看而改变实际匹配逻辑”。

---

## 15. Top-N 候选设计

系统支持配置 Top-N：

```yaml
output:
  top_n: 5
```

对于 source 每条记录，至少保留：

```text
Top1
Top2
...
TopN
```

即使最高分没有达到成功阈值，也要保留 Top-N 候选。

这对于：

- 人工复核；
- 评估模型；
- 调整字段权重；
- 调整阈值；
- 分析错误匹配；

非常重要。

---

## 16. 输出设计

系统至少输出两个结果文件/工作表。

### 16.1 正式匹配结果表

用途：作为集团码正式匹配结果。默认保留所有 source 记录，未匹配记录的集团码为空，便于核对覆盖率；后续可增加 `include_unmatched` 控制是否只输出匹配成功记录。

建议字段：

| 字段 | 说明 |
|---|---|
| source_id | 客户物料主键 |
| source_material_code | 客户物料编码 |
| matched | 是否匹配成功 |
| target_id | 命中的集团记录主键 |
| group_code | 集团码，仅成功时填写 |
| raw_score | 内部原始相似度 |
| display_score | 显示相似度 |
| threshold | 本次匹配阈值 |
| match_status | MATCHED / UNMATCHED |
| matched_group | 命中的集团物料组 |
| rule_profile | 使用的配置版本 |

严格要求：

```text
raw_score <= threshold
=> group_code 必须为空
```

不能因为“Top1 总归有一个结果”就把它写成正式集团码。

### 16.2 最相似 Top-N 表

建议采用长表结构：

| source_id | rank | target_id | group_code | raw_score | display_score | field_scores |
|---|---:|---|---|---:|---:|---|
| A001 | 1 | G1001 | JT001 | 0.87 | 87.0 | ... |
| A001 | 2 | G3021 | JT455 | 0.82 | 82.0 | ... |
| A001 | 3 | G8821 | JT811 | 0.79 | 79.0 | ... |

Top-N 表不受 success threshold 限制，即便所有候选均未达到匹配成功阈值，也应保留候选供人工复核。

### 16.3 字段级可解释得分

推荐同时保留：

```text
name_score
specification_score
manufacturer_score
standard_score
...
```

或者以 JSON 形式写入：

```json
{
  "material_name": 0.91,
  "specification": 0.88,
  "manufacturer": 1.0
}
```

这样现场人员可以知道“为什么匹配成这个集团码”。

---

## 17. 配置文件总体示例

```yaml
profile:
  name: institute_13_v1
  version: 1

source:
  type: excel
  path: ./data/source.xlsx
  sheet: Sheet1
  id_column: MATNR

target:
  type: excel
  path: ./data/target.xlsx
  sheet: ZTMM_MARA
  id_column: MATNR
  result_code_column: ZJTM

fields:
  source:
    material_name: MAKTX
    specification: ZXHGG
    manufacturer: ZSCCJ
    material_group: MATKL

  target:
    material_name: ZNAME
    specification: ZXHGG
    manufacturer: ZSCCJ
    material_group: MATKL
    group_code: ZJTM

normalization:
  trim: true
  lowercase: true
  normalize_width: true
  collapse_spaces: true
  normalize_punctuation: true

synonyms:
  file: ./config/dictionaries/synonyms.yaml

match_rules:
  - name: name_match
    source_fields: [material_name]
    target_fields: [material_name]
    method: semantic
    weight: 0.35

  - name: spec_match
    source_fields: [specification]
    target_fields: [specification]
    method: fuzzy
    weight: 0.40

  - name: manufacturer_match
    source_fields: [manufacturer]
    target_fields: [manufacturer]
    method: normalized_exact
    weight: 0.25

scoring:
  missing_field_strategy: dynamic_weight

retrieval:
  top_k: 100

group_matching:
  mode: mapped
  default: global

decision:
  success_threshold: 0.82

score_display:
  scale: 100
  coefficient: 1.0
  offset: 0
  min: 0
  max: 100

output:
  top_n: 5
  include_unmatched: true
  matched_file: ./output/matched.xlsx
  topn_file: ./output/topn.xlsx
```

注：实际配置 schema 应在开发阶段通过 JSON Schema / Pydantic 等方式进行严格校验，启动任务前发现非法配置。

---

## 18. 核心数据结构建议

### MatchRule

```text
name
source_fields[]
target_fields[]
combine
separator
method
weight
normalizers[]
synonym_dictionary
options{}
```

### Candidate

```text
source_id
target_id
retrieval_score
```

### MatchScore

```text
source_id
target_id
field_scores{}
raw_score
display_score
```

### MatchDecision

```text
source_id
best_target_id
raw_score
threshold
status
group_code
```

---

## 19. 插件接口建议

为了保证通用性，建议抽象：

```text
InputAdapter
Normalizer
FieldMatcher
CandidateRetriever
ScoreAggregator
GroupStrategy
DecisionStrategy
ResultExporter
EmbeddingProvider
VectorIndex
```

第一阶段不需要实现大量插件，但接口应预留，避免后面客户差异导致主流程不断出现 `if customer == ...`。

---

## 20. 运行模式

建议支持两种调用方式。

### CLI

```bash
material-matcher run --config profiles/institute_13.yaml
```

适合：

- 现场批处理；
- 离线环境；
- 调试；
- 定时任务。

### 服务模式

后续提供 HTTP API：

```text
POST /jobs
GET  /jobs/{id}
GET  /jobs/{id}/result
```

服务模式不应影响核心匹配引擎，CLI 与 API 调用同一套内部 Engine。

---

## 21. 部署约束

首个目标服务端为银河麒麟 Linux V10。

设计约束：

- 不依赖 Docker 才能运行；
- Docker 仅作为可选部署能力；
- 支持离线安装；
- Python/runtime/第三方依赖尽量随安装包完整交付；
- 不要求现场访问公网安装依赖；
- 不要求现场编译复杂 native dependency；
- 通过 systemd 管理服务模式；
- 程序包与大模型/Embedding 模型包尽量解耦；
- 优先采用可嵌入式索引，减少额外 daemon 数量。

建议目录：

```text
/opt/material-matcher/
/etc/material-matcher/
/var/lib/material-matcher/
/var/log/material-matcher/
```

---

## 22. 性能原则

对于百万级 target 数据：

- 禁止对 10 万 × 100 万做完整两两比较；
- 应先召回候选，再执行高成本精排；
- target 侧标准化结果、向量、索引应持久化；
- 多个 source 批次复用 target 索引；
- 支持分批读取和分批写出，避免一次性占用过高内存；
- 可配置并发数；
- 对 CPU/GPU 能力保持解耦。

---

## 23. 可追溯性

每次批量匹配必须记录：

- profile 名称；
- profile 版本；
- 输入文件摘要/hash；
- target 数据版本；
- 同义词版本；
- 匹配算法版本；
- 模型版本；
- threshold；
- Top-N；
- 执行时间；
- 程序版本。

这样以后可以回答：

> 某个集团码为什么在某一天被匹配出来？当时使用的是哪套规则？

---

## 24. 测试要求

至少包含：

### 配置测试

- 合法配置可加载；
- 缺少必要字段立即报错；
- 无效字段引用立即报错；
- 权重非法时报错；
- threshold 超范围时报错。

### 字段关系测试

- 一对一；
- 一对多；
- 多对一；
- 多对多；
- 空字段拼接；
- 同义词替换。

### 分组测试

- strict 模式；
- global 模式；
- mapped 模式；
- 一对多组映射；
- 未配置组 fallback。

### 阈值测试

必须验证：

```text
score > threshold
=> MATCHED

score = threshold
=> UNMATCHED 且 group_code 为空

score < threshold
=> UNMATCHED 且 group_code 为空
```

### 输出测试

- 正式匹配表只为成功记录填写集团码；
- 未命中记录仍保留最高相似度；
- Top-N 排序正确；
- 每个 source 最多 N 条候选；
- 字段级得分可以追溯。

---

## 25. 第一阶段 MVP 建议范围

第一阶段优先完成：

1. Excel/CSV 输入；
2. 字段逻辑映射；
3. 一对一 / 一对多 / 多对一 / 多对多拼接；
4. 字符串模糊匹配；
5. 语义向量匹配；
6. 字段权重；
7. 同义词；
8. dynamic weight；
9. strict/global/mapped 物料组策略；
10. success threshold；
11. 显示相似度系数；
12. 正式结果表；
13. Top-N 候选表；
14. CLI 批处理；
15. 麒麟 V10 离线安装包。

暂时不把 Web UI、复杂工作流、人工审批系统作为核心 MVP 前置条件。

---

## 26. 非目标与边界

第一阶段不承诺：

- 完全自动解决所有物料主数据质量问题；
- 每条 source 必须匹配成功；
- 单一相似度算法适用于所有字段；
- 单一客户配置能够复用于所有客户；
- 仅使用向量相似度完成最终决策；
- 将 Top1 候选自动等同于正确集团码。

系统最重要的业务原则是：

> 宁可明确输出“未匹配”，也不要在低置信度情况下强行生成错误集团码。

---

## 27. 后续设计项

在开始核心实现前，还需要继续细化：

- 配置文件正式 schema；
- 各类 FieldMatcher 接口定义；
- embedding 模型选型；
- 向量索引选型；
- 中文规格型号标准化算法；
- 单位换算规则；
- 同义词维护机制；
- 物料组映射文件格式；
- Excel 输出字段最终模板；
- 性能基准数据集；
- 人工标注的标准答案集；
- 匹配准确率、Top-N recall、自动确认率等评测指标。

---

## 28. 总结

MATERIAL_MATCHER 的目标抽象为：

```text
任意 Source 数据
+ 任意 Target 数据
+ 输入适配配置
+ 字段映射配置
+ 字段组合规则
+ 字段匹配算法
+ 字段权重
+ 同义词/标准化配置
+ 物料组策略
+ 成功阈值
+ 显示规则

→ 正式匹配结果
→ Top-N 最相似候选
→ 字段级可解释信息
```

13 所集团码匹配只是该通用引擎的第一套实际 profile，而不是系统能力边界。
