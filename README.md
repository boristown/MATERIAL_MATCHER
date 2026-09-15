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

运行时版本已推进到 `0.8.0`。仓库已经具备从外部离线输入生成正式交付目录的源码级流水线，**但模型、wheel、Python Runtime 和最终离线包仍按仓库策略不提交 Git**。

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

新增：

```text
scripts/build_release.py
```

将已准备 Runtime、当前后端源码和 Vue production dist 组成 release，并校验：

- `pyproject.toml` 与 `material_matcher.__version__` 一致；
- release version 与项目版本一致；
- Runtime manifest 和 Runtime 文件树一致；
- Runtime 实际架构/Python 与 manifest 一致；
- 正式依赖可 import；
- `material-matcher --help` 可执行；
- `web/dist/index.html` 存在。

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

#### B/S 与部署预检

- FastAPI 正式 `serve` 命令可托管 Vue SPA，业务路由刷新回退到 `index.html`；未知 `/api/*` 不会错误返回前端页面；
- 模型目录统一为 `/var/lib/material_matcher/models/current`；
- 新增 `material-matcher doctor`，可要求检查前端、Embedding 和 release manifest；
- 安装器以正式 `material_matcher` 运行用户对**尚未激活的新版本**执行 doctor。

#### 事务化升级

升级顺序已调整为：

```text
校验离线包
→ 复制新 release/model
→ 旧服务保持在线
→ 新版本 doctor
→ doctor 全通过
→ 停止旧服务
→ 原子切换 current
→ 启动新服务
→ readiness
```

若 systemd 启动或 readiness 失败，会恢复安装前 release/model；若升级前旧服务正在运行，则重新启动旧版本。

同时取消每次升级对整个 `/var/lib/material_matcher` 的递归 `chown -R`，避免百万级索引/结果导致无意义的长时间文件遍历。

完整操作见：[v0.8 正式离线交付指南](docs/OFFLINE_RELEASE_GUIDE.md)。

## 当前性能与交付边界

v0.8 已具备业务闭环、向量执行、token-aware 调度、真实语料画像以及离线发布/升级机制，但**仍不能声明已经完成生产规模和麒麟实机验收**：

- Git 仓库按设计不提交 `bge-base-zh-v1.5` 模型、Python Runtime、wheelhouse 和最终安装介质；
- 真实语料画像仍需在客户真实数据 + 正式模型上执行；
- 尚未完成 100 万 Target / 10 万 Source 的真实 Recall@K、端到端耗时、内存和磁盘实测；
- 当前 packed-popcount 热路径仍为 portable NumPy/LUT，实现了正确的大规模结构但还未完成 native SIMD/POPCNT、HNSW 或 Block/Disk 自动路由；
- 离线构建、完整性检查、doctor、事务切换和回滚已有 CI 覆盖，但尚未在真实银河麒麟 Linux V10 + 正式 Runtime/wheel/model 介质上执行安装验收；
- SELinux/现场安全策略、systemd 权限和客户实际磁盘挂载差异仍需实机验证。

因此当前状态应理解为：**核心业务和性能候选架构已闭环，正式离线交付机制已实现到源码/自动化测试层，下一阶段重点是目标服务器实机、真实模型、准确率和百万级性能验收。**

## 下一里程碑

1. 准备目标 CPU 的正式基础 Python Runtime、完整 wheelhouse 与 `bge-base-zh-v1.5` ONNX/tokenizer，按 v0.8 流水线生成真实离线介质。
2. 在银河麒麟 V10 实机执行安装、升级、回滚、systemd/readiness、权限和磁盘映射验收。
3. 在目标 CPU 比较 portable packed-popcount、native SIMD/POPCNT、HNSW/Block/Disk，形成 `AutoBBQIndex` 选择策略。
4. 使用真实业务样本验证 Recall@10 / Recall@50 / Recall@100、TopN 排序和最终集团码准确率。
5. 完成 100 万 Target / 10 万 Source 首次建库及索引复用后的端到端 Benchmark，再判断是否满足首次 2～4 小时、复用索引后 20～90 分钟的产品目标。
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
