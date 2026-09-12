# MATERIAL_MATCHER

通用物料/实体批量匹配引擎。

项目目标是支持不同客户、不同数据格式、不同字段结构和不同匹配策略，通过配置化与可插拔组件完成大规模数据匹配，并输出可解释、可审计的候选及决策结果。

当前首个落地场景为 13 所集团物料编码匹配，但核心架构不绑定单一客户、Excel 格式、SAP 表结构或单一相似度算法。

## 当前阶段

项目目前处于**设计先行**阶段，优先完善业务背景、核心抽象、配置体系、算法边界、评测方案与麒麟 Linux V10 离线部署方案，再进入核心代码实现。

其中一项强制设计目标是：**普通客户差异必须通过 profile / dictionary / mapping / catalog 配置完成，新增客户不得要求修改核心程序。**

这里的“普通客户差异”包括表头/列名、字段数量、字段组合关系、多数据源 Join、Target Catalog 路由、字段权重、匹配算法选择、阈值/敏感性、物料组策略、同义词、Top-N 和输出列等。只有平台从未支持过的新协议、新数据源驱动或全新算法类型，才允许以通用插件形式扩展代码；插件加入后应可由任意客户 Profile 复用。

部署侧同样采用统一产品形态：银河麒麟 Linux V10、无 Docker、完全离线一键安装、统一逻辑目录、自动选择大容量数据盘和高位空闲端口、systemd 自启动，以及基于 Vue 3 的 B/S 管理界面。

## 文档

- [项目背景与设计约束](docs/PROJECT_BACKGROUND.md)
- [通用匹配引擎开发设计书](docs/DEVELOPMENT_DESIGN.md)
- [零代码客户适配设计](docs/ZERO_CODE_ADAPTATION_DESIGN.md)
- [插件化架构与零代码客户适配契约](docs/PLUGIN_ARCHITECTURE.md)
- [向量数据库与 BBQ 高速批量匹配设计](docs/VECTOR_INDEX_DESIGN.md)
- [麒麟 V10 一键部署、运行与 B/S UI 设计](docs/DEPLOYMENT_AND_UI_DESIGN.md)
- [通用客户 Profile 示例](config/examples/generic_customer.yaml)
- [13 所 Z001 / Z006 字段映射草案](docs/customers/13_institute_z001_z006_mapping.md)
- [13 所 Z001 / Z006 Profile 示例](config/examples/institute_13_z001_z006.yaml)
