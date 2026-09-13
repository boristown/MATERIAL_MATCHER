# 物料集团码匹配引擎：银河麒麟 V10 部署与运行补充规范

> 文档版本：2.2  
> 日期：2026-09-13  
> 状态：Normative Supplement  
> 说明：本文只补充银河麒麟 Linux V10 的部署、安装、运行与运维约束。**本文不再定义 UI 菜单、页面层级或页面路由。** UI 唯一规范见 `OPERATION_UI_DESIGN.md` 与 `API_UI_DEPLOYMENT_CONTRACT.md` 第 44 章；安装开发契约见后者第 45 章。

## 1. 部署硬约束

服务端必须满足：

- 银河麒麟 Linux V10；
- 不依赖 Docker / Docker Compose / Kubernetes；
- 支持完全离线安装；
- 一键安装入口 `sudo ./install.sh`；
- 正式安装包携带 Python Runtime、Python 依赖、Native 依赖、Vue 已构建静态资源、匹配引擎、单比特向量召回能力和数据库迁移；
- 现场不得要求 `npm install`、公网 `pip install`、`git clone`、`docker pull` 或现场 gcc 编译；
- systemd 管理并开机自启；
- 所有客户使用完全相同的逻辑目录。

## 2. 固定逻辑目录

```text
/opt/material_matcher
/etc/material_matcher
/var/lib/material_matcher
/var/log/material_matcher
```

程序不得按客户名更换逻辑路径。

推荐子目录：

```text
/opt/material_matcher/current
/opt/material_matcher/releases

/etc/material_matcher/profiles
/etc/material_matcher/catalogs
/etc/material_matcher/mappings
/etc/material_matcher/dictionaries
/etc/material_matcher/templates
/etc/material_matcher/secret

/var/lib/material_matcher/datasets
/var/lib/material_matcher/indexes
/var/lib/material_matcher/models
/var/lib/material_matcher/uploads
/var/lib/material_matcher/results
/var/lib/material_matcher/jobs
/var/lib/material_matcher/tmp
```

## 3. 最大数据盘自动探测

安装器扫描可写本地持久化文件系统，按**可用空间**降序推荐数据盘。

默认排除：

- `/boot`、`/boot/efi`；
- tmpfs/devtmpfs/proc/sysfs/cgroup；
- overlay/squashfs；
- 只读挂载；
- 可移动临时介质。

无论真实数据盘是 `/data`、`/u01` 还是其他位置，应用始终访问 `/var/lib/material_matcher`。

允许通过受控软链接或 bind mount 将大数据目录映射到推荐磁盘。

实际物理位置记录在：

```text
/etc/material_matcher/storage.env
```

## 4. 自动端口

首次安装从：

```text
12000 ～ 29999
```

随机选择高位端口。

要求：

1. 使用安全随机源；
2. 最多随机尝试 200 次；
3. 必须实际 socket bind 验证端口可用；
4. 随机失败后允许顺序扫描；
5. 选定后写入 `/etc/material_matcher/server.env`；
6. 升级不得重新随机端口。

## 5. 固定管理员账号

系统不建设多用户体系。

```text
username = admin
```

首次安装生成随机 10 位字母数字密码，固定保存在：

```text
/etc/material_matcher/secret/admin_password.env
```

要求：

- `root:root`；
- 权限 `0600`；
- 密码不得写入前端静态资源或日志；
- 升级不得自动重置密码。

## 6. systemd

主服务固定：

```text
material_matcher.service
```

正式服务建议使用无登录 shell 的系统用户 `material_matcher` 运行，不长期使用 root 身份运行 Web 服务。

安装器必须执行：

```bash
systemctl daemon-reload
systemctl enable --now material_matcher.service
```

服务建议至少包含：

```text
Restart=on-failure
RestartSec=3
WorkingDirectory=/opt/material_matcher/current
EnvironmentFile=/etc/material_matcher/server.env
EnvironmentFile=/etc/material_matcher/storage.env
EnvironmentFile=/etc/material_matcher/secret/admin_password.env
```

## 7. 健康检查

必须提供：

```text
GET /api/health
GET /api/health/ready
```

安装成功必须以 `/api/health/ready` 通过为准。

ready 至少检查：

- 元数据库可读写；
- 数据目录可读写；
- 临时目录可写；
- 当前活动索引可加载（若存在）；
- 匹配引擎可初始化；
- 剩余磁盘空间高于最低保护阈值。

## 8. 单比特向量能力随包交付

客户不需要自行安装 Elasticsearch、Milvus 或 Docker 容器。

正式安装包自动交付：

- Target 1-bit 向量索引；
- Query 量化组件；
- 批量检索组件；
- 索引元数据；
- mmap/Flat/HNSW 等已正式实现的索引后端；
- CPU 能力检测与兼容后端。

Native 组件必须提供与目标 CPU 架构匹配的预编译版本，现场不得重新编译。

## 9. 临时文件

临时文件统一位于：

```text
/var/lib/material_matcher/tmp
```

每个临时对象必须登记：

- 来源任务；
- 类型；
- 创建时间；
- 最后访问时间；
- 大小；
- 是否正在使用；
- 是否允许删除；
- 保留时间。

清理接口只能接受任务、时间、类型等业务条件，不允许前端传任意绝对路径。

正式方案、正式集团码数据、正式索引、正式结果、模型和系统配置不得被临时清理功能删除。

## 10. 安装流程

```text
检查 root 权限
→ 检查麒麟版本与 CPU 架构
→ 检查安装包完整性
→ 探测最大可用数据盘
→ 创建固定逻辑目录
→ 安装自包含运行时
→ 安装后端程序
→ 安装 Vue 静态资源
→ 安装单比特向量召回组件
→ 选择空闲高位端口
→ 生成 admin 初始密码
→ 初始化/迁移元数据库
→ 注册 systemd
→ enable + start
→ readiness 健康检查
→ 输出访问地址和运维路径
```

`install.sh` 必须具备幂等性：已有安装时不得覆盖业务数据、端口和密码。

## 11. 升级、卸载和保护

升级必须保护：

```text
/etc/material_matcher
/var/lib/material_matcher/datasets
/var/lib/material_matcher/indexes
/var/lib/material_matcher/results
```

升级流程应支持失败回滚到 previous release。

普通卸载默认只移除程序、运行时和 systemd，不删除业务数据。

只有显式 `--purge` 并二次确认后才允许删除业务数据。

## 12. UI 归属说明

本文件不再维护任何 Dashboard、结果中心、人工复核菜单、配置向导页面或临时文件页面布局。

开发人员不得从本文件历史版本恢复以下旧结构：

```text
首页 / Dashboard
结果中心
人工复核独立菜单
临时文件独立菜单
Catalog 独立一级菜单
```

正式前端只能遵循：

- `OPERATION_UI_DESIGN.md`：业务页面结构；
- `API_UI_DEPLOYMENT_CONTRACT.md` 第 44 章：开发级路由、组件、交互和验收红线。

这样部署规范与 UI 规范职责分离，避免同一个功能在多份文档中出现不同版本。
