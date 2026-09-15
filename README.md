# 物料集团码匹配引擎

面向集团物料编码统一场景的批量相似度匹配平台。

项目目标是支持不同客户、不同数据格式、不同字段结构和不同匹配策略，通过业务配置完成大规模物料匹配，并输出可解释、可审计的候选及最终集团码结果。

当前首个落地场景为 13 所集团物料编码匹配，但底层架构不绑定单一客户、单一 Excel 格式、单一 SAP 表结构或单一物料类别。

## 核心原则

- 换客户、换表头、换字段、换权重、换阈值、换物料类别，不修改底层程序。
- 物料类别和各类别的匹配规则属于业务配置，不作为底层固定枚举。
- 普通业务用户通过图形化向导配置，不直接接触技术配置文件。
- 日常操作统一为一条五步主流程：`选择数据 → 确认匹配规则 → 比对计算 → 人工处理 → 生成结果`。
- 匹配方案只是可复用模板，不是运行任务的强制前置条件。
- 字段重要程度统一使用 `0～100` 数字权重，并由运行时归一化。
- 采用 B/S 架构，目标服务器为银河麒麟 Linux V10，无 Docker，正式交付支持完全离线安装。
- 集团侧百万级数据优先使用单比特向量压缩进行候选召回，再结合字段规则精排。
- 第一阶段默认 Embedding 为 `BAAI/bge-base-zh-v1.5`，但通过 Provider 可替换；模型、处理流水线和集团目录不变时复用 Target 向量与索引。
- CPU-only 参考环境下，100 万 Target + 10 万 Source 的产品目标为首次数小时级、索引复用后更短；最终以目标服务器实测为准，不以 synthetic benchmark 代替生产验收。

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

小任务可使用通用扫描后端完成完整业务流程；不会构造完整 Source × Target 相似度矩阵。

### v0.5：可复用向量执行核心

- 可替换 `EmbeddingProvider`，默认 `BAAI/bge-base-zh-v1.5 / 768维`；
- 本地 ONNX Provider，Runtime/模型缺失时显式失败，不伪造语义结果；
- 持久化 Embedding Cache；
- Target fingerprint 绑定目录、文件 SHA、模型 SHA、维度、检索文本处理规则和分类字段；
- 只改评分权重或最终阈值不会误触发 Target 重建；
- Target 采用 1-bit packed vector；Query 采用 4-bit signed-magnitude；候选使用 int8 sidecar 重排；
- packed bytes + Query bit-plane + XOR/AND + popcount LUT 粗召回；
- mmap + blockwise TopK，不生成 Source × Target 全量矩阵；
- STRICT / MAPPED 使用分类 postings 先缩小候选；
- `scan / vector` 自动路由；
- `index_versions` 持久化 BUILDING / READY / FAILED，并支持索引复用；
- 任务阶段持久化 `INDEX / RETRIEVE / RERANK / PERSIST / DONE` 和实际 Index ID；
- 提供 `material-matcher benchmark embedding` 与 `material-matcher benchmark vector`。

### v0.6：Token-aware Embedding 批处理

- tokenizer 获取实际 token 长度；
- 输出 P50 / P95 / P99 / P99.9 / 最大长度；
- 统计 128 / 192 / 256 / 512 截断比例并推荐覆盖 P99 的 `max_length`；
- `max_batch_size + token_budget` 双约束长度分桶；
- 默认 `MATERIAL_MATCHER_EMBEDDING_TOKEN_BUDGET=16384`；
- 分桶推理后恢复原输入顺序；
- Embedding Cache miss 使用同一 token-aware batching；
- Target 建库和 Query Cache 自动继承 Token Budget；
- Benchmark 展示 token 分布、截断率、micro-batches 与 padding efficiency。

### v0.7：真实任务语料画像

任务规则页可直接基于当前 Source / Target 与 retrieval 配置分析真实业务文本：

- 使用正式执行相同的 `build_retrieval_text`；
- 使用当前正式 Provider tokenizer，模型未就绪时不以测试 tokenizer 冒充；
- 文件流式读取 + deterministic bounded reservoir；
- 默认最多保留 4096 条样本、同步扫描最多 10 万行；
- 明确返回 `scan_complete / scanned_rows / coverage_ratio`；
- 分别统计 Source / Target P50/P95/P99/P99.9、截断率、空文本率、重复率、Padding 效率；
- 推荐值是 advisory only，不会隐藏修改草稿；
- 用户显式“采用建议值”后才更新 `retrieval.max_length`，正式任务启动后随不可变 `config_snapshot` 冻结。

接口：

```text
POST /api/task-drafts/{draft_id}/text-profile
```

### v0.8：正式离线交付与安全升级链路

仓库已经具备从外部离线输入生成正式交付目录的源码级流水线，**但模型、wheel、Python Runtime 和最终离线包仍按仓库策略不提交 Git**。

#### 自包含 Runtime

新增：

```text
scripts/prepare_runtime.py
```

输入为目标架构的基础 Python Runtime 和完整 wheelhouse。构建过程强制：

```text
pip --no-index --find-links <wheelhouse>
```

不会在缺包时回退公网。完成后执行 `pip check`、正式依赖 import、CPU 架构检查，并生成：

```text
runtime/bin/python3
runtime/bin/material-matcher
runtime/runtime-manifest.json
```

启动器属于 Runtime 完整性的一部分。

#### Release 构建

`scripts/build_release.py` 将已准备 Runtime、当前后端源码和 Vue production dist 组成 release，并校验：

- `pyproject.toml` 与 `material_matcher.__version__` 一致；
- release version 与项目版本一致；
- Runtime manifest 和 Runtime 文件树一致；
- Runtime 实际架构/Python 与 manifest 一致；
- 正式依赖可 import；
- `material-matcher --help` 可执行；
- `web/dist/index.html` 存在；
- release 源码复制排除 `__pycache__ / *.pyc / *.pyo`，避免构建机运行痕迹进入正式介质。

生成 `release-manifest.json`，固化 Runtime manifest、源码树和前端树摘要。

#### Offline Bundle

`scripts/build_offline_bundle.py` 将 release、正式模型和 wheelhouse 组装为最终离线目录。`installer/verify_offline_bundle.py` 实现三层完整性链：

```text
runtime-manifest.json
        ↓
release-manifest.json
        ↓
offline-manifest.json
```

校验器会重新计算 Runtime、后端源码、Vue dist 与离线包逐文件 SHA-256，并拒绝：缺件、未登记文件、篡改、路径逃逸、不安全符号链接、版本混装、CPU 架构不匹配以及错误架构的 `onnxruntime/tokenizers` wheel。

#### B/S、预检与事务化升级

- FastAPI 正式 `serve` 命令可托管 Vue SPA，未知 `/api/*` 不会错误返回前端页面；
- 模型目录统一为 `/var/lib/material_matcher/models/current`；
- `material-matcher doctor` 可检查前端、Embedding、数据目录和 release manifest；
- 新 release/model 在旧服务仍在线时复制并预检，全部通过后才停止旧服务并原子切换 `current`；
- 新服务启动/readiness 失败时恢复旧 release/model，并在升级前旧服务确实运行时重新启动旧版本；
- 不再对整个 `/var/lib/material_matcher` 执行递归 `chown -R`，避免百万级索引目录拖长升级窗口。

完整操作见：[v0.8 正式离线交付指南](docs/OFFLINE_RELEASE_GUIDE.md)。

### v0.9：召回质量与真实业务准确率验收

运行时版本已推进到 `0.9.0`。本阶段把“性能 benchmark”升级为“性能 + 质量双验收”，并把准确率验收从 synthetic reference 延伸到真实业务标注集。

#### 向量 Recall 基线

`benchmark vector` 除吞吐和磁盘占用外，会在有界 reference 子集上使用 `float32 exact cosine` 作为基准，计算：

- Recall@10 / Recall@50 / Recall@100（在有效 K 范围内）；
- Top1 hit rate；
- reference rows / query count；
- 明确标记 `production_performance_claim=false`、`business_accuracy_claim=false`。

该指标用于比较 portable BBQ、未来 native SIMD/POPCNT、HNSW/Block 等检索实现是否发生召回退化，**不等同于业务集团码准确率**。

#### 真实任务业务验收

完成任务可以额外进入“准确率验收”，上传 `supplement` 类型的 Excel/CSV 真值文件，并显式选择：

- 验收键：`source_id` 或 `source_row_id`；
- 真值文件中的验收键列；
- 正确集团码列。

验收层只读取冻结的任务结果，不修改任务，持久化 `evaluation_runs / evaluation_items` 与审计事件。报告包括：

- 真值覆盖率；
- 原始 Top1 准确率；
- 人工处理后的最终准确率与人工增益；
- 自动匹配区准确率；
- Review / 未匹配 / 最终有结果比例；
- 正确集团码在持久化候选中的 Recall@K；
- 错例、未覆盖真值以及正确候选排名。

候选 Recall 严格受任务冻结的 `decision.top_n` 限制。例如任务只保存 Top3，就不会伪报 Recall@5/10。

对应接口：

```text
POST /api/tasks/{task_id}/evaluations
GET  /api/tasks/{task_id}/evaluations
GET  /api/evaluations/{run_id}
```

任务列表中已完成任务提供“准确率验收”入口，验收历史与错例可回看。该功能用于真实标注集验收；在尚未导入客户真实真值前，不对实际业务准确率作数值承诺。

#### 自动化基线

v0.9 收口 CI：GitHub Actions run #122，backend / frontend 均成功；`pytest -q` 为 **44 passed**，同时通过 `compileall`、安装脚本语法校验、仓库文件策略与 Vue production build。

## 当前性能与交付边界

v0.9 已具备业务闭环、向量执行、token-aware 调度、真实语料画像、离线发布/升级机制以及可重复的召回/业务准确率验收框架，但**仍不能声明已经完成生产规模和银河麒麟实机验收**：

- Git 仓库按设计不提交 `bge-base-zh-v1.5` 模型、Python Runtime、wheelhouse 和最终安装介质；
- 准确率验收框架已经完成，但真实业务准确率仍必须使用客户历史正确集团码/人工金标数据实际测量；
- 尚未完成 100 万 Target / 10 万 Source 的正式模型端到端耗时、内存、磁盘与真实 Recall 实测；
- 当前 packed-popcount 热路径仍为 portable NumPy/LUT，实现了正确的大规模结构但还未完成 native SIMD/POPCNT、HNSW 或 Block/Disk 自动路由；
- 离线构建、完整性检查、doctor、事务切换和回滚已有 CI 覆盖，但尚未在真实银河麒麟 Linux V10 + 正式 Runtime/wheel/model 介质上执行安装验收；
- `匹配方案` 与 `基础数据` 的底层表已存在，但前端仍需从占位页面产品化；账号/权限也仍需按最终部署要求强化。

因此当前状态应理解为：**核心匹配平台、性能候选架构、离线交付机制和质量验收框架均已形成；下一阶段主要进入真实数据/真实机器验收，以及平台外围管理能力产品化。**

## 下一里程碑

1. 准备目标 CPU 的正式基础 Python Runtime、完整 wheelhouse 与 `bge-base-zh-v1.5` ONNX/tokenizer，按 v0.8 流水线生成真实离线介质。
2. 使用客户历史正确集团码/人工金标数据运行 v0.9 业务验收，形成真实 Top1、最终准确率、Review率和候选 Recall 基线。
3. 在银河麒麟 V10 实机执行安装、升级、回滚、systemd/readiness、权限和磁盘映射验收。
4. 完成 100 万 Target / 10 万 Source 首次建库及索引复用后的端到端 Benchmark；仅在实测需要时再投入 native SIMD/POPCNT、HNSW/Block/Disk。
5. 产品化“匹配方案”和“基础数据”管理页面，并补最终账号/权限治理。
6. 如现场确有需要，将百万级全量 token 画像升级为持久化、可恢复、可显示进度的异步预检任务。

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
- [银河麒麟 V10 部署设计](docs/DEPLOYMENT_AND_UI_DESIGN.md)
- [v0.8 正式离线交付指南](docs/OFFLINE_RELEASE_GUIDE.md)
- [项目背景与设计约束](docs/PROJECT_BACKGROUND.md)
- [零代码客户适配设计](docs/ZERO_CODE_ADAPTATION_DESIGN.md)
- [插件化架构设计](docs/PLUGIN_ARCHITECTURE.md)
- [非技术用户配置体验设计](docs/NON_TECHNICAL_CONFIGURATION_DESIGN.md)
- [13 所物料类别业务配置说明](docs/customers/13_institute_material_type_config.md)
- [13 所已验证字段映射草案](docs/customers/13_institute_z001_z006_mapping.md)
