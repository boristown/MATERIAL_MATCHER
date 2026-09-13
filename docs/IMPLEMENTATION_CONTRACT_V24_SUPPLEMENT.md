# IMPLEMENTATION_CONTRACT v2.4 补充：Embedding 与批量性能

本补充文件与 `IMPLEMENTATION_CONTRACT.md` 同级生效，避免为了增加模型/性能规范而复制或改写原有第 21～40 章。

- 默认生产 Embedding：`BAAI/bge-base-zh-v1.5`，768 维；必须通过 Provider 可替换。
- 历史兼容/性能模式：`BAAI/bge-small-zh-v1.5`。
- 高精度可选：`Qwen/Qwen3-Embedding-0.6B`。
- CPU-only 参考规模 `100万 Target + 10万 Source`：首次完整处理目标 `2～4 小时`；集团目录、模型和处理流水线不变的后续任务目标 `20～90 分钟`。
- 必须支持 Target embedding 长期复用、文本去重、长度分桶、批量 tokenizer、批量 inference、流式量化与索引写入。
- 禁止把百万级 float32 Target 向量作为常驻内存或完整中间文件的必要前提。
- 推荐正式存储 `1-bit BBQ + int8 rerank sidecar`；768 维、100万条的向量主体约为：BBQ 96 MB、int8 768 MB。
- 首次安装、模型切换或 CPU 参数变化后必须做真实数据抽样 Benchmark，并预测全量耗时和磁盘；预测超过默认 4 小时必须告警。
- 任何性能降级策略都必须重新验证 Recall@10 / Recall@50 / Recall@100 和最终集团码准确率。

详细定义以 [`EMBEDDING_AND_PERFORMANCE_DESIGN.md`](./EMBEDDING_AND_PERFORMANCE_DESIGN.md) 为准。