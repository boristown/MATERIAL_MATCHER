# MATERIAL_MATCHER 向量数据库与 BBQ 高速批量匹配设计

> 文档状态：Draft
>
> 本文是 [`DEVELOPMENT_DESIGN.md`](./DEVELOPMENT_DESIGN.md) 的专项设计，定义 MATERIAL_MATCHER 的向量数据库、Better Binary Quantization（BBQ）极限压缩索引，以及百万级 Target × 十万级 Source 的高速批量候选召回方案。
>
> 核心原则：**向量检索负责高召回候选生成，最终集团码判断仍由通用字段匹配、规则约束、字段权重与成功阈值共同决定。**

---

## 1. 设计背景

本项目不是从零开始设计相似度算法。2026 年已有两套可复用经验：

1. `xiaogang-ai-workspace/xg_app/similarity.py` 已实现较成熟的物料相似度算法，包括字段拆解、字符 n-gram Sørensen-Dice、BGE 语义向量、字段权重、动态归一、关键字段冲突封顶、物料类型硬边界、结果解释与批量分块计算。
2. 既有 ZAIMAST 链路已经存在 BBQ 服务桥接，说明 BBQ 量化向量检索已经在既有系统中使用过。新项目应优先复用和验证既有经验，而不是另造一套互不兼容的向量检索协议。

MATERIAL_MATCHER 的变化主要在规模和通用化：

- 历史算法适合单表查重和较小规模全量两两计算；
- 新场景是约 10 万 Source 对约 100 万 Target，不能做完整笛卡尔积；
- 新系统要支持任意字段映射、物料组策略、不同客户 profile；
- 新系统目标环境为银河麒麟 Linux V10，不能依赖 Docker 才能运行。

因此新架构采用：

```text
高速候选召回：BBQ 1-bit 向量索引
        ↓
高精度向量重排（可选 int8 / float16）
        ↓
历史成熟的字段规则/语义混合算法抽象化精排
        ↓
字段权重 + 冲突规则 + 阈值决策
        ↓
正式匹配结果 + Top-N
```

---

## 2. 历史物料相似度算法作为兼容基线

历史实现应保留为一个可选 profile，例如：

```text
profiles/baselines/xiaogang_similarity_v1.yaml
```

其历史口径包括：

- 字段规则分：字符 n-gram Sørensen-Dice；
- 普通字段使用 2/3-gram；
- 短字段使用 1/2-gram；
- 语义分：BGE embedding cosine；
- 历史 embedding 模型：`bge-small-zh-v1.5`，512 维；
- 历史语义占比：30%；
- 历史规则占比：70%；
- 历史校准：`score ^ 4.25`；
- 字段仅在至少一方非空时参与权重归一；
- 支持关键字段冲突分数上限；
- 支持核心字段缺失分数上限；
- 支持业务品类冲突分数上限；
- 支持物料类型硬边界；
- 支持停用物料排除。

历史固定权重可作为回归测试基线，但不得成为通用引擎的硬编码默认值。

### 2.1 新系统如何复用历史算法

历史实现中的以下能力可直接抽象复用：

```text
Normalizer
FieldExtractor
NgramDiceMatcher
SemanticMatcher
WeightedScoreAggregator
CriticalFieldCapRule
MissingCoreFieldCapRule
CategoryConflictRule
ResultExplainer
```

需要替换的主要部分是：

```text
历史：在较小集合中分块计算全部 pair
新系统：先通过 BBQ 从百万级 Target 召回少量候选，再对候选执行历史精排逻辑
```

### 2.2 阈值兼容

历史算法曾使用 `>= 0.90` 的重复判定语义。

MATERIAL_MATCHER 当前通用设计按本项目业务要求定义为：

```text
final_raw_score > success_threshold
    => MATCHED

final_raw_score <= success_threshold
    => UNMATCHED
```

若需要精确复现历史结果，可在兼容 profile 中配置：

```yaml
decision:
  comparator: gte
  success_threshold: 0.90
```

新客户 profile 默认使用：

```yaml
decision:
  comparator: gt
```

---

## 3. BBQ 核心目标

BBQ（Better Binary Quantization）的核心思想是将 Target embedding 的每一个维度压缩到单个 bit。

对于 float32 embedding：

```text
原始：32 bit / dimension
BBQ ： 1 bit / dimension
```

仅考虑主向量编码，理论压缩比例约为：

```text
32 : 1
```

### 3.1 512 维历史 BGE 模型示例

单条向量：

```text
float32 = 512 × 4 bytes = 2048 bytes
1-bit   = 512 / 8 bytes = 64 bytes
```

100 万条 Target 的向量主体：

```text
float32 ≈ 2.048 GB
1-bit   ≈ 64 MB
```

这不包含：

- ID；
- HNSW 图；
- 校正参数；
- metadata；
- 可选高精度 rerank sidecar。

但 1-bit 主索引可以把最频繁访问的向量主体缩到非常小，使其更容易常驻 CPU cache / RAM。

---

## 4. 默认采用非对称量化

不建议把正式方案简化成“Query 和 Target 都只取符号位”。

推荐采用 BBQ-like 非对称量化：

```text
Target：1 bit / dimension
Query ：4 bit / dimension
```

也就是：

- 百万级、长期存储的 Target 做极限压缩；
- 当前批次 Query 保留更高精度；
- 使用位运算近似计算 dot product / cosine 排序。

这与当前 Elasticsearch BBQ 的默认非对称量化方向一致，但 MATERIAL_MATCHER 不要求部署 Elasticsearch。

### 4.1 为什么 Query 保留 4 bit

Query 数量远少于 Target 常驻索引，因此 Query 多使用少量 bit 对总体内存影响很小，却可以明显保留更多幅度信息。

Query 4-bit 值可拆成 4 个 bit-plane：

```text
Q0 Q1 Q2 Q3
```

Target 只有一个 bit-plane：

```text
T
```

近似点积热路径可以转化为：

```text
c0 = popcount(T & Q0)
c1 = popcount(T & Q1)
c2 = popcount(T & Q2)
c3 = popcount(T & Q3)

partial = c0
        + (c1 << 1)
        + (c2 << 2)
        + (c3 << 3)
```

再结合量化时保存的少量校正值恢复近似相似度。

核心优势是：

- 避免大量 float32 乘加；
- 一次 CPU 指令处理几十/几百个维度；
- 非常适合 SIMD、AND、POPCNT；
- Target 数据体积极小，内存带宽压力显著下降。

---

## 5. 二值 Hamming 仅作为基线实现

系统同时保留简单二值模式：

```text
Target 1-bit
Query  1-bit
```

距离：

```text
hamming = popcount(Target XOR Query)
```

归一化：

```text
similarity = 1 - hamming / dimensions
```

用途：

- 单元测试；
- 性能基线；
- native SIMD 校验；
- 极端资源受限模式。

但它不是推荐的正式默认算法，因为 Query 也被压到 1 bit 后精度损失更大。

---

## 6. 校正信息

1-bit 主向量之外，允许为每条 Target 保存少量量化校正参数，例如：

```text
mean
scale
norm
offset
correction_term
```

具体数学表达式在实现阶段通过既有 BBQ 服务与 float32 baseline 对齐实验确定。

设计约束：

> 可以用极少量额外字节换取明显更好的 Recall@K，但主向量仍必须保持 1 bit / dimension。

---

## 7. 向量存储模式

### 7.1 `binary_only`

```text
1-bit Target 主索引
+ correction metadata
```

优点：

- 内存最小；
- 磁盘最小；
- 召回最快。

适用于：

- 资源非常受限；
- 后续字段规则精排很强；
- 允许增加 BBQ oversampling。

### 7.2 `binary_int8_rerank`

推荐默认：

```text
1-bit 主索引       -> 高频召回
int8 sidecar       -> 只对候选做高精度重排
```

512 维、100 万 Target 的 int8 sidecar 向量主体约 512 MB，可 mmap，不要求全部常驻内存。

该模式在存储、速度、精度之间更平衡。

### 7.3 `binary_float16_rerank`

精度优先：

```text
1-bit 主索引
float16 sidecar
```

适用于误匹配成本极高、磁盘较充足的环境。

### 7.4 float32 的定位

float32 原始 embedding 可以用于：

- 离线索引构建；
- Benchmark 真值；
- 模型升级/重新量化；
- 可选归档。

不要求将百万条 float32 向量永久常驻服务内存。

---

## 8. VectorIndex 通用接口

```text
VectorIndex
├── build()
├── load()
├── save()
├── search()
├── search_batch()
├── add()
├── delete()
├── compact()
└── stats()
```

建议实现：

```text
VectorIndex
├── EmbeddedBBQFlatIndex
├── EmbeddedBBQHnswIndex
├── EmbeddedBBQDiskIndex
├── AutoBBQIndex
├── ExistingBBQHttpAdapter
├── ElasticsearchBBQAdapter       # 可选
└── ExternalVectorDbAdapter       # 可选
```

### 8.1 默认后端

银河麒麟 V10 离线环境默认：

```text
Embedded BBQ
```

而不是强制要求：

```text
Elasticsearch / Qdrant / Milvus / Docker
```

### 8.2 历史 BBQ 兼容适配器

已有 ZAIMAST BBQ 链路可通过：

```text
ExistingBBQHttpAdapter
```

接入，主要用途：

- 对照历史结果；
- 回归测试；
- 迁移期间双跑；
- 验证新 Embedded BBQ 的 Recall@K 和排序一致性。

新核心 Engine 不绑定历史 HTTP 地址或鉴权方式。

---

## 9. 三种 BBQ 索引形态

### 9.1 BBQ Flat

对一个候选集合做连续 1-bit 扫描。

适合：

- strict 物料组过滤后候选量较小；
- mapped 后只涉及少数小组；
- 数万级及以下候选；
- 要求简单、稳定、批量吞吐高。

特点：

- 不需要 HNSW 图；
- 连续读取 packed bits；
- SIMD 利用率高；
- 对小集合通常比图遍历更划算。

### 9.2 BBQ HNSW

适合：

- global 全库搜索；
- 百万级 Target；
- 超大物料组。

流程：

```text
4-bit Query
↓
1-bit HNSW 图遍历
↓
oversampled Top-K
↓
高精度 rerank
```

### 9.3 BBQ Disk / Block Index

为内存更紧张的麒麟现场保留类似 disk-BBQ 的本地实现：

```text
1-bit packed vector blocks
+ cluster / coarse routing
+ mmap
+ sequential block scoring
```

目标不是复制 Elasticsearch 代码，而是借鉴公开算法思想，构建项目自有、可离线打包的 block-based 索引。

---

## 10. AutoBBQIndex

不存在对所有数据规模都最快的唯一方案。

因此默认建议：

```text
AutoBBQIndex
```

根据过滤后的有效 Target 数量自动选择：

```text
小集合 -> BBQ Flat
大集合 -> BBQ HNSW / BBQ Disk
```

示例：

```yaml
vector_index:
  provider: embedded_bbq
  algorithm: auto
  flat_scan_threshold: auto
```

`flat_scan_threshold` 不应写死为某个经验数字，而应通过目标服务器 Benchmark 得到。

---

## 11. 与物料组策略结合

### 11.1 strict

```text
Source Group A
↓
只搜索 Target Group A
```

如果组内候选很少：

```text
BBQ Flat
```

如果某个组特别大：

```text
BBQ HNSW
```

### 11.2 global

```text
Source
↓
全量 100 万 Target
↓
BBQ HNSW / BBQ Disk
```

### 11.3 mapped

例如：

```text
SAP_A -> GROUP_01 + GROUP_02 + GROUP_07
```

先解析允许的 Target shard，再对组合后的候选空间执行 AutoBBQIndex。

### 11.4 不为每个小组机械建立 HNSW

如果 Target 有大量小物料组：

```text
极小组 -> 共享 packed segment + offset table
小组   -> Flat shard
大组   -> HNSW shard
```

避免成千上万个小 HNSW 带来的索引碎片、内存浪费和部署复杂度。

---

## 12. 真正的批量匹配流程

本系统必须以 Batch 为第一公民，而不是把 10 万条 Source 当成 10 万次单查询。

```text
Source rows
↓
Batch normalization
↓
Batch field composition
↓
Batch embedding
↓
Batch 4-bit query quantization
↓
按 Group / Shard 重排 Query
↓
Batch BBQ retrieval
↓
Oversampled Top-K
↓
High-precision vector rerank
↓
Field-rule rerank
↓
Weighted final score
↓
Threshold decision
↓
Streaming output
```

核心 API：

```python
search_batch(queries, top_k, filters=None)
```

单查询只是：

```python
search_one(query):
    return search_batch([query], ...)[0]
```

---

## 13. 批量 Embedding 复用历史优化

历史实现已经验证：

- 相同标准化文本先去重；
- 唯一值才调用 embedding；
- embedding 按条数批量；
- 同时受总字符数限制；
- embedding 完成后做 L2 normalize；
- 相同文本复用缓存向量。

新系统继续保留这些策略，并扩展成持久化 embedding cache：

```text
cache_key = hash(model_version + normalized_text)
```

Target embedding 在索引构建后长期复用。

---

## 14. Target 二进制内存布局

假设 512 维：

```text
512 bits = 64 bytes = 8 × uint64
```

建议主编码：

```c
uint64_t words[ceil(D / 64)]
```

Target 连续排列：

```text
[target0][target1][target2]...[targetN]
```

要求：

- 固定长度；
- 64-byte 对齐优先；
- sequential access；
- mmap friendly；
- prefetch friendly；
- SIMD friendly。

维度不能被 64 整除时，最后 word 必须 mask 无效 bit。

---

## 15. SIMD 热路径

### 15.1 1-bit Hamming 基线

```c
x = target_word ^ query_word;
distance += popcount(x);
```

### 15.2 1-bit Target × 4-bit Query

正式 BBQ-like 路径：

```text
AND
↓
POPCOUNT
↓
bit shift
↓
sum
↓
correction
```

### 15.3 x86_64

运行时按 CPU 自动选择：

```text
AVX / AVX2 + POPCNT
AVX-512/VPOPCNTDQ（在实测有收益时）
scalar fallback
```

不应假定 AVX-512 一定最快，最终以目标 CPU Benchmark 为准。

### 15.4 aarch64

预留：

```text
NEON AND
CNT
UADDLP / reduction
```

### 15.5 Runtime Dispatch

```text
CPUFeatureDetector
↓
选择最佳 native kernel
```

配置：

```yaml
native:
  simd: auto
```

测试环境可强制：

```yaml
native:
  simd: scalar
```

用于结果一致性校验。

---

## 16. Native 实现边界

Python 负责：

- Excel/CSV；
- 配置；
- 字段映射；
- 同义词；
- profile；
- 任务调度；
- 输出；
- 审计。

C++ 或 Rust native 模块负责热路径：

- bit packing；
- 4-bit query quantization；
- correction 参数；
- BBQ Flat block scan；
- BBQ HNSW distance kernel；
- SIMD/POPCNT；
- partial Top-K；
- int8/float16 rerank hot loop。

原则：

> 禁止在 Python 中逐向量、逐维执行百万级 BBQ 比较。

---

## 17. Block Scan

BBQ Flat 批量检索不能写成：

```text
for source:
    for target:
        python_distance()
```

应采用二维 block：

```text
Query Block  = Bq
Target Block = Bt
```

Native 核心一次处理：

```text
[Bq, packed_words] × [Bt, packed_words]
```

并直接维护每个 Query 的 Top-K。

禁止生成完整：

```text
Bq × Bt
```

结果矩阵后再排序，因为百万级数据会造成不必要的内存流量。

---

## 18. Top-K 选择优化

扫描/图搜索过程中只保留 K 个最佳候选：

可实现：

- fixed-size min heap；
- partial selection；
- block-local Top-K + merge；
- threshold pruning。

目标：

```text
K << Target Count
```

不能对百万个分数执行完整排序。

---

## 19. Query 按 Shard 重排

10 万 Source 批量任务中，不应严格按照 Excel 原顺序搜索。

内部可以根据：

```text
material_group
mapped_target_groups
index_shard
```

对 Query 暂时重排：

```text
同一 shard 的 Query 连续处理
```

优势：

- Target packed vectors cache 热；
- HNSW shard 少重复切换；
- mmap page 命中率更高；
- 提高 SIMD batch 吞吐。

最终输出再按 source 原始行号恢复顺序。

---

## 20. Oversampling

1-bit 主索引存在量化误差，因此：

```text
最终 Top-N != 第一阶段只召回 N 个
```

例如最终需要：

```text
Top-N = 5
```

BBQ 第一阶段可能先召回：

```text
Top-K = 50 / 100 / 200
```

再重排。

配置：

```yaml
vector_retrieval:
  top_k: 100
  oversampling_factor: 3.0
```

具体 factor 必须用标注数据验证，不能单纯追求速度而降低正确集团码的 Recall@K。

---

## 21. 三层排序

### Layer 1：BBQ 候选召回

```text
1,000,000 Target
↓
Top-K 100
```

分数：

```text
retrieval_score
```

### Layer 2：高精度向量重排

```text
Top-K 100
↓
Vector Top 20~50
```

可使用：

```text
int8 cosine/dot
float16 cosine/dot
```

分数：

```text
vector_rerank_score
```

### Layer 3：通用字段精排

对保留候选执行：

- 一对一 / 一对多 / 多对一 / 多对多字段组合；
- n-gram Dice；
- fuzzy/token/numeric/exact；
- 同义词；
- 字段权重；
- 历史 critical field cap；
- material group 规则；
- 其他客户 profile 规则。

得到：

```text
final_raw_score
```

最终匹配阈值只判断：

```text
final_raw_score
```

---

## 22. 分数必须分层保存

禁止把 BBQ 分数直接覆盖成最终相似度。

Candidate 至少保存：

```text
retrieval_score
vector_rerank_score
rule_score
semantic_score
final_raw_score
display_score
```

示例：

```json
{
  "source_id": "S001",
  "target_id": "G10001",
  "rank": 1,
  "retrieval_score": 0.81,
  "vector_rerank_score": 0.89,
  "rule_score": 0.94,
  "semantic_score": 0.89,
  "final_raw_score": 0.92,
  "display_score": 92.0
}
```

这对定位“BBQ 漏召回”和“规则误判”非常重要。

---

## 23. BBQ 不替代字段权重

向量索引解决的是：

```text
如何快速从 100 万 Target 中找到值得精排的几十/几百条候选
```

它不能替代：

- 型号规格高权重；
- 厂家一致性；
- 标准图号；
- 质量等级；
- 同义词；
- 物料组；
- 客户业务规则。

因此：

```text
vector_score != final_match_score
```

这是系统架构的硬约束。

---

## 24. mmap 与索引文件布局

建议索引目录：

```text
index/
└── target_<version>/
    ├── manifest.json
    ├── ids.bin
    ├── binary_vectors.bin
    ├── corrections.bin
    ├── hnsw.graph
    ├── group_offsets.bin
    ├── rerank_int8.bin
    ├── metadata.parquet
    └── checksum.sha256
```

其中：

```text
binary_vectors.bin
```

必须是真正的 packed 1-bit Target 主向量文件。

大文件优先：

```text
mmap(read-only)
```

由 Linux page cache 管理。

---

## 25. manifest

```json
{
  "format_version": 1,
  "target_version": "2026-09-11",
  "embedding_model": "bge-small-zh-v1.5",
  "dimensions": 512,
  "normalize": true,
  "quantization": "bbq_asymmetric",
  "target_bits_per_dimension": 1,
  "query_bits_per_dimension": 4,
  "index_algorithm": "auto",
  "record_count": 1000000,
  "rerank_storage": "int8"
}
```

注意：上述模型仅是历史兼容 profile 示例。通用引擎不得把 512 维或 BGE 模型写死。

加载索引时必须校验：

- model version；
- dimensions；
- normalization；
- quantization version；
- target data version；
- checksum。

不匹配则拒绝加载，避免“模型换了但沿用旧索引”。

---

## 26. 索引版本与原子切换

Target 集团数据更新时：

```text
旧索引 target_v1 正常服务
↓
离线构建 target_v2
↓
完整校验
↓
原子切换 current -> target_v2
↓
新任务使用 v2
```

不要在百万级生产索引上逐条修改到半成品状态。

建议：

```text
/var/lib/material-matcher/indexes/current
```

指向当前完整版本。

---

## 27. 批量调度器

新增：

```text
BatchMatchScheduler
```

职责：

1. Source 分块；
2. 批量 embedding；
3. 批量 query quantization；
4. 按物料组/shard 重排；
5. 调用 `search_batch()`；
6. 合并多路候选；
7. 高精度 rerank；
8. 字段精排；
9. 阈值决策；
10. 流式写结果；
11. 最终恢复原始 Source 顺序。

配置示例：

```yaml
batch:
  source_batch_size: 1024
  workers: auto
  reorder_by_shard: true
```

具体 batch size 由目标服务器 Benchmark 决定。

---

## 28. 配置示例

```yaml
vector:
  enabled: true

  embedding:
    provider: local_or_http
    model: bge-small-zh-v1.5
    dimensions: 512
    normalize: true
    batch_size: 64
    cache: true

  index:
    provider: embedded_bbq
    algorithm: auto
    target_bits_per_dimension: 1
    query_bits_per_dimension: 4
    correction: true
    mmap: true
    simd: auto
    flat_scan_threshold: auto

  retrieval:
    top_k: 100
    oversampling_factor: 3.0

  rerank:
    enabled: true
    storage: int8
    top_k: 50

  compatibility:
    existing_bbq_http_adapter: false
```

13 所的具体 profile 后续可以覆盖：

- embedding 模型；
- group strategy；
- Top-K；
- rerank 精度；
- 字段权重；
- threshold。

---

## 29. 麒麟 Linux V10 离线打包

BBQ native 热路径必须预编译交付，不要求客户现场安装 gcc/rustc。

建议：

```text
runtime/
native/
├── x86_64/
│   └── material_matcher_native.so
└── aarch64/
    └── material_matcher_native.so
```

启动时：

1. 检测 CPU 架构；
2. 加载对应 native library；
3. 检测 SIMD 能力；
4. runtime dispatch 最优 kernel；
5. 打开 mmap 索引；
6. 启动服务。

Docker 不是运行前提。

---

## 30. Benchmark 基准必须同时看速度和召回

BBQ 优化不能只证明“更快”，还必须证明“没有把正确集团码丢出候选集”。

Benchmark 至少包含：

### 30.1 正确性

- 与 float32 exact cosine baseline 对比；
- 与既有 ZAIMAST BBQ 服务对比；
- 与历史相似物料算法对比；
- Recall@10；
- Recall@50；
- Recall@100；
- Top-1 accuracy；
- 最终集团码 precision / recall；
- 未匹配率；
- 错误自动匹配率。

### 30.2 性能

- 索引构建时间；
- 索引文件大小；
- 常驻 RSS；
- mmap page cache；
- 单 Query latency P50/P95/P99；
- Batch rows/s；
- 10 万 Source 完整批量耗时；
- CPU 利用率；
- embedding 耗时与 retrieval 耗时分拆。

### 30.3 对比矩阵

至少比较：

```text
float32 exact
int8
1-bit Hamming
BBQ 1-bit Target + 4-bit Query
BBQ + int8 rerank
BBQ + float16 rerank
BBQ Flat
BBQ HNSW
```

---

## 31. 选型原则

本项目最终不是追求“理论上最先进的向量数据库”，而是追求：

```text
在实际麒麟服务器上
以最小部署复杂度
在百万级 Target 上
尽可能低内存
尽可能高批量吞吐
同时保持足够高的正确集团码 Recall@K
```

因此默认选择应由实际 Benchmark 决定。

预期优先级：

```text
Embedded BBQ + mmap
    > 必须运维独立向量数据库
    > 必须 Docker/Kubernetes
```

但 `VectorIndex` 接口必须允许将来切换 Elasticsearch / Qdrant / Milvus 等外部后端。

---

## 32. 第一阶段实现建议

第一阶段优先实现：

1. `VectorIndex` 接口；
2. 历史 `xiaogang_similarity_v1` 精排 profile；
3. Existing BBQ HTTP compatibility adapter；
4. Target 1-bit packing；
5. Query 4-bit quantization；
6. native BBQ Flat batch kernel；
7. SIMD runtime dispatch；
8. Top-K partial selection；
9. int8 rerank sidecar；
10. material-group strict/global/mapped 分区；
11. mmap index format；
12. Benchmark 工具；
13. 再根据百万级实际 Benchmark 决定 HNSW / block-disk 实现优先级。

这个顺序的好处是：

- Flat + 1-bit 可以最快建立可验证的正确性基线；
- 可以直接与历史 BBQ 服务对拍；
- 可以先测出按物料组后实际候选规模；
- 如果绝大部分 group 过滤后只有数千到数万条，未必需要复杂 HNSW；
- 只有 global / 超大 group 才投入 HNSW 优化。

---

## 33. 与主开发设计书的关系

最终完整流程为：

```text
任意 Source / Target
↓
输入适配
↓
字段映射
↓
标准化 + 同义词
↓
物料组 strict / global / mapped
↓
BBQ 1-bit 高速候选召回
↓
int8 / float16 向量重排（可选）
↓
一对一 / 一对多 / 多对一 / 多对多字段精排
↓
字段权重
↓
规则冲突 / 上限
↓
final_raw_score
↓
严格成功阈值
↓
正式匹配结果 + Top-N 候选 + 可解释字段得分
```

其中 BBQ 是性能层，不改变业务层的通用配置模型。

---

## 34. 关键结论

1. **Target 主向量按 1 bit / dimension 极限压缩。**
2. **默认 Query 使用 4 bit 非对称量化，而不是把 Query 也强制压成 1 bit。**
3. **批量匹配必须使用 native SIMD/POPCNT + block search，不能 Python 逐条比较。**
4. **按物料组后的较小集合优先 BBQ Flat；百万级全局集合再使用 HNSW / block-disk。**
5. **1-bit 只负责召回；最终集团码仍由字段级精排和阈值决定。**
6. **历史物料相似度算法作为可复现 baseline/profile 继续保留。**
7. **既有 ZAIMAST BBQ 服务作为兼容与回归基准，不成为新系统强依赖。**
8. **默认方案必须能在无 Docker 的银河麒麟 Linux V10 离线运行。**
9. **任何性能优化都必须通过 Recall@K 和最终集团码错误率验证。**
10. **宁可多召回候选、后续精排，也不能为了极限速度把正确集团码在 BBQ 阶段提前丢掉。**
