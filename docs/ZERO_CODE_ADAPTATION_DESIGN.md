# MATERIAL_MATCHER 零代码客户适配设计

> 文档状态：Normative Draft
>
> 本文是《通用匹配引擎开发设计书》的约束性补充。目标不是“尽量配置化”，而是明确规定：**对于常见客户差异，新增客户只能新增或修改配置、字典和数据文件，不允许修改核心程序代码。**

---

## 1. 设计目标

MATERIAL_MATCHER 必须把“客户差异”视为运行时数据，而不是程序逻辑。

当客户发生以下变化时，核心程序必须无需改造：

- 客户从 13 所切换到其他单位；
- SAP 导出格式不同；
- Excel/CSV 表头名称不同；
- 表头所在行不同；
- SAP 技术字段名与中文字段名不同；
- source/target 字段数量不同；
- source/target 字段对应关系不同；
- 一对一、一对多、多对一、多对多组合关系不同；
- 客户需要不同的字段权重；
- 客户使用不同的相似度算法组合；
- 客户对匹配成功的敏感度不同；
- 不同物料组需要不同权重或不同阈值；
- 同义词、厂家别名、单位规范不同；
- 是否按物料组过滤不同；
- 输出列名、顺序、Top-N 数量不同；
- 相似度显示方式不同。

因此，新客户上线的正常交付物应为：

```text
一个 profile YAML
+ 若干字典文件
+ 可选字段映射表/物料组映射表
+ 输入文件
```

而不是一个客户专用分支或一组客户专用 if/else。

---

## 2. 零代码适配的边界

### 2.1 必须零代码支持的变化

以下变化属于“配置域”，禁止通过修改核心代码解决：

1. 文件列名变化；
2. 列顺序变化；
3. 表头行变化；
4. Sheet 名变化；
5. 字段缺失或新增；
6. 字段别名变化；
7. 字段拼接关系变化；
8. 字段标准化规则变化；
9. 字段匹配算法选择变化；
10. 字段权重变化；
11. 阈值变化；
12. 物料组策略变化；
13. 同义词/别名变化；
14. 输出格式变化；
15. 候选 Top-N 数量变化；
16. 显示相似度映射变化；
17. 不同物料组应用不同策略。

### 2.2 可以需要开发新插件的变化

只有出现“平台从未支持过的新能力”时才允许开发，例如：

- 新的文件协议或专有二进制格式；
- 新的数据库驱动或专有 SAP 接口；
- 全新的匹配算法类型；
- 全新的模型服务协议；
- 无法用现有转换 DSL 表达的复杂业务计算。

即使需要开发，也应新增通用 Adapter/Matcher/Transform 插件，而不是写客户名判断。

禁止：

```python
if customer == "13所":
    ...
elif customer == "xx所":
    ...
```

允许：

```python
adapter = adapter_registry.create(profile.source.adapter)
matcher = matcher_registry.create(rule.method)
```

---

## 3. 核心架构原则

系统按如下链路执行：

```text
Profile Loader
    ↓
Schema Validator
    ↓
Input Adapter
    ↓
Column Resolver
    ↓
Logical Field Builder
    ↓
Normalization / Dictionary Pipeline
    ↓
Candidate Retrieval
    ↓
Rule-set Router
    ↓
Field Matchers
    ↓
Weighted Scoring
    ↓
Decision Policy
    ↓
Output Mapper
```

核心代码只认识通用接口和配置 Schema，不认识任何客户字段名。

---

## 4. Profile 是唯一客户入口

每个客户或业务场景使用独立 profile。

```text
profiles/
├── base.yaml
├── institute_13.yaml
├── customer_a.yaml
├── customer_b.yaml
└── customer_b_high_precision.yaml
```

推荐支持继承：

```yaml
profile:
  name: customer_b
  extends: base.yaml
  version: 3
```

这样公共能力写在 `base.yaml`，客户只覆盖差异项。

配置优先级：

```text
引擎默认值
< base profile
< customer profile
< task override
```

所有合并后的最终配置必须在任务开始前固化并记录 SHA-256，用于审计和结果复现。

---

## 5. 输入格式完全配置化

### 5.1 Reader 配置

输入读取不能假定第一行就是表头，也不能假定只有一个 Sheet。

```yaml
source:
  adapter: excel
  path: ./input/customer.xlsx
  options:
    sheet: 物料主数据
    header_row: 3
    skip_rows: [1, 2]
    data_start_row: 4
    trim_headers: true
    merged_header_strategy: fill_forward
    encoding: utf-8
    empty_values: ["", "NULL", "N/A", "-"]
```

CSV 示例：

```yaml
source:
  adapter: csv
  options:
    encoding: gb18030
    delimiter: ","
    quotechar: '"'
    header_row: 1
```

### 5.2 列解析不能只靠精确列名

每个逻辑字段支持多个候选列名：

```yaml
logical_fields:
  material_id:
    source:
      aliases: [MATNR, 物料编码, 物料号, SAP物料编码]
      required: true
```

支持列名解析策略：

```yaml
column_resolution:
  mode: ordered
  strategies:
    - exact
    - case_insensitive
    - normalized
    - alias
    - regex
```

例如：

```yaml
logical_fields:
  material_name:
    source:
      aliases: [MAKTX, 物料描述, 物料名称]
      regex: [".*物料.*描述.*", ".*名称.*"]
```

如果出现多个候选列，应按配置优先级选择；存在歧义时在启动校验阶段报错，不允许静默猜错。

---

## 6. 逻辑字段必须是动态定义的

核心程序不得把如下字段写成固定 Python 常量：

```text
material_name
specification
manufacturer
...
```

这些只能作为示例或默认模板。

真正的运行时字段集合由 profile 定义：

```yaml
logical_fields:
  material_id:
    type: string
  desc:
    type: text
  model_spec:
    type: text
  vendor:
    type: text
  custom_property_x:
    type: text
```

引擎内部应使用：

```text
Dict[field_name, value]
```

或等价动态结构，而不是固定 dataclass 字段列表。

这样客户新增一个 `防护等级`、`材质牌号`、`精度等级` 字段时，只需要配置，不需要改代码。

---

## 7. 派生字段与转换 DSL

仅靠“物理列映射到逻辑列”还不够。不同客户经常需要从多个列构造一个匹配字段。

因此必须提供通用转换 DSL。

示例：

```yaml
derived_fields:
  source_identity:
    expression:
      op: concat
      fields: [desc, model_spec, vendor]
      separator: " "
      skip_empty: true
```

应至少支持：

- `copy`
- `concat`
- `coalesce`
- `constant`
- `trim`
- `lower/upper`
- `replace`
- `regex_replace`
- `regex_extract`
- `dictionary_map`
- `unit_normalize`
- `numeric_parse`
- `prefix/suffix`
- `substring`
- `join_unique`

例如：

```yaml
derived_fields:
  normalized_vendor:
    expression:
      op: dictionary_map
      field: vendor
      dictionary: manufacturer_aliases
```

原则：客户格式变化优先通过 DSL 表达，不新写客户专用函数。

---

## 8. 字段匹配关系完全数据驱动

引擎不能假定哪些字段需要比较。

配置定义本次任务的全部比较关系：

```yaml
match_rules:
  - id: description_rule
    source_fields: [desc]
    target_fields: [name, short_name]
    compose:
      source: concat
      target: concat
      separator: " "
    method: semantic
    weight: 0.35

  - id: model_rule
    source_fields: [model, specification]
    target_fields: [group_model]
    compose:
      source: concat
      target: concat
      separator: " "
    method: hybrid
    weight: 0.45
```

只要已有 Matcher 能覆盖客户需求，就不需要代码改造。

---

## 9. 权重必须支持多级覆盖

不同客户不仅全局权重不同，同一客户的不同物料组也可能不同。

因此权重至少支持：

```text
默认权重
→ 客户权重
→ 规则集权重
→ 物料组/条件权重
→ 单任务 override
```

示例：

```yaml
rule_sets:
  default:
    rules:
      desc: 0.30
      model: 0.45
      vendor: 0.25

  resistor:
    when:
      source.material_group: [R001, R002]
    rules:
      desc: 0.15
      model: 0.60
      vendor: 0.25
```

引擎只执行解析后的 `effective_weight`，不得在代码里写客户权重。

---

## 10. 匹配敏感性必须作为 Decision Policy

“客户对匹配度敏感性不同”不能只理解成一个 `success_threshold`。

必须把判定策略做成独立配置层。

### 10.1 单阈值模式

```yaml
decision:
  mode: single_threshold
  matched_if: gt
  success_threshold: 0.82
```

### 10.2 三段式模式

```yaml
decision:
  mode: bands
  bands:
    - status: MATCHED
      min_exclusive: 0.90
    - status: REVIEW
      min_exclusive: 0.80
      max_inclusive: 0.90
    - status: UNMATCHED
      max_inclusive: 0.80
```

### 10.3 按物料组不同阈值

```yaml
decision:
  mode: routed
  default:
    success_threshold: 0.84
  routes:
    - when:
        source.material_group: [IC]
      success_threshold: 0.92
    - when:
        source.material_group: [STANDARD_PART]
      success_threshold: 0.78
```

### 10.4 按字段完整度调整

```yaml
decision:
  completeness_policy:
    - when_missing_any: [model, vendor]
      success_threshold: 0.94
```

这样同一套程序可以适配“宁可漏匹配也不能错”的客户，也可以适配“优先提高覆盖率”的客户。

---

## 11. 相似度校准也必须配置化

客户对 80、90、95 分的理解可能不同，因此需要把内部匹配分与业务显示分完全分离。

支持：

```yaml
score_calibration:
  internal:
    method: power
    gamma: 4.25

score_display:
  method: linear
  scale: 100
  coefficient: 1.0
  offset: 0
  clamp: [0, 100]
```

也可支持分段映射：

```yaml
score_display:
  method: piecewise_linear
  points:
    - [0.60, 60]
    - [0.80, 85]
    - [0.90, 95]
    - [1.00, 100]
```

显示变换不得改变最终决策，除非客户明确配置 `decision.score_source` 使用另一个经过验证的内部校准分。

---

## 12. 物料组策略必须可路由

不能只提供一个全局 strict/global/mapped。

同一客户可能出现：

- A 类严格按组；
- B 类一个 SAP 组对应多个集团组；
- C 类完全不限制集团组。

因此应支持：

```yaml
group_matching:
  default:
    mode: global
  routes:
    - when:
        source.material_group: [A001]
      mode: strict
      source_field: material_group
      target_field: material_group

    - when:
        source.material_group: [B001]
      mode: mapped
      target_groups: [G01, G02, G03]
```

物料组只是 Candidate Filter 的一种配置，不应成为核心算法硬边界。

---

## 13. 同义词/别名/单位全部外置

配置示例：

```yaml
dictionaries:
  synonyms: ./dict/synonyms.yaml
  manufacturers: ./dict/manufacturers.yaml
  units: ./dict/units.yaml
  material_groups: ./dict/material_groups.yaml
```

字典必须支持版本号和哈希。

任何客户专有厂家名称、型号别名、单位缩写都不得写入 Python/C++/Rust 源码。

---

## 14. 候选召回策略也需要配置化

不同数据规模和物料组可能使用不同召回方式。

```yaml
retrieval:
  routes:
    - when:
        target_count_lte: 20000
      backend: bbq_flat
      top_k: 100

    - when:
        target_count_gt: 20000
      backend: bbq_hnsw
      top_k: 200
```

还应支持多路召回：

```yaml
retrieval:
  merge: reciprocal_rank_fusion
  channels:
    - backend: bbq
      top_k: 150
    - backend: exact_filter
      fields: [model]
      top_k: 50
```

因此更换客户不需要重新设计候选算法，只需要切换配置。

---

## 15. 输出也必须零代码配置

不同客户可能要求不同列名和顺序。

不能把 Excel 输出列写死。

```yaml
output:
  format: xlsx
  top_n: 5
  sheets:
    matched:
      name: 匹配结果
      columns:
        - source.material_id
        - source.desc
        - decision.status
        - target.group_code
        - scores.final_raw_score
        - scores.display_score

    candidates:
      name: TopN
      long_format: true
      columns:
        - source.material_id
        - rank
        - target.material_id
        - target.group_code
        - scores.final_raw_score
```

列标题支持重命名：

```yaml
output:
  aliases:
    source.material_id: 客户物料号
    target.group_code: 集团码
    scores.display_score: 相似度
```

---

## 16. 配置 Schema 校验是强制能力

要做到零代码适配，配置错误必须在任务启动前被发现。

至少校验：

- 必填配置是否存在；
- source/target 文件是否可读；
- Sheet 是否存在；
- 主键字段是否能解析；
- 逻辑字段是否引用了不存在的物理列；
- 派生字段依赖是否形成循环；
- matcher 是否已注册；
- 权重是否合法；
- threshold 是否在允许范围；
- group route 是否冲突；
- output 是否引用不存在的字段；
- 字典文件是否存在；
- embedding 维度是否与索引一致。

建议命令：

```bash
material-matcher validate --profile profiles/customer_a.yaml
```

成功后输出：

```text
PROFILE VALID
source schema: OK
target schema: OK
logical fields: 12
match rules: 6
weight sum: 1.0000
decision policy: routed
retrieval backend: auto_bbq
```

---

## 17. 配置预览 / Dry Run

上线新客户前必须支持无匹配执行的预览：

```bash
material-matcher inspect --profile profiles/customer_a.yaml
```

输出：

- 实际识别到的物理列；
- 物理列 → 逻辑字段映射；
- 10 条标准化样例；
- 派生字段结果；
- 最终生效权重；
- 最终生效阈值；
- 物料组路由；
- 输出字段映射。

这样格式适配问题可通过配置调试，不需要修改代码后再试。

---

## 18. 配置热切换

引擎服务启动后应允许不同任务选择不同 profile：

```text
POST /jobs
profile = customer_a_v3
```

下一任务可以直接：

```text
profile = customer_b_v1
```

不要求重启服务。

索引应通过以下键隔离：

```text
(target_dataset_hash,
 embedding_model,
 embedding_dimension,
 vectorization_profile,
 normalization_profile)
```

若仅修改最终字段权重或成功阈值，不应要求重建向量索引。

---

## 19. 配置变化与重建范围

不同配置变化对系统的影响不同，应自动判断：

| 配置变化 | 是否重读数据 | 是否重算向量 | 是否重建索引 | 是否重新精排 |
|---|---:|---:|---:|---:|
| 输出列名 | 否 | 否 | 否 | 否 |
| success threshold | 否 | 否 | 否 | 可复用已有分数 |
| 字段权重 | 否 | 否* | 否* | 是 |
| 同义词（仅规则精排） | 否 | 否 | 否 | 是 |
| 向量输入字段变化 | 否 | 是 | 是 | 是 |
| embedding 模型变化 | 否 | 是 | 是 | 是 |
| 物料组候选过滤 | 否 | 否 | 通常否 | 是 |
| source 列映射 | 是 | 视情况 | 视情况 | 是 |

`*` 前提是该字段的向量/规则特征已在可复用特征缓存中。

这使调权重、调阈值可以快速重新计算，而不是每次从头向量化百万条集团数据。

---

## 20. 一个完整的跨客户示例

### 客户 A

```yaml
profile:
  name: customer_a
  extends: base.yaml

source:
  adapter: excel
  options:
    sheet: Sheet1
    header_row: 1

logical_fields:
  material_id:
    source: {aliases: [MATNR]}
  description:
    source: {aliases: [MAKTX]}
    target: {aliases: [物料名称]}
  model:
    source: {aliases: [型号规格]}
    target: {aliases: [集团规格]}

match_rules:
  - id: desc
    source_fields: [description]
    target_fields: [description]
    method: semantic
    weight: 0.4
  - id: model
    source_fields: [model]
    target_fields: [model]
    method: normalized_exact
    weight: 0.6

decision:
  success_threshold: 0.88
```

### 客户 B

不修改任何程序，只换 profile：

```yaml
profile:
  name: customer_b
  extends: base.yaml

source:
  adapter: excel
  options:
    sheet: SAP导出
    header_row: 4

logical_fields:
  material_id:
    source: {aliases: [物资编码, SAP编码]}
  description:
    source: {aliases: [物资描述]}
    target: {aliases: [集团名称]}
  vendor:
    source: {aliases: [品牌, 厂家]}
    target: {aliases: [制造商名称]}

match_rules:
  - id: desc
    source_fields: [description]
    target_fields: [description]
    method: hybrid
    weight: 0.65
  - id: vendor
    source_fields: [vendor]
    target_fields: [vendor]
    method: synonym_exact
    weight: 0.35

decision:
  mode: bands
  bands:
    - {status: MATCHED, min_exclusive: 0.93}
    - {status: REVIEW, min_exclusive: 0.82, max_inclusive: 0.93}
    - {status: UNMATCHED, max_inclusive: 0.82}
```

两个客户使用完全相同的可执行程序。

---

## 21. 新客户接入流程

标准流程必须变成配置工作，而不是开发工作：

```text
1. 获取客户 source/target 样例
2. 复制 base profile
3. 配置 Reader
4. 配置列别名
5. 配置逻辑字段
6. 配置派生字段
7. 配置匹配规则
8. 配置权重
9. 配置阈值/敏感性
10. 配置同义词和物料组映射
11. validate
12. inspect / dry-run
13. 用标注样本 benchmark
14. 正式运行
```

正常情况下不应出现第 15 步“修改程序”。

---

## 22. 验收标准：证明“换客户无需改程序”

开发完成后必须准备至少 3 套差异明显的 fixture：

### Fixture A：SAP 技术字段

```text
MATNR / MAKTX / MATKL / HERST...
```

### Fixture B：中文业务字段

```text
物料编码 / 物料名称 / 规格型号 / 厂家...
```

### Fixture C：异构组合字段

```text
名称 + 牌号 + 尺寸 + 品牌
↔
集团描述 + 规格 + 制造商
```

三个 fixture 必须使用：

- 同一份程序二进制；
- 同一套核心代码；
- 不同 profile；
- 不同权重；
- 不同阈值；
- 不同物料组策略；
- 不同输出列。

CI 测试要求：

```text
git diff -- core/ == empty
```

仅替换 profile 即可通过全部匹配流程。

---

## 23. Definition of Done

只有同时满足以下条件，才能宣称系统具备“通用客户零代码适配能力”：

1. 新客户列名变化不改代码；
2. SAP 格式变化不改代码；
3. 字段数量变化不改代码；
4. 字段映射关系变化不改代码；
5. 一对多/多对一/多对多关系变化不改代码；
6. 权重变化不改代码；
7. 阈值和敏感性变化不改代码；
8. 同义词变化不改代码；
9. 物料组策略变化不改代码；
10. 输出字段变化不改代码；
11. 不同 profile 可在同一服务实例中连续运行；
12. 所有配置经过 Schema 校验；
13. 每次运行记录最终生效配置及哈希；
14. 不允许核心代码出现客户名、客户专属字段名或客户专属权重常量。

最终原则：

> **代码实现能力，配置描述差异。**
>
> **客户变化应当导致 profile 变化，而不是程序版本变化。**
