# 物料集团码匹配引擎

面向集团物料编码统一场景的批量相似度匹配平台。

项目支持不同客户、不同数据格式、不同字段结构和不同匹配策略，通过业务配置完成大规模物料匹配，并输出可解释、可审计的候选及最终集团码结果。首个落地场景为 13 所，但底层架构不绑定单一客户、Excel 格式、SAP 表结构或物料类别。

## 核心原则

- 换客户、换表头、换字段、换权重、换阈值、换物料类别，不修改底层程序。
- 物料类别和匹配规则属于业务配置，不作为底层固定枚举。
- 普通业务用户使用图形化界面，不要求直接编辑技术配置文件。
- 日常操作统一为五步主流程：`选择数据 → 确认匹配规则 → 比对计算 → 人工处理 → 生成结果`。
- 匹配方案是可选复用模板，不是任务启动的强制前置条件。
- 字段重要程度使用 `0～100` 权重，运行时归一化。
- 目标环境为银河麒麟 Linux V10、B/S 架构、无 Docker、支持完全离线安装。
- 百万级 Target 优先通过压缩向量候选召回，再进行字段规则精排；不构造完整 Source × Target 相似度矩阵。
- 默认 Embedding 为 `BAAI/bge-base-zh-v1.5 / 768d`，通过 Provider 可替换。
- 性能与准确率必须以正式模型、真实数据和目标服务器实测为准，不使用 synthetic benchmark 冒充生产验收。

## 当前运行版本

`0.9.0`

## 已实现里程碑

### v0.4：端到端业务闭环

```text
上传 Source / Target
→ 自动识别与字段确认
→ 配置字段组合、权重、阈值和匹配范围
→ Dry Run
→ 持久化任务执行
→ TopN / 第二候选 / 分差 / 字段解释
→ 人工确认或标记未匹配
→ 生成并下载最终 Excel
```

小任务可以使用通用扫描后端完成全流程。

### v0.5：可复用向量执行核心

- 可替换 `EmbeddingProvider`；
- 本地 ONNX Provider，模型/Runtime 缺失时显式失败，不伪造语义结果；
- 持久化 Embedding Cache；
- Target fingerprint 绑定目录、文件 SHA、模型、维度、检索文本处理规则和分类字段；
- Target 1-bit packed vector，Query 4-bit，候选 int8 sidecar 重排；
- packed bytes + Query bit-plane + XOR/AND + popcount LUT 粗召回；
- mmap + blockwise TopK；
- STRICT / MAPPED postings；
- `scan / vector` 自动路由；
- 索引 BUILDING / READY / FAILED、复用状态和任务阶段持久化；
- CLI 提供 Embedding 与向量内核 benchmark。

### v0.6：Token-aware Embedding

- tokenizer 实际 token 长度；
- P50 / P95 / P99 / P99.9 / 最大长度；
- 128 / 192 / 256 / 512 截断率和建议 `max_length`；
- `max_batch_size + token_budget` 双约束分桶；
- 默认 `MATERIAL_MATCHER_EMBEDDING_TOKEN_BUDGET=16384`；
- Embedding Cache、Target 建库和 Query 推理统一继承 batching 策略；
- benchmark 输出 micro-batches 与 padding efficiency。

### v0.7：真实任务语料画像

任务规则页可以使用正式 retrieval text 和正式 tokenizer 分析 Source / Target：

- deterministic bounded reservoir；
- 默认最多保留 4096 样本、同步扫描最多 10 万行；
- `scan_complete / scanned_rows / coverage_ratio`；
- P50/P95/P99/P99.9、截断率、空文本率、重复率、Padding 效率；
- 推荐值 advisory only，只有用户显式采用后才写入草稿；
- 正式任务启动后随不可变 `config_snapshot` 冻结。

接口：

```text
POST /api/task-drafts/{draft_id}/text-profile
```

### v0.8：正式离线交付与事务化升级

仓库已经具备从外部离线输入生成正式交付目录的源码级流水线；模型、wheel、Python Runtime 和最终安装介质不提交 Git。

主要能力：

- `scripts/prepare_runtime.py`：使用目标架构 Python Runtime + wheelhouse，自包含安装且强制 `--no-index`；
- `scripts/build_release.py`：验证版本、Runtime manifest、依赖、CLI、Vue production dist；
- `scripts/build_offline_bundle.py`：组装 release、模型和 wheelhouse；
- `installer/verify_offline_bundle.py`：Runtime → Release → Offline 三层 SHA-256/版本/架构完整性链；
- `material-matcher doctor`：正式切换前验证前端、Embedding、数据目录和 release；
- 新版本在旧服务在线时复制和 doctor，通过后再停止旧服务并原子切换；
- readiness 失败自动恢复旧 release/model；
- 避免升级时递归 `chown -R /var/lib/material_matcher`。

完整操作见 [v0.8 正式离线交付指南](docs/OFFLINE_RELEASE_GUIDE.md)。

### v0.9：召回质量与真实业务准确率验收

#### 向量质量基线

`benchmark vector` 在性能指标之外，使用有界 `float32 exact cosine` reference 计算有效范围内的 Recall@K 和 Top1 hit rate，并明确标记：

```text
production_performance_claim = false
business_accuracy_claim = false
```

该指标用于比较 BBQ/native/HNSW 等检索实现是否出现召回退化，不等同于业务集团码准确率。

#### 真实任务业务验收

完成任务可以进入“准确率验收”，上传 `supplement` 类型 Excel/CSV 真值文件，并按 `source_id` 或 `source_row_id` 对齐。

报告包含：

- 真值覆盖率；
- 原始 Top1 准确率；
- 人工处理后的最终准确率与准确率增益；
- 自动匹配区准确率；
- Review / 未匹配 / 最终有结果比例；
- 正确集团码在持久化候选中的 Recall@K；
- 错例、未覆盖真值、正确候选排名。

候选 Recall 严格受冻结任务的 `decision.top_n` 限制，不对未持久化的候选深度伪造指标。验收只读取任务结果，不修改冻结结果，并持久化 `evaluation_runs / evaluation_items` 和审计事件。

接口：

```text
POST /api/tasks/{task_id}/evaluations
GET  /api/tasks/{task_id}/evaluations
GET  /api/evaluations/{run_id}
```

### v0.9 控制面增强：匹配方案

`/profiles` 已由占位页升级为真实方案管理：

- 新建、编辑草稿、校验、发布；
- PUBLISHED 版本不可变；
- 回滚通过复制历史版本生成新的发布版本，不覆盖历史；
- 支持多字段、`concat / coalesce / best_of`、GLOBAL / STRICT / MAPPED；
- 常用界面编辑时保留 pipeline、matcher_options、retrieval 和 advanced 中未展示的高级配置，避免复杂方案被降级保存；
- 已发布方案可以可选地创建任务草稿；
- 任务草稿记录 `profile_id + version_no` 来源，最终任务仍冻结完整 `config_snapshot`；
- 后端校验引用的方案版本真实存在且为 PUBLISHED，拒绝伪造方案来源。

方案仍然只是可选模板，直接新建任务的路径保持不变。

### v0.9 控制面增强：基础数据

`/data` 已由占位页升级为真实资产管理：

- 集团码目录；
- 上传文件资产；
- 实际向量索引状态；
- 新建目录时创建并激活首个不可变版本；
- 同一目录可以上传后续不可变版本；
- READY 版本可显式切换 active，且同一目录只允许一个 active；
- 目录版本切换不会修改历史任务的 `catalog_version_id`；
- 新 Target 版本首次进入向量任务时仍按真实 fingerprint 判断构建或复用索引，不伪造索引 READY。

对应目录版本接口：

```text
GET  /api/catalogs/{catalog_id}/versions
POST /api/catalogs/{catalog_id}/versions
POST /api/catalogs/{catalog_id}/versions/{version_id}/activate
```

注意：当前 `active` 是基础数据中的“当前目录版本”标记。五步任务第一步仍支持上传/绑定自己的 Target 目录版本，尚未自动改成使用 active 目录；“直接选择已有目录创建任务”仍属于下一阶段工作。

## 当前自动化基线

最新稳定 CI：

- backend：成功；
- frontend：成功；
- `pytest -q`：**57 passed**；
- `python -m compileall -q src`：通过；
- `bash -n installer/install.sh`：通过；
- repository file policy：通过；
- Vue production build：通过。

当前仅有 FastAPI/Starlette 测试依赖的外部 deprecation warning，不影响测试结果。

## 当前性能与交付边界

当前已经具备业务闭环、向量执行、token-aware 调度、真实语料画像、离线发布/升级、召回/业务准确率验收，以及真实的方案和基础数据管理能力，但**仍不能声明完成生产规模和银河麒麟实机验收**：

- Git 仓库按设计不提交 `bge-base-zh-v1.5` 正式模型、Python Runtime、wheelhouse 和最终安装介质；
- 真实业务准确率必须使用客户历史正确集团码/人工金标实际测量；
- 尚未完成 100 万 Target / 10 万 Source 正式模型端到端耗时、内存、磁盘和真实 Recall 实测；
- packed-popcount 当前仍为 portable NumPy/LUT，是否投入 native SIMD/POPCNT、HNSW/Block/Disk 需由实测决定；
- 尚未在真实银河麒麟 V10 + 正式 Runtime/wheel/model 介质执行安装、升级、回滚和 systemd/readiness 验收；
- 基础数据的 active 目录尚未接入任务第一步的“选择已有目录”入口；
- 字典/同义词管理尚未产品化，因为当前 normalize pipeline 没有运行时字典 lookup 操作；在执行引擎真正消费前不会提供装饰性字典配置页；
- 账号/权限仍需按最终部署要求强化。

因此当前状态应理解为：**核心匹配平台与主要业务控制面已经闭环，下一阶段重点转向真实数据、真实模型、目标服务器和生产治理验收。**

## 下一里程碑

1. 在任务“选择数据”阶段增加“上传新 Target / 选择已有目录版本”二选一，并保持五步主流程不变。
2. 准备目标 CPU 的正式 Python Runtime、完整 wheelhouse 与 `bge-base-zh-v1.5` ONNX/tokenizer，生成真实离线介质。
3. 使用客户历史正确集团码/人工金标运行业务验收，形成真实 Top1、最终准确率、Review率和候选 Recall 基线。
4. 在银河麒麟 V10 实机执行安装、升级、回滚、systemd/readiness、权限与磁盘映射验收。
5. 完成 100 万 Target / 10 万 Source 首次建库及索引复用后的端到端 Benchmark；仅在实测需要时再投入 native SIMD/POPCNT、HNSW/Block/Disk。
6. 强化账号/权限；如确有业务需求，再增加会被 normalize pipeline 实际消费的字典/同义词能力。
7. 如现场确有需要，将百万级全量 token 画像升级为持久化、可恢复、可显示进度的异步预检任务。

## 当前 13 所业务样例

当前公开样例中包含：

- A001：元器件；
- A002：标准件；
- A003：金属材料；
- A005：非金属材料；
- A006：复合材料；
- A007：物资类其他。

以上仅是 13 所的一套业务配置，其他单位可以使用完全不同的物料类别代码和匹配方案。

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
