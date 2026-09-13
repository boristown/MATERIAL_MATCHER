# 物料集团码匹配引擎

面向集团物料编码统一场景的批量相似度匹配平台。

项目目标是支持不同客户、不同数据格式、不同字段结构和不同匹配策略，通过业务配置完成大规模物料匹配，并输出可解释、可审计的候选及最终集团码结果。

当前首个落地场景为 13 所集团物料编码匹配，但底层架构不绑定单一客户、单一 Excel 格式、单一 SAP 表结构或单一物料类别。

## 核心原则

- 换客户、换表头、换字段、换权重、换阈值、换物料类别，不修改底层程序。
- 物料类别和各类别的匹配规则属于业务配置，不作为底层固定枚举。
- 普通业务用户通过图形化向导配置，不直接接触技术配置文件。
- 字段重要程度统一使用 `0～100` 数字权重，并实时显示系统归一化后的实际占比。
- 采用 B/S 架构，目标服务器为银河麒麟 Linux V10，无 Docker 也可完全离线一键安装。
- 集团侧百万级数据优先使用单比特向量压缩进行高速候选召回，再结合字段规则进行精排。
- 第一阶段默认 Embedding 采用 `BAAI/bge-base-zh-v1.5`，但通过 Provider 可替换；模型、处理流水线和集团目录不变时必须复用 Target 向量与索引。
- CPU-only 参考环境下，100 万集团物料首次建库 + 10 万客户物料完整匹配的产品目标为数小时级（参考 2～4 小时），实际以现场自动 Benchmark 为准。

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
- [Embedding 模型与批量性能设计](docs/EMBEDDING_AND_PERFORMANCE_DESIGN.md)
- [单比特向量索引与高速批量匹配设计](docs/VECTOR_INDEX_DESIGN.md)
- [开发实施强制规范](docs/IMPLEMENTATION_CONTRACT.md)
- [v2.4 Embedding 与性能实施补充](docs/IMPLEMENTATION_CONTRACT_V24_SUPPLEMENT.md)
- [核心函数、接口、UI、部署与验收规范](docs/API_UI_DEPLOYMENT_CONTRACT.md)
- [业务操作界面专项设计](docs/OPERATION_UI_DESIGN.md)
- [项目背景与设计约束](docs/PROJECT_BACKGROUND.md)
- [零代码客户适配设计](docs/ZERO_CODE_ADAPTATION_DESIGN.md)
- [插件化架构设计](docs/PLUGIN_ARCHITECTURE.md)
- [非技术用户配置体验设计](docs/NON_TECHNICAL_CONFIGURATION_DESIGN.md)
- [麒麟 V10 一键部署、运行与 B/S 界面设计](docs/DEPLOYMENT_AND_UI_DESIGN.md)
- [13 所物料类别业务配置说明](docs/customers/13_institute_material_type_config.md)
- [13 所已验证字段映射草案](docs/customers/13_institute_z001_z006_mapping.md)