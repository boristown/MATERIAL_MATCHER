# 银河麒麟 V10 最终离线安装介质制作与验收总规范

> **文档性质：最终安装介质总规格。**
>
> 本文件用于驱动安装包制作和最终验收，不作为客户具体安装步骤。客户真正操作时，只阅读与其选择相对应的那一份安装手册。
>
> 当前交付策略：**两种独立安装方式同时交付，Docker 方式优先推荐，非 Docker / Native Source 方式作为完全独立的备用方案。两种方式二选一，绝对不是先后安装两遍。**

---

## 1. 最终介质必须提供两条完全独立的安装路径

### A. Docker 离线安装（老板/客户优先）

客户即使没有预装 Docker，也必须能够离线完成：

```text
安装介质
→ 自动安装/确认 Docker Engine
→ 自动安装/确认 Docker Compose
→ 离线导入 MATERIAL_MATCHER 镜像
→ 创建持久化目录
→ Compose 启动
→ health/ready
→ 导入默认业务 seed
→ 业务 smoke
```

对应客户手册：

`docs/KYLIN_V10_DOCKER_OFFLINE_INSTALL.md`

### B. 非 Docker / Native Source 离线安装

完全不依赖 Docker，使用自包含 Python Runtime、源码可见 release 和 systemd。

对应客户手册：

`docs/KYLIN_V10_NATIVE_OFFLINE_INSTALL.md`

### 重要

- 两种方式都必须 CLI-first；
- 两种方式都必须完全离线；
- 两种方式都必须能由非原厂人员独立安装；
- 两种方式都必须保护相同的数据；
- 两种方式都必须包含 6 个默认方案和默认同义词；
- 两种方式各自独立验收；
- 客户根据现场策略选择其中一种；
- 手册和介质不得出现“先装 Native 再装 Docker”或相反的暗示。

---

## 2. 最终交付介质根目录

建议最终 U 盘/离线目录结构：

```text
MATERIAL_MATCHER-最终离线交付介质-<version>/
├── 00-请先阅读/
│   └── README-请选择一种安装方式.txt
├── 01-Docker方式/
│   ├── 启动Docker安装.sh
│   ├── 安装手册-Docker方式.md
│   ├── docker/
│   │   ├── engine/
│   │   ├── compose/
│   │   └── licenses/
│   ├── images/
│   │   └── material-matcher-<version>.tar
│   ├── compose/
│   ├── source/
│   ├── seed/
│   ├── smoke/
│   ├── tools/
│   ├── BUILD_INFO.txt
│   └── SHA256SUMS
├── 02-非Docker方式/
│   ├── 启动本地安装.sh
│   ├── 安装手册-非Docker方式.md
│   ├── bootstrap/
│   ├── release/
│   ├── wheelhouse/
│   ├── models/
│   ├── seed/
│   ├── smoke/
│   ├── tools/
│   ├── BUILD_INFO.txt
│   └── SHA256SUMS
├── 客户端浏览器-Win7/
│   ├── README-浏览器选择.txt
│   ├── Firefox-ESR-115.41.0-Win7-x64.exe
│   ├── Chrome-109.0.5414.120-Win7-x64.exe
│   ├── SHA256SUMS.txt
│   └── LICENSES-AND-SOURCES.txt
└── SHA256SUMS-整个交付介质.txt
```

根目录 README 必须明确：

> Docker 方式和非 Docker 方式是两种替代方案，只选择一种安装。老板/客户没有其它限制时优先使用 Docker 方式。

---

## 3. Docker 方式是当前优先推荐方案

原因是运行边界更清晰、依赖隔离更明确、升级/回滚更容易标准化。

但客户现场可能完全没有 Docker，因此 **Docker 安装介质自身必须携带与银河麒麟 V10、目标 CPU 架构匹配的 Docker Engine 与 Docker Compose 离线组件。**

普通安装人员不得自行：

- 上网下载 Docker；
- 配置 Docker 仓库；
- docker pull；
- docker build；
- 手工安装 Compose；
- 手写 compose.yaml。

安装器必须自动完成或清晰提示。

如果客户已有兼容 Docker：

- 优先检测并复用；
- 不覆盖客户已有容器/镜像/网络/volume；
- 不运行全局 prune；
- 不擅自修改与本系统无关的 daemon 配置。

---

## 4. Docker 介质必须具备的资产

至少包含：

- Docker Engine 离线安装组件；
- Docker Compose v2 离线组件；
- MATERIAL_MATCHER 正式 image tar；
- compose.yaml；
- 源码副本；
- 6 个方案 seed；
- 同义词 seed；
- smoke 数据；
- 维护工具；
- manifest / SHA256；
- 第三方许可证与来源记录。

Docker/Compose 的具体版本必须在最终构建时冻结，并记录：

- 版本；
- CPU 架构；
- Kylin V10 兼容性实测；
- 原始来源；
- SHA256；
- 许可证/再分发说明。

不能只在文档写“需要 Docker”，却把 Docker 的安装留给客户。

---

## 5. Native 方式必须继续完整保留

非 Docker 方式不是残缺 fallback。

它必须独立包含：

- installer bootstrap runtime；
- 正式 Python Runtime；
- wheelhouse；
- embedding 模型；
- production web dist；
- Python/Vue 源码；
- systemd 安装链；
- upgrade / rollback；
- backup / restore；
- 6 个方案 seed；
- 同义词 seed。

客户明确禁止 Docker 时，应当可以只拿 `02-非Docker方式/` 完成部署。

---

## 6. 两种方式共享的数据与业务合同

无论 Docker 还是 Native：

- `/etc/material_matcher`：配置；
- `/var/lib/material_matcher`：数据逻辑入口；
- `/var/log/material_matcher`：日志；
- storage.env / 等价配置必须唯一指向真实数据目录；
- 不允许双 metadata DB；
- 不允许升级清空数据；
- 不允许重置 admin；
- 不允许覆盖客户自定义方案/同义词；
- 失败时必须可回滚。

Docker 方式必须使用宿主机 bind mount，不能把唯一业务数据库留在容器层或匿名 volume。

---

## 7. 默认业务 seed

两种方式首次安装后都必须自动存在：

- A001 元器件；
- A002 标准紧固件；
- A003 金属材料；
- A005 非金属材料；
- A006 复合材料；
- A007 物资类其他（跨类目）；
- 当前正式同义词/归一化配置。

要求：

- seed 纳入版本控制；
- 构建来源可追溯；
- 首次导入幂等；
- 重复安装不重复；
- 升级不覆盖客户修改；
- 不携带测试账号、历史任务、客户真实 Excel。

---

## 8. Win7 客户端浏览器工具包也是正式介质组成部分

现场访问终端可能是 Windows 7，而且现有浏览器可能过旧。因此交付介质必须额外提供一个独立的 Win7 浏览器离线目录。

### 首选：Firefox ESR 115.41.0

作为当前 Win7 的主要推荐浏览器。

### 备用：Chrome 109.0.5414.120

Chrome 109 是 Win7 最后支持主版本。由于已经停止持续安全更新，只作为隔离内网兼容备用，不作为通用公网浏览器推荐。

浏览器目录与服务器安装目录独立：

- 安装服务器时不强制装浏览器；
- 客户 Win7 PC 访问异常时再安装；
- Firefox/Chrome 各准备一份正式离线安装程序；
- 默认本次交付按 Win7 x64；
- 若客户存在 Win7 x86，另行准备对应 x86 包。

浏览器二进制必须：

- 来自官方/企业官方来源；
- 不从第三方下载站取得；
- 不修改原安装包；
- 记录版本、来源、获取日期；
- 生成 SHA256；
- 保留许可证/再分发说明；
- 纳入最终介质 manifest。

---

## 9. Win7 浏览器验收

交付前至少执行：

### Firefox ESR 115.41.0

在 Win7 x64：

- 离线安装；
- 打开登录页；
- 登录；
- STEP1～STEP4 页面；
- Excel 上传；
- Top5/弹窗/筛选等核心交互；
- Excel 下载。

### Chrome 109

执行同样的基础 smoke。

如出现差异：

README 明确 Firefox 为首选、Chrome 为备用。

---

## 10. Docker clean-room 验收

必须在**没有 Docker**的干净银河麒麟 V10 环境：

1. 断网；
2. 仅复制 `01-Docker方式/`；
3. 运行 `./启动Docker安装.sh`；
4. 离线安装 Docker Engine；
5. 离线安装 Compose；
6. 导入应用 image tar；
7. 启动 Compose；
8. health/ready；
9. 6 方案 + 同义词 seed；
10. STEP1～STEP4 smoke。

还必须验证：

- 已有兼容 Docker 的现场；
- 端口冲突；
- 介质损坏；
- 重复安装；
- upgrade；
- rollback；
- backup/restore；
- seed 幂等；
- 删除/重建应用容器后数据仍存在。

如果需要联网下载 Docker 或手工补依赖，FAIL。

---

## 11. Native clean-room 验收

必须在干净银河麒麟 V10：

1. 断网；
2. 不预装项目 Python/Node；
3. 仅复制 `02-非Docker方式/`；
4. 运行 `./启动本地安装.sh`；
5. 完成 systemd 安装；
6. health/ready；
7. 6 方案 + 同义词 seed；
8. STEP1～STEP4 smoke；
9. reboot 后自动启动。

并验证升级、rollback、backup/restore、双 DB 阻断。

---

## 12. 两套方式必须分别产生 Evidence

最终不能只验证其中一套却声称“两种均支持”。

至少输出：

```text
test-results/final-installer/docker/<日期>/
test-results/final-installer/native/<日期>/
test-results/final-installer/win7-browser/<日期>/
```

分别记录：

- PASS / PARTIAL / BLOCKED；
- 软件版本；
- main commit；
- 介质 SHA256；
- Kylin V10 版本；
- CPU；
- Docker/Compose 或 Python Runtime 版本；
- 是否断网；
- 首次安装；
- upgrade；
- rollback；
- backup/restore；
- seed；
- 业务 smoke；
- 发现 Bug 与修复 PR。

---

## 13. 最终 Definition of Done

只有以下同时满足才允许称为“完整最终安装介质”：

- [ ] Docker 客户手册独立存在；
- [ ] Native 客户手册独立存在；
- [ ] 根目录明确“两种方式二选一”；
- [ ] Docker 安装介质自带 Docker Engine 离线组件；
- [ ] Docker 安装介质自带 Compose；
- [ ] Docker image tar 完整；
- [ ] Native 自包含 Runtime 完整；
- [ ] 两种方式均完全离线；
- [ ] 两种方式均 CLI-first；
- [ ] 两种方式均预置 6 个方案；
- [ ] 两种方式均预置同义词；
- [ ] Docker clean-room PASS；
- [ ] Native clean-room PASS；
- [ ] upgrade / rollback / backup restore 均通过；
- [ ] Win7 Firefox 离线包已归档并 smoke PASS；
- [ ] Win7 Chrome 离线包已归档并 smoke PASS；
- [ ] 浏览器来源/许可证/SHA256 已记录；
- [ ] 最终整个介质 SHA256 已归档。

---

## 14. 给安装包制作 Agent 的最终要求

> **最终不是做一个“同时混合 Docker 和 Native 的安装程序”，而是制作同一交付介质中的两个独立安装产品。客户只选择一种。Docker 是当前优先推荐路径，并且必须自带 Docker Engine + Compose；Native 是不依赖 Docker 的完整替代路径。介质还必须独立携带 Win7 推荐 Firefox ESR 和 Chrome 兼容包，保证现场终端浏览器过旧时仍可离线解决。**
