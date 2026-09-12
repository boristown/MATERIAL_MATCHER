# MATERIAL_MATCHER

通用物料/实体批量匹配引擎。

项目目标是支持不同客户、不同数据格式、不同字段结构和不同匹配策略，通过配置化与可插拔组件完成大规模数据匹配，并输出可解释、可审计的候选及决策结果。

当前首个落地场景为 13 所集团物料编码匹配，但核心架构不绑定单一客户、Excel 格式、SAP 表结构或单一相似度算法。

## 当前阶段

项目目前处于**设计先行并进入 MVP 实现**阶段。设计约束继续保持不变：普通客户差异必须通过 profile / dictionary / mapping / catalog 配置完成，新增客户不得要求修改核心程序。

这里的“普通客户差异”包括表头/列名、字段数量、字段组合关系、多数据源 Join、Target Catalog 路由、字段权重、匹配算法选择、阈值/敏感性、物料组策略、同义词、Top-N 和输出列等。只有平台从未支持过的新协议、新数据源驱动或全新算法类型，才允许以通用插件形式扩展代码；插件加入后应可由任意客户 Profile 复用。

部署侧采用统一产品形态：银河麒麟 Linux V10、无 Docker、完全离线一键安装、统一逻辑目录、自动选择大容量数据盘和高位空闲端口、systemd 自启动，以及基于 Vue 3 的 B/S 管理界面。

配置体验侧要求：**普通业务用户默认不接触 YAML、插件 ID、Join、Rule Set 等技术概念**。默认采用向导、自动识别、拖拽映射、重要程度滑块、匹配严格程度滑块、试跑预览和版本回滚；底层技术配置仅在高级/专家模式显示。

## 已开始实现的 MVP 能力

当前实现分支已包含：

- Python/FastAPI B/S 服务骨架；
- 固定 `admin` 登录与会话令牌；
- `/api/health`、`/api/health/ready` 健康检查；
- Profile YAML 加载、结构校验和 SHA-256；
- 通用 `PluginRegistry`；
- Excel 样表自动识别：Sheet、表头行、字段语义、样例值、空值候选、前导零风险；
- Vue 3 + TypeScript + Element Plus 管理端；
- 可实际上传 Excel 样表并查看自动识别结果的配置向导第一步；
- 银河麒麟 V10 一键安装脚本骨架：固定目录、最大数据盘探测、高位空闲端口、随机 10 位 admin 密码、systemd；
- 后端单元测试、前端构建检查和安装脚本语法检查 CI。

下一阶段优先完成：集团码样表上传、字段确认/拖拽映射、权重滑块、严格度/阈值预览、配置发布与版本管理，然后进入 DatasetGraph/Join、Catalog 路由和 BBQ 索引实现。

## 本地开发

后端：

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[dev]'
export MATERIAL_MATCHER_ADMIN_PASSWORD=Ab3dEf7Gh9
material-matcher serve
```

前端：

```bash
cd web
npm install
npm run dev
```

默认开发后端端口为 `17843`，Vite 会将 `/api` 代理到该端口。

运行测试：

```bash
pytest -q
bash -n installer/install.sh
```

构建前端：

```bash
cd web
npm run build
```

正式麒麟离线包不会依赖现场 Node.js 或在线 `pip install`；开发完成后将把 Python runtime、wheelhouse、native BBQ 组件和 `web/dist` 一并打包。

## 文档

- [项目背景与设计约束](docs/PROJECT_BACKGROUND.md)
- [通用匹配引擎开发设计书](docs/DEVELOPMENT_DESIGN.md)
- [零代码客户适配设计](docs/ZERO_CODE_ADAPTATION_DESIGN.md)
- [插件化架构与零代码客户适配契约](docs/PLUGIN_ARCHITECTURE.md)
- [非技术用户配置体验设计](docs/NON_TECHNICAL_CONFIGURATION_DESIGN.md)
- [向量数据库与 BBQ 高速批量匹配设计](docs/VECTOR_INDEX_DESIGN.md)
- [麒麟 V10 一键部署、运行与 B/S UI 设计](docs/DEPLOYMENT_AND_UI_DESIGN.md)
- [通用客户 Profile 示例](config/examples/generic_customer.yaml)
- [13 所 Z001 / Z006 字段映射草案](docs/customers/13_institute_z001_z006_mapping.md)
- [13 所 Z001 / Z006 Profile 示例](config/examples/institute_13_z001_z006.yaml)
