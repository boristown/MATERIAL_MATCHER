# 物料集团码匹配引擎

面向集团物料编码统一场景的批量相似度匹配平台。

项目目标是支持不同客户、不同数据格式、不同字段结构和不同匹配策略，通过业务配置完成大规模物料匹配，并输出可解释、可审计的候选及最终集团码结果。

当前首个落地场景为 13 所集团物料编码匹配，但底层架构不绑定单一客户、单一 Excel 格式、单一 SAP 表结构或单一物料类别。

## 核心原则

- 换客户、换表头、换字段、换权重、换阈值、换物料类别，不修改底层程序。
- 物料类别和各类别的匹配规则属于业务配置，不作为底层固定枚举。
- 普通业务用户通过图形化向导配置，不直接接触技术配置文件。
- 日常操作统一为一条五步主流程：`选择数据 → 确认匹配规则 → 比对计算 → 人工处理 → 生成结果`，普通用户只进入“匹配任务”即可完成全过程。
- 匹配方案只是可复用模板，不是运行任务的强制前置条件。
- 字段重要程度统一使用 `0～100` 数字权重，并实时显示系统归一化后的实际占比。
- 采用 B/S 架构，目标服务器为银河麒麟 Linux V10，无 Docker 也可完全离线一键安装。
- 集团侧百万级数据优先使用单比特向量压缩进行高速候选召回，再结合字段规则进行精排。
- 第一阶段默认 Embedding 采用 `BAAI/bge-base-zh-v1.5`，但通过 Provider 可替换；模型、处理流水线和集团目录不变时必须复用 Target 向量与索引。
- CPU-only 参考环境下，100 万集团物料首次建库 + 10 万客户物料完整匹配的产品目标为数小时级（参考 2～4 小时），实际以现场自动 Benchmark 为准。

## 当前实现里程碑

### v0.4：小规模端到端业务闭环

已打通：

```text
上传 Source / Target
→ 自动识别与字段确认
→ 配置字段组合、权重、阈值和匹配范围
→ Dry Run
→ SQLite 持久化任务队列执行
→ TopN / 第二候选 / 分差 / 字段解释
→ 人工确认或标记未匹配
→ 生成并下载最终 Excel
```

小任务仍可使用通用扫描后端完成完整业务流程；不会构造完整 Source × Target 相似度矩阵。

### v0.5：可复用向量执行核心

当前开发分支已经接入向量检索正式执行链路：

- 可替换 `EmbeddingProvider`，默认配置为 `BAAI/bge-base-zh-v1.5 / 768 维`；
- 本地 ONNX Provider，模型文件和运行时缺失时显式报告，不使用伪语义结果；
- 持久化 Embedding Cache，相同模型/处理规则/文本可跨任务复用；
- Target 索引 fingerprint 绑定目录版本、Target 文件 SHA、模型实际 SHA、维度、检索文本处理规则和分类字段；
- 仅修改评分权重或最终判定阈值不会错误触发 Target 重建；
- Target 主索引采用 1-bit packed vector，Query 采用 4-bit 非对称量化；
- 粗召回使用 packed bytes + Query sign/3 magnitude bit-plane + XOR/AND + popcount LUT，避免展开 Target bit matrix；
- 候选使用 int8 sidecar 重排；
- 分块 TopK 召回，不生成 Source × Target 全量相似度矩阵；
- STRICT / MAPPED 模式使用分类 postings 先缩小候选范围；
- `scan / vector` 自动路由：小任务继续走扫描，大目录或显式语义规则进入向量链路；
- `index_versions` 持久化 BUILDING / READY / FAILED 生命周期，并支持不变 Target 索引复用；
- 任务运行阶段持久化 `INDEX / RETRIEVE / RERANK / PERSIST / DONE` 和实际 Index ID；
- “系统设置”可查看模型/Runtime readiness、索引版本和 Benchmark 历史；
- 任务页只有在正式 Embedding Runtime + 模型文件就绪时才开放“语义相似”；
- 提供 `material-matcher benchmark embedding` 和 `material-matcher benchmark vector`。

### v0.6：Token-aware Embedding 批处理

为降低 CPU-only ONNX 推理中的 padding 浪费，正式 Provider 已接入长度感知批处理：

- tokenizer 先得到实际 token 长度；
- 输出 P50 / P95 / P99 / P99.9 / 最大长度；
- 统计 128 / 192 / 256 / 512 的截断比例，并给出覆盖 P99 的最小推荐 `max_length`；
- 按 token 长度排序组批，同时受 `max_batch_size` 与 `token_budget` 双重约束；
- 默认 `MATERIAL_MATCHER_EMBEDDING_TOKEN_BUDGET=16384`，可在现场按 CPU/内存调整；
- 分桶推理完成后恢复原输入顺序，不改变向量与物料的对应关系；
- Embedding Cache miss 会进入相同的 token-aware batching，cache key 和向量语义保持不变；
- Token Budget 从 Settings 传入正式 Provider，并由现有 Target 建库 / Query Cache 自动继承，不只是 UI 展示参数；
- 正式 Embedding Benchmark 新增 `token_length_profile`、不同长度截断率、planned micro-batches 与 padding efficiency；
- 系统设置页直接展示 Batch Size、Token Budget、P99、建议 max_length 和 padding efficiency。

其中：

- `benchmark embedding` 使用**实际配置的生产 Embedding Provider / 模型**测量吞吐、P50/P95 batch latency、token 长度画像和 110 万条向量化预计时长；
- `benchmark vector` 使用确定性测试向量测量实际 BBQ build/search 内核，只用于内核基准，明确不作为生产模型端到端性能承诺。

## 当前性能边界

v0.6 已具备大规模向量路径和 token-aware 推理调度结构，但**尚不能声明已经达到 100 万 Target / 10 万 Source 的生产性能目标**：

- 本仓库不提交 `bge-base-zh-v1.5` 模型文件，也没有在 GitHub CI 中运行真实模型推理；
- 当前 Benchmark 的 token 画像功能已经完成，但还需要在真实业务 Source/Target 检索文本上采样，而不是只看 synthetic benchmark 文本；
- 尚未在目标银河麒麟 Linux V10 服务器安装正式 ONNX 模型并执行现场 Benchmark；
- 尚未完成 100 万 Target / 10 万 Source 的真实 Recall@K、端到端阶段耗时和内存/磁盘实测；
- 当前 `EmbeddedBBQFlatIndex` 已使用 portable packed-popcount 热路径，但仍是 NumPy/LUT 实现，尚不是最终 native SIMD/POPCNT、HNSW 或 Block/Disk 路由实现。

因此当前状态应理解为：**业务闭环已完成，向量执行核心和 token-aware 推理调度已接通，正在进入真实模型、真实语料和生产规模验收阶段。**

## 下一里程碑

1. 对真实任务的 Source/Target retrieval text 进行流式采样，生成实际业务 token P50/P95/P99/P99.9、截断率和推荐 max_length。
2. 正式离线交付 `bge-base-zh-v1.5` ONNX / tokenizer 与 `onnxruntime + tokenizers` wheelhouse，不将模型二进制提交到 Git。
3. 在目标 CPU 上 Benchmark portable packed-popcount、native SIMD/POPCNT、HNSW/Block/Disk 路径，形成 `AutoBBQIndex` 选择策略。
4. 使用真实业务样本验证 Recall@10 / Recall@50 / Recall@100、TopN 排序和最终集团码准确率。
5. 完成 100 万 Target / 10 万 Source 首次建库与索引复用后的端到端 Benchmark，再决定是否满足 2～4 小时和 20～90 分钟产品目标。
6. 完成自包含 Python Runtime、前端 dist、wheelhouse、模型和 Native 组件的正式离线安装介质，并在真实银河麒麟 V10 验收。

## 当前 13 所业务样例

当前公开样例中包含：

- A001：元器件；
- A002：标准件；
- A003：金属材料；
- A005：非金属材料；
- A006：复合材料；
- A007：物资类其他。

以上仅是 13 所的一套业务配置，其他单位可使用完全不同的物料类别代码和匹配方案。

## 文档

- [物料集团码匹配引擎开发设计书](docs/DEVELOPMENT_DESIGN.md)
- [业务操作界面专项设计 v2.5](docs/OPERATION_UI_DESIGN.md)
- [v2.5 五步任务主流程补充规范](docs/TASK_FLOW_V25_SUPPLEMENT.md)
- [Embedding 模型与批量性能设计](docs/EMBEDDING_AND_PERFORMANCE_DESIGN.md)
- [单比特向量索引与高速批量匹配设计](docs/VECTOR_INDEX_DESIGN.md)
- [开发实施强制规范](docs/IMPLEMENTATION_CONTRACT.md)
- [v2.4 Embedding 与性能实施补充](docs/IMPLEMENTATION_CONTRACT_V24_SUPPLEMENT.md)
- [核心函数、接口、UI、部署与验收规范](docs/API_UI_DEPLOYMENT_CONTRACT.md)
- [项目背景与设计约束](docs/PROJECT_BACKGROUND.md)
- [零代码客户适配设计](docs/ZERO_CODE_ADAPTATION_DESIGN.md)
- [插件化架构设计](docs/PLUGIN_ARCHITECTURE.md)
- [非技术用户配置体验设计](docs/NON_TECHNICAL_CONFIGURATION_DESIGN.md)
- [麒麟 V10 一键部署、运行与 B/S 界面设计](docs/DEPLOYMENT_AND_UI_DESIGN.md)
- [13 所物料类别业务配置说明](docs/customers/13_institute_material_type_config.md)
- [13 所已验证字段映射草案](docs/customers/13_institute_z001_z006_mapping.md)
