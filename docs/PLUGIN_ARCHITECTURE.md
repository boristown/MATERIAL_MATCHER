# MATERIAL_MATCHER 插件化架构与零代码客户适配契约

> 状态：Normative Draft
>
> 本文把“后续换所不修改核心代码”从设计愿景提升为强制架构契约。普通客户差异必须通过配置、字典、映射、Catalog 和插件装配完成；客户名称、客户字段名、客户权重和客户阈值不得进入核心引擎源码。

---

## 1. 背景：9 月 10 日现场笔记暴露出的真实复杂度

13 所现场笔记和公开样例说明，实际问题并不是“一个 SAP Excel 对一个统一集团码 Excel”。至少存在以下变化：

- 不同物料大类使用不同字段组合，例如元器件、标准紧固件、金属材料、非金属材料、复合材料等；
- 不同大类的集团码表头和字段语义不同；
- 同一客户不同大类的匹配权重不同；
- 同一业务字段在不同大类中名称不同，例如“型号/牌号/详细型号规格/规格”等；
- 某些比对字段可能来自 `ZTMM_MARA`，也可能需要 `MARA` 或其他导出表补充；
- 现场笔记中存在 source 与集团字段逐项对应关系，这些关系应成为配置数据，而不是程序分支；
- 不同大类可能需要不同的候选过滤、规则精排、关键字段冲突策略和成功阈值。

因此核心模型必须是：

```text
多个数据源
   ↓
声明式 Join / Enrichment
   ↓
动态逻辑字段
   ↓
按条件路由到 Catalog + Rule Set
   ↓
通用召回 / 匹配 / 评分 / 决策
   ↓
可配置输出
```

而不是：

```text
if 客户 == 13所:
    if 类型 == A001: ...
    if 类型 == A006: ...
```

---

## 2. 可保证的边界

### 2.1 普通新客户：零代码

如果新客户仍属于以下能力范围，则必须做到**不修改核心程序、不重新编译核心程序**：

- Excel / CSV / 已支持数据库 / 已支持 SAP 导出格式；
- 表头、列顺序、Sheet、表头行不同；
- 字段数量和名称不同；
- 需要从多个输入表 Join/补字段；
- 一对一、一对多、多对一、多对多字段对应；
- 字段拼接、回退、取最佳值、值映射、正则清洗；
- 不同字段权重；
- 不同物料大类使用不同规则；
- 不同成功阈值和人工复核阈值；
- 不同同义词、厂家别名、单位、标准号规则；
- 不同 Target 集团码表结构；
- 不同 Top-N 和输出 Excel 结构。

新客户正常交付物应只有：

```text
profiles/<customer>.yaml
catalogs/<customer>/*.yaml
mappings/<customer>/*.yaml
dictionaries/<customer>/*
```

### 2.2 平台第一次遇到的新能力：新增通用插件

只有以下情况允许开发：

- 从未支持过的新文件/网络协议；
- 新数据库驱动；
- 全新的向量索引后端；
- 全新的字段匹配算法；
- DSL 无法表达的通用转换操作。

即使需要开发，也只能增加**通用插件**，不得在核心代码中加入客户专用 `if/else`。插件安装后，应可被任何客户 Profile 通过插件 ID 使用。

---

## 3. 插件注册中心

核心引擎只依赖抽象接口和 Registry：

```text
PluginRegistry
├── datasource
├── join
├── transform
├── normalizer
├── dictionary
├── router
├── retriever
├── matcher
├── scorer
├── decision
└── output
```

Profile 只引用插件 ID：

```yaml
source:
  plugin: excel

retrieval:
  plugin: auto_bbq

match_rules:
  - method: normalized_standard

output:
  plugin: xlsx
```

禁止：

```python
if customer_name == "13所":
    ...
```

允许：

```python
plugin = registry.create(kind, plugin_id, config)
```

---

## 4. DataSourcePlugin：任意输入格式

统一接口示意：

```python
class DataSourcePlugin:
    def inspect(self, config) -> DatasetSchema: ...
    def read_batches(self, config) -> Iterable[RecordBatch]: ...
```

首批内置插件：

- `excel`
- `csv`
- `parquet`
- `database`

后续可安装：

- RFC / OData / REST
- 数据中台
- 其他专有接口

Excel 插件必须支持：

- 多 Sheet；
- 任意表头行；
- 跳过说明行；
- 合并表头；
- 列别名；
- 所有编码字段按字符串读取，防止前导零丢失；
- 多文件 glob；
- 大文件流式/分块读取。

---

## 5. DatasetGraph：支持 MARA + ZTMM_MARA 等多源拼接

现场笔记出现 `ZTMM_MARA` 与 `MARA` 并列，说明 Source 不能只有一个输入表。

因此 Profile 必须支持多个命名数据集：

```yaml
datasets:
  ztmm_mara:
    plugin: excel
    path: ./input/ZTMM_MARA.xlsx

  mara:
    plugin: excel
    path: ./input/MARA.xlsx

  extra_vendor:
    plugin: excel
    path: ./input/vendor.xlsx
```

再声明 Join：

```yaml
joins:
  - id: enrich_mara
    left: ztmm_mara
    right: mara
    type: left
    keys:
      - left: MATNR
        right: MATNR
    select:
      - MEINS
      - MATKL
```

必要能力：

- `left / inner` Join；
- 单键/复合键；
- 字段冲突处理；
- `coalesce` 优先级；
- Join 后数据质量统计；
- 一对多 Join 防爆炸校验；
- 可缓存静态维表。

这样未来另一个所使用 `MARA + MAKT + 自定义 Z 表`，只增加 datasets/joins 配置，不修改引擎。

---

## 6. SchemaResolverPlugin：物理字段与逻辑字段解耦

核心引擎永远不直接依赖 `ZXHGG`、`ZWLMC`、`MATNR` 等客户字段。

配置：

```yaml
logical_fields:
  source_id:
    from: ztmm_mara
    aliases: [MATNR, 物料, 物料编码]

  unit:
    candidates:
      - dataset: ztmm_mara
        aliases: [MEINS, 计量单位]
      - dataset: mara
        aliases: [MEINS]
```

解析顺序可以为：

```text
exact → normalized → alias → regex
```

若存在歧义必须 fail-fast，不允许静默选错列。

---

## 7. TransformPlugin / DSL：把现场映射变成数据

9 月 10 日笔记里的“SAP 字段 S 对集团字段 J”的对应关系，本质上应表达成 DSL。

内置操作至少包括：

- `copy`
- `concat`
- `coalesce`
- `best_of`
- `constant`
- `nullify`
- `value_map`
- `replace`
- `regex_replace`
- `regex_extract`
- `dictionary_map`
- `normalize_unit`
- `normalize_standard`
- `normalize_dimension`
- `join_unique`

例如 SAP 中“型号 + 型号规格 + 牌号”可组成统一身份文本：

```yaml
derived_fields:
  identity:
    op: concat
    fields: [model, model_spec, grade]
    separator: " "
    skip_empty: true
```

复合材料可能优先用型号，缺失时回退牌号：

```yaml
  effective_grade:
    op: coalesce
    fields: [model, grade]
```

这类差异都不能写成客户专用 Python 函数。

---

## 8. CatalogPlugin：Target 侧支持多模板

集团码侧不能假设只有一张统一表。

```yaml
target_catalogs:
  electronics:
    source: ./group/electronics.xlsx
    schema: catalogs/electronics.yaml

  fasteners:
    source: ./group/fasteners.xlsx
    schema: catalogs/fasteners.yaml

  metal:
    source: ./group/metal.xlsx
    schema: catalogs/metal.yaml

  nonmetal:
    source: ./group/nonmetal.xlsx
    schema: catalogs/nonmetal.yaml

  composite:
    source: ./group/composite.xlsx
    schema: catalogs/composite.yaml
```

Catalog 负责：

- 自己的输入格式；
- 集团码主键；
- 自己的逻辑字段映射；
- 自己的向量文本构造；
- 可选独立 BBQ shard/index。

---

## 9. RouterPlugin：按物料类型动态选择规则

现场笔记显示不同大类使用完全不同字段逻辑，因此路由必须是配置。

```yaml
routing:
  by: source.material_type
  routes:
    - values: [A001, Z001]
      catalog: electronics
      rule_set: electronics_v1

    - values: [A002, Z002]
      catalog: fasteners
      rule_set: fasteners_v1

    - values: [A003, Z003]
      catalog: metal
      rule_set: metal_v1

    - values: [A005, Z005]
      catalog: nonmetal
      rule_set: nonmetal_v1

    - values: [A006, Z006]
      catalog: composite
      rule_set: composite_v1
```

这里的代码值、客户名称、类别数量均不得进入核心源码。

Router 后续还应支持：

- 按物料组；
- 按字段是否为空；
- 按数据来源；
- 按多个条件 AND/OR；
- default/fallback route。

---

## 10. RetrieverPlugin：候选召回可替换

统一接口：

```python
class RetrieverPlugin:
    def build(self, target_dataset, config): ...
    def search_batch(self, queries, top_k, filters=None): ...
```

内置：

- `exact_filter`
- `keyword`
- `bbq_flat`
- `bbq_hnsw`
- `auto_bbq`
- `multi_retrieval`

不同所可以通过配置决定：

```yaml
retrieval:
  plugin: auto_bbq
  top_k: 200
```

无需改代码。

---

## 11. MatcherPlugin：字段比对算法可插拔

统一输入输出：

```text
(source_value, target_value, matcher_config)
    → score[0,1] + evidence
```

内置建议：

- `exact`
- `normalized_exact`
- `contains`
- `ngram_dice`
- `token_similarity`
- `numeric_text`
- `normalized_standard`
- `semantic`
- `hybrid`

任何 Rule Set 只组合这些 matcher：

```yaml
- id: standard
  source_fields: [purchase_standard, technical_standard]
  target_fields: [adopted_standard]
  compose: best_of
  method: normalized_standard
  weight: 0.20
```

---

## 12. ScorePolicyPlugin：权重与冲突规则配置化

不同所、不同物料类型可以有不同权重。

```yaml
rule_sets:
  metal_v1:
    weights:
      grade: 0.35
      specification: 0.25
      standard: 0.20
      manufacturer: 0.10
      category: 0.10
```

还需支持：

- 动态权重归一；
- 缺失字段处理；
- critical 字段冲突封顶；
- hard reject；
- bonus/penalty；
- 条件权重。

核心代码只执行通用 Score Policy，不知道客户权重。

---

## 13. DecisionPolicyPlugin：客户敏感性配置化

```yaml
decision:
  plugin: bands
  bands:
    - status: MATCHED
      min_exclusive: 0.92
    - status: REVIEW
      min_exclusive: 0.82
      max_inclusive: 0.92
    - status: UNMATCHED
      max_inclusive: 0.82
```

也可按类别路由不同阈值。

正式集团码仍遵循：只有 Decision Policy 判定 `MATCHED` 时才写入正式结果；低于阈值的 Top1 只能作为候选，不能冒充正式集团码。

---

## 14. OutputPlugin：客户输出模板也不改代码

```yaml
output:
  plugin: xlsx
  sheets:
    result:
      name: 匹配结果
      columns: [...]
    candidates:
      name: TopN
      columns: [...]
```

支持：

- Excel/CSV；
- 列名别名；
- 列顺序；
- 多 Sheet；
- Top-N 长表/宽表；
- 字段级证据；
- 运行配置 hash；
- 数据版本/index 版本。

---

## 15. 插件包 Manifest 与兼容性

每个外部插件必须提供 manifest：

```yaml
plugin:
  id: sap_odata
  kind: datasource
  version: 1.2.0
  api_version: 1
  supported_platforms:
    - kylin-v10-x86_64
    - kylin-v10-aarch64
```

核心启动时校验：

- plugin ID 唯一；
- API version 兼容；
- 平台/架构兼容；
- 配置 Schema 合法；
- 所有引用字段存在；
- 所有 route 可解析；
- 所有 dictionary 可加载。

插件发现应支持：

```text
内置 registry
+ /opt/material-matcher/plugins/
```

在麒麟 V10 离线环境中，插件随离线安装包交付，不依赖公网下载。

---

## 16. Profile 编译：配置先变成执行计划

运行前必须把 Profile 编译成只读 Execution Plan：

```text
YAML/Profile
  ↓ validate
DatasetGraph
  ↓ resolve
Logical Schema
  ↓ compile
Routes + Rule Sets
  ↓ bind
Plugins
  ↓ freeze
ExecutionPlan + SHA-256
```

批量运行时不反复解释 YAML；这样既快，又能保证审计一致性。

Execution Plan 必须记录：

- profile version/hash；
- plugin versions；
- dictionary hashes；
- model/index versions；
- effective weights；
- effective thresholds。

---

## 17. 配置检查和 dry-run

必须提供：

```bash
material-matcher validate profile.yaml
material-matcher inspect profile.yaml
material-matcher dry-run profile.yaml --sample 100
```

`validate` 检查配置结构；`inspect` 输出最终字段映射/路由/有效权重；`dry-run` 用少量真实数据验证字段解析和 Join。

新客户上线应先通过这三个阶段，而不是改代码试错。

---

## 18. 9 月 10 日笔记在架构中的落点

现场笔记中的信息不应成为硬编码需求，而应落到如下配置对象：

| 现场信息 | 配置对象 |
|---|---|
| A001/A002/A003/A005/A006 等物料大类 | `routing.routes` |
| 每类不同集团码表结构 | `target_catalogs` |
| S 字段 ↔ J 字段对应 | `logical_fields + match_rules` |
| 型号/牌号/型号规格的不同关系 | `transform + matcher` |
| 规格、尺寸、标准号的专门比较 | `normalizer + matcher` |
| 国产/进口代码 | `value_map dictionary` |
| MARA + ZTMM_MARA | `datasets + joins` |
| 不同大类不同权重 | `rule_sets` |
| 不同客户匹配敏感性 | `decision policy` |
| 同义词 | `dictionary plugin` |

这张表是后续实现时的强制对应关系。

---

## 19. 零代码验收标准

“插件化”不能只停留在接口命名。正式验收至少包含：

1. 使用同一个 MATERIAL_MATCHER 程序包；
2. 准备至少 3 套字段结构明显不同的模拟客户；
3. 每个客户包含不同 Source 列名和 Target Catalog；
4. 至少一个客户使用单 Source；
5. 至少一个客户使用多 Source Join；
6. 至少一个客户使用多 Catalog 路由；
7. 三个客户权重和阈值不同；
8. 三个客户仅替换 profile/dictionary/mapping 即可运行；
9. 核心源码 Git diff 必须为 0；
10. 生成结果中记录完整配置和插件版本 hash。

此外 13 所本身应作为一套验收案例：至少覆盖两个字段体系差异明显的大类（当前已整理 Z001/Z006），后续再逐步补齐其他大类。

---

## 20. 最终边界

目标不是承诺“世界上任何未知格式永远不写代码”，这是不可实现的。

可承诺且必须做到的是：

> **所有常规客户差异均为配置数据；核心程序只实现通用能力。只有平台从未具备的新协议或新算法才新增一次通用插件。插件加入后，之后所有客户均可零代码复用。**

因此未来从 13 所推广到其他所时，正常情况应该是“新增一个 Profile”，而不是“复制一个项目分支”。
