# 物料集团码匹配引擎：Embedding 模型与批量性能设计

> 文档版本：v2.4
> 日期：2026-09-13
> 适用：银河麒麟 Linux V10、无 Docker、CPU-only 也必须可运行的现场部署

## 1. 结论

第一阶段正式默认 Embedding 模型选择：

```text
BAAI/bge-base-zh-v1.5
```

历史兼容/低资源模式：

```text
BAAI/bge-small-zh-v1.5
```

高精度可选模式：

```text
Qwen/Qwen3-Embedding-0.6B
```

模型只负责候选召回和语义特征，不直接决定最终集团码；最终结果仍由字段规则、数字权重、关键字段冲突和阈值共同决定。

## 2. 为什么选择 bge-base-zh-v1.5

### 2.1 场景适配

物料数据以中文短文本为主，包括名称、型号、规格、标准号、生产厂家等。该场景不需要 32K 长上下文，但需要较好的中文检索能力、稳定 CPU 批处理和可离线交付。

### 2.2 准确率与成本平衡

公开 C-MTEB 中文检索结果中：

- bge-small-zh-v1.5：Retrieval 61.77；
- bge-base-zh-v1.5：Retrieval 69.49；
- bge-large-zh-v1.5：Retrieval 70.46；
- Qwen3-Embedding-0.6B：CMTEB-R 71.02。

bge-base 相比 small 有明显提升，但比 0.6B/large 级模型更适合 CPU-only 的麒麟服务器。

### 2.3 工程属性

- 维度：768；
- 模型仓库约 410 MB；
- BERT Encoder，ONNX Runtime CPU 优化成熟；
- 最大序列长度 512，但本项目不默认使用满 512；
- 可离线打包；
- 适合批量短文本推理。

## 3. 模型不得写死

Embedding Provider 必须可替换：

```yaml
embedding:
  provider: onnx_local
  model_id: BAAI/bge-base-zh-v1.5
  dimensions: 768
  normalize: true
  precision: int8
  max_length: auto
  cache: true
```

索引必须绑定：model_id、模型文件 SHA-256、dimensions、precision、max_length、embedding 文本构造配置 SHA、数据处理流水线 SHA、集团码目录版本。

任一项变化都必须生成新索引版本，不得复用旧索引。

## 4. Embedding 文本属于业务配置

不得在核心代码写死“名称+型号+规格”。

```yaml
embedding_text:
  source:
    fields: [物料名称, 型号, 规格, 技术标准, 生产厂家]
    combine: concat
    separator: " "
  target:
    fields: [集团物料名称, 型号, 规格, 采用标准, 生产厂家]
    combine: concat
    separator: " "
```

不同客户、不同物料类别可使用不同文本构造方案。

## 5. 大批量向量化优化

现有向量专项设计已经包含：Batch-first、文本去重、embedding cache、SIMD/POPCNT、Block Scan、partial Top-K、Query 按 shard 重排、mmap、批量调度、int8/float16 rerank 等机制。本版本补足模型推理侧的时空优化。

正式 Target 建库流程：

```text
流式读取
→ 字段处理/组合
→ 文本哈希去重
→ token 长度统计与分桶
→ 批量 tokenizer
→ ONNX Runtime 批量 embedding
→ L2 normalize
→ 立即写 1-bit BBQ
→ 立即写 int8 rerank sidecar
→ 释放本 batch float32
```

禁止先生成 100 万条 float32 向量整体常驻内存/落盘后再进行第二次量化。

关键优化：

- 相同文本只向量化一次；
- Target embedding 跨任务长期缓存；
- cache key 包含模型、流水线和文本；
- batch 同时受行数和 max_batch_tokens 控制；
- 长度分桶减少 padding；
- tokenizer / inference / quantize+write 流水并行；
- batch 级 float32 中间张量；
- Target 索引顺序写入并原子切换；
- Source Query 默认任务级生命周期。

## 6. max_length 策略

不固定为 512。首次建库先对样本做 token 长度统计，根据 P99/P99.9 选择 128/192/256/512，并记录 P50/P95/P99/P99.9、截断条数和截断率。

## 7. 参考性能规模

基准工作量：

```text
Target：1,000,000 条
Source：100,000 条
Embedding：bge-base-zh-v1.5 / 768 维
retrieval_top_k：200
output_top_n：5
参考服务器：32 逻辑 CPU / 64 GB RAM / NVMe / 无 GPU
```

以下是工程预算，不是未实测服务器上的性能承诺。

### 7.1 Embedding 吞吐与时间

首次需要向量化最多约 1,100,000 条：

| 吞吐 | 约需时间 |
|---:|---:|
| 75 条/秒 | 4.07 小时 |
| 100 条/秒 | 3.06 小时 |
| 150 条/秒 | 2.04 小时 |
| 200 条/秒 | 1.53 小时 |
| 300 条/秒 | 1.02 小时 |
| 500 条/秒 | 0.61 小时 |

CPU-only 验收口径：>=150 条/秒推荐；100～150 条/秒可接受；<100 条/秒必须提示全量时间风险。

### 7.2 首次全量耗时预算

| 阶段 | 预算 |
|---|---:|
| 表格读取、处理、去重 | 5～20 分钟 |
| Target 100万 Embedding | 1～3 小时 |
| BBQ/int8 索引写入 | 5～20 分钟 |
| HNSW/Block（如需要） | 10～60 分钟 |
| Source 10万 Embedding | 5～20 分钟 |
| BBQ 召回 + 向量重排 | 5～30 分钟 |
| 字段精排 | 10～45 分钟 |
| 结果输出 | 3～15 分钟 |

产品目标：首次建库 + 10万客户物料完整匹配 2～4 小时。

### 7.3 后续任务

集团目录、模型、处理流水线和索引均不变时 Target 侧完全复用，10万客户物料任务目标 20～90 分钟。

## 8. 磁盘预算

默认模型 768 维、100 万 Target：

| 形态 | 空间 |
|---|---:|
| float32 | 3.072 GB |
| float16 | 1.536 GB |
| int8 sidecar | 0.768 GB |
| 1-bit BBQ | 96 MB |

10 万 Source 的 4-bit Query 主体约 38.4 MB。

正式推荐 `1-bit BBQ + int8 rerank + correction/ids/metadata + 可选 HNSW/Block`，按约 1.1～1.8 GB / 100万条索引版本预算；float16 rerank 模式约 1.9～2.7 GB / 版本。

为了原子切换至少预留两个索引版本。安装器最低建议可用数据盘 20 GB，推荐 50 GB 以上。

## 9. 内存预算

- 推荐 64 GB RAM；
- 32 GB 应能够通过 mmap + 分块运行；
- 不允许把百万级 float32 Target 作为常驻内存前提；
- 内存低于 32 GB 时必须给出告警并要求现场 Benchmark。

## 10. 自动 Benchmark 与预计完成时间

首次安装、模型切换或 CPU/线程参数变化时必须提供：

```text
benchmark embedding
benchmark index
benchmark match
```

从真实数据抽样 10,000～50,000 条，测量读取、tokenize、embedding、量化、索引、召回、精排吞吐，保存 P50/P95 batch latency，并在 UI 展示预计全量耗时和预计磁盘占用。预测超过默认 4 小时时必须提示风险。

## 11. 超时预算的降级顺序

1. 检查 max_length 是否明显大于真实 P99；
2. 调整 batch / token budget / ONNX 线程；
3. 开启/确认 INT8 CPU 推理；
4. 优先使用分类/物料组缩小候选空间；
5. 切换历史 bge-small-zh-v1.5 性能模式；
6. 有 GPU 时启用 GPU Execution Provider。

任何降级必须同时重新测 Recall@10 / Recall@50 / Recall@100 和最终集团码准确率。

## 12. 性能验收红线

- 必须拆分 embedding / retrieval / rerank / rule-score / export 各阶段耗时；
- 不得只给总时间而无法定位瓶颈；
- 不得因为速度降低 retrieval_top_k 而不验证 Recall@K；
- 不得重复计算未变化的 Target embedding；
- 不得在 Python 中对百万级向量逐条/逐维比较；
- 不得生成完整 Source×Target 相似度矩阵。
