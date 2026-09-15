# 物料集团码智能匹配平台

MATERIAL_MATCHER 是面向集团物料编码统一场景的批量相似物料匹配平台。它支持不同客户、不同 Excel/CSV 结构、不同字段组合和不同匹配策略，通过可配置规则完成候选召回、精细评分、人工复核和最终集团码输出。

**当前代码版本：`1.0.0`**

> `1.0.0` 表示仓库内可实现的产品、工程、部署与验收能力已经形成完整闭环；不代表客户现场已经完成生产验收。正式上线必须继续按照 [`agent.md`](agent.md) 在银河麒麟 V10、正式模型、真实金标和真实 100K×1M 数据上取得证据，并以 `material-matcher acceptance --require-production-ready` 返回 0 为最终门禁。

## 产品原则

- 五步主流程固定为：`选择数据 → 确认匹配规则 → 比对计算 → 人工处理 → 生成结果`。
- 匹配方案是可选复用模板，不是任务创建前置条件。
- 换客户、换表头、换字段、换权重、换物料类别不修改底层程序。
- 默认 normalization 是 identity；大小写、标点、正则、字典、NULL、数值容差都必须显式配置。
- 任务启动后冻结完整配置快照、目录版本、方案版本和字典版本语义，历史任务不随控制面更新漂移。
- 百万级 Target 使用候选召回 + 字段精排，不构造完整 Source×Target 相似度矩阵。
- 默认 Embedding 为 `BAAI/bge-base-zh-v1.5 / 768d`，Provider 可替换。
- synthetic benchmark 只用于性能/召回回归保护，不能冒充真实业务准确率或生产规模验收。

## 1.0 已实现能力

### 五步业务闭环

- `.xlsx / .xlsm / .csv` 上传、检查和字段识别；明确拒绝旧 `.xls`。
- 第 1 步 Target 支持二选一：
  - 直接选择“基础数据”中已有 READY 集团码目录版本；
  - 上传新 Target 并创建新的不可变目录版本。
- Source 物料标识字段和集团码字段确认。
- 第 2 步支持多字段、`concat / coalesce / best_of`、权重、关键字段、阈值和 GLOBAL / STRICT / MAPPED 范围。
- `exact / contains / fuzzy / hybrid / semantic / numeric` 匹配内核；数值容差不提供隐藏默认值。
- Dry Run、正式持久化 worker、重启恢复、进度阶段、TopN、第二候选、分差、字段解释。
- 人工确认、批量确认、标记未匹配和审计记录。
- 最终 Excel 结果生成和下载。

### 匹配方案

`/profiles` 已是版本化业务控制面：

- DRAFT / 校验 / PUBLISHED；
- 已发布版本不可变；
- 回滚会复制历史版本并产生新的发布版本；
- 高级 `pipeline / matcher_options / retrieval / advanced` 在普通编辑时无损保留；
- 支持业务字典选择与 numeric tolerance；
- 已发布方案可选创建任务草稿；
- 服务端验证方案来源必须是真实 PUBLISHED 版本。

### 基础数据

`/data` 已支持：

- 集团码目录及不可变版本；
- 同目录唯一 active READY 版本；
- 上传文件资产；
- 实际向量索引状态；
- 业务字典及不可变版本。

目录 active 切换只影响后续默认选择，不修改历史任务冻结的 `catalog_version_id`。

### 显式业务字典

Normalize pipeline 支持 `dictionary_map`：

- exact / replace 两种显式模式；
- 字典 ID、版本号、SHA-256 和映射语义随任务/发布方案冻结；
- 后续新增字典版本不会改变历史任务；
- 字典真正参与字段评分和 retrieval text，不存在“只有配置页、运行时不消费”的装饰能力。

### 向量执行核心

- 可替换 `EmbeddingProvider`；
- 本地 ONNX Runtime + tokenizer；缺正式模型时显式不可用，不用测试向量冒充生产语义；
- 持久化 float16 Embedding Cache；
- Target 1-bit packed vector；Query signed 4-bit；int8 rerank sidecar；
- packed sign bits + Query bit planes + XOR/AND + uint8 popcount LUT 粗召回；
- mmap + blockwise TopK；
- STRICT/MAPPED scope postings；
- Target fingerprint / index reuse；
- scan/vector 自动路由；
- BUILDING/READY/FAILED 与执行阶段可观测。

当前 coarse kernel 是 portable NumPy/LUT。是否投入 native SIMD/POPCNT、HNSW、Block/Disk 等更复杂方案，只根据真实目标机器实测决定。

### Token-aware Embedding 与真实语料画像

- tokenizer 实际 token 长度；
- P50/P95/P99/P99.9/max；
- 128/192/256/512 截断率；
- `max_batch_size + token_budget` 双约束分桶；
- micro-batch / padding efficiency；
- Embedding Cache、Target 建库、Query 推理统一继承 token budget；
- Source/Target 真实 retrieval text 流式 bounded-reservoir 画像；
- 推荐 `max_length` 只提示，必须由用户显式采用。

### 质量与准确率验收

向量 benchmark 使用 float32 exact cosine reference 计算 Recall@K/Top1 hit，用于检测 BBQ/未来索引优化是否发生检索退化，并明确标记为**非业务准确率**。

完成任务可以上传独立 `supplement` 金标，输出：

- truth coverage；
- Top1 accuracy；
- 人工处理后的 final accuracy；
- human accuracy gain；
- automatic accuracy；
- review / unmatched / resolved rate；
- 正确集团码在持久化候选中的 Recall@K；
- 错例和正确候选排名。

验收结果持久化，不修改冻结任务结果。

### 账号、安全与权限

- SQLite 持久化账号；
- 密码使用 `scrypt + random salt`，不存明文；
- `admin / operator / reviewer / viewer` 四级角色；
- 权限由服务端 RBAC 执行，不依赖前端隐藏按钮；
- 新用户/管理员重置后强制改密；
- 首次安装 bootstrap `admin` 也必须首次登录改密；
- 新密码不能与当前密码相同；
- 修改角色、停用、重置密码会使旧会话失效；
- 最后一个启用管理员不能被停用或降权。

### 离线交付与事务化升级

目标环境：银河麒麟 Linux V10、无 Docker、无公网依赖。

交付链：

```text
目标架构 Python Runtime + wheelhouse
  → scripts/prepare_runtime.py
  → runtime + runtime-manifest

Vue source
  → npm run build
  → web/dist

runtime + backend source + web/dist
  → scripts/build_release.py
  → release + release-manifest

release + 正式 ONNX 模型 + wheelhouse
  → scripts/build_offline_bundle.py
  → offline bundle + offline-manifest
  → installer/verify_offline_bundle.py
  → installer/install.sh
```

主要防护：

- Runtime → Release → Offline 三层 SHA-256 / 版本 / CPU 架构完整性链；
- 离线 wheel 架构检查；
- 不允许逃逸 symlink；
- `material-matcher doctor`；
- 新版本复制和 doctor 时旧服务继续在线；
- 仅在切换阶段进入短停机窗口；
- `current/previous` 版本化链接；
- systemd readiness 失败自动恢复旧 release/model；
- 升级不递归扫描/chown 海量历史索引和结果。

详见 [`docs/OFFLINE_RELEASE_GUIDE.md`](docs/OFFLINE_RELEASE_GUIDE.md)。正式上线请以 [`agent.md`](agent.md) 为最新执行契约。

### 生产验收门禁

CLI：

```bash
material-matcher acceptance
material-matcher acceptance --require-production-ready
```

门禁状态：

- `PASS`：当前环境存在具体证据，并达到显式批准阈值；
- `BLOCKED`：代码路径存在，但缺正式模型、金标、Kylin V10、正式介质、百万级任务或批准阈值；
- `FAIL`：实际配置/环境有缺陷，或真实测量低于批准阈值。

项目验收阈值必须显式提供，不使用内置“拍脑袋”标准：

```text
MATERIAL_MATCHER_ACCEPTANCE_MIN_TRUTH_ROWS
MATERIAL_MATCHER_ACCEPTANCE_MIN_TRUTH_COVERAGE
MATERIAL_MATCHER_ACCEPTANCE_MIN_TOP1_ACCURACY
MATERIAL_MATCHER_ACCEPTANCE_MIN_FINAL_ACCURACY
MATERIAL_MATCHER_ACCEPTANCE_MAX_REVIEW_RATE
MATERIAL_MATCHER_ACCEPTANCE_MAX_SCALE_HOURS
```

其中百万级门禁只接受真实 `COMPLETED` 任务的证据：`Source >= 100000`、实际索引 `Target rows >= 1000000`、任务起止时间完整，并满足批准的最大端到端小时数。Synthetic benchmark 无法满足此门禁。

## 目录约定

正式安装：

```text
/opt/material_matcher
/etc/material_matcher
/var/lib/material_matcher
/var/log/material_matcher
```

端口从 `12000–29999` 自动选择可用值。首次安装 bootstrap admin 密码保存在：

```text
/etc/material_matcher/secret/admin_password.env
```

该文件为 `root:root 0600`；bootstrap 密码仅用于首次登录，之后必须通过系统强制流程轮换。

## 开发与 CI

Backend：

```bash
python3 -m pip install -e '.[dev]'
pytest -q
python3 -m compileall -q src
bash -n installer/install.sh
python3 scripts/check_repo_files.py
```

Frontend：

```bash
cd web
npm install --no-audit --no-fund
npm run build
```

仓库禁止提交模型、wheel、Runtime、数据库、索引、结果、cache、venv、`node_modules` 和 `dist`。

## 1.0 的完成边界

**仓库内代码侧目标已经收口到 1.0。** 仍需要运维/业务在真实环境完成的不是“再开发几个按钮”，而是生产证据：

- 正式 `bge-base-zh-v1.5` ONNX/tokenizer/runtime/wheelhouse；
- 银河麒麟 Linux V10 实机；
- 项目批准的业务准确率/Review率/最大耗时门槛；
- 独立真实业务金标；
- >=1M Target + >=100K Source 正式任务；
- 实际 CPU/内存/磁盘/索引复用和回滚验证。

所以不要用“代码版本 1.0.0”代替“生产已验收”。生产完成的唯一机器可判定条件是：

```text
material-matcher acceptance --require-production-ready
exit code = 0
production_ready = true
blocked = 0
fail = 0
```

完整部署与上线步骤见 [`agent.md`](agent.md)。

## 主要文档

- [`agent.md`](agent.md)：运维 Agent 生产上线执行契约
- [`docs/OFFLINE_RELEASE_GUIDE.md`](docs/OFFLINE_RELEASE_GUIDE.md)：离线 Runtime/Release/Bundle 交付机制
- [`docs/DEVELOPMENT_DESIGN.md`](docs/DEVELOPMENT_DESIGN.md)：开发设计
- [`docs/API_UI_DEPLOYMENT_CONTRACT.md`](docs/API_UI_DEPLOYMENT_CONTRACT.md)：API/UI/部署契约
- [`docs/EMBEDDING_AND_PERFORMANCE_DESIGN.md`](docs/EMBEDDING_AND_PERFORMANCE_DESIGN.md)：Embedding 与性能设计
- [`docs/VECTOR_INDEX_DESIGN.md`](docs/VECTOR_INDEX_DESIGN.md)：向量索引设计
- [`docs/CONFIGURABLE_PROCESSING_DESIGN.md`](docs/CONFIGURABLE_PROCESSING_DESIGN.md)：显式数据处理流水线
- [`docs/OPERATION_UI_DESIGN.md`](docs/OPERATION_UI_DESIGN.md)：业务操作 UI
- [`docs/TASK_FLOW_V25_SUPPLEMENT.md`](docs/TASK_FLOW_V25_SUPPLEMENT.md)：五步主流程
