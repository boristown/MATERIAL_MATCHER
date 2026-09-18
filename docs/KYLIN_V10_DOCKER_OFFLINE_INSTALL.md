# 银河麒麟 V10 离线安装手册（Docker 方式）

> **适用场景：老板/客户优先选择 Docker 隔离部署时使用。**
>
> 本手册是一条完整、独立的安装路径。**只按本手册安装即可，不需要再执行“非 Docker 安装手册”。**
>
> 目标：客户现场即使没有预装 Docker，也能在完全离线的银河麒麟 V10 服务器上，通过一个命令行入口完成 Docker Engine、Docker Compose、本系统镜像、业务种子数据和服务的安装。

---

## 1. 安装完成后会得到什么

安装完成后：

- MATERIAL_MATCHER 运行在 Docker 容器中；
- 客户数据、配置、日志保存在宿主机持久化目录；
- 容器删除/重建不会删除业务数据；
- 默认包含 6 个正式匹配方案：
  - A001 元器件
  - A002 标准紧固件
  - A003 金属材料
  - A005 非金属材料
  - A006 复合材料
  - A007 物资类其他（跨类目）
- 默认包含经过验证的同义词/归一化配置；
- 同义词支持批量勾选、批量删除，并继续通过版本机制保存；
- 系统可以完全断网运行。

---

## 2. 客户服务器前提

安装人员只需要确认：

- 操作系统：银河麒麟 V10；
- CPU 架构与安装介质一致；
- 具有 root 或 sudo 管理权限；
- 有足够磁盘空间；
- 可以在终端执行命令；
- 安装期间无需访问公网。

**客户现场不要求预装：**

- Docker；
- Docker Compose；
- Python；
- Node.js；
- npm；
- Git；
- MATERIAL_MATCHER 任何依赖。

这些必须由离线安装介质自行提供。

---

## 3. Docker 安装介质必须包含

Docker 方式交付目录至少包含：

```text
MATERIAL_MATCHER-Docker-KylinV10-<version>-<arch>/
├── 启动Docker安装.sh
├── README-请先阅读.txt
├── 安装手册-Docker方式.md
├── SHA256SUMS
├── BUILD_INFO.txt
├── docker/
│   ├── engine/                # 与目标麒麟/CPU匹配的离线 Docker Engine 安装包
│   ├── compose/               # Docker Compose v2 离线组件
│   └── licenses/              # 第三方组件许可证/声明
├── images/
│   └── material-matcher-<version>.tar
├── compose/
│   ├── compose.yaml
│   └── env.template
├── source/
│   ├── src/
│   ├── web/
│   ├── scripts/
│   └── pyproject.toml
├── seed/
│   ├── profiles/
│   └── synonyms/
├── smoke/
└── tools/
```

制作人员必须确保 Docker Engine / Compose 组件可以合法随介质分发，并与目标 CPU 架构及银河麒麟 V10 兼容。

---

## 4. 正式安装入口

将整个安装目录复制到服务器本地磁盘，不建议直接从 U 盘执行。

进入目录：

```bash
cd "/path/to/MATERIAL_MATCHER-Docker-KylinV10-<version>-<arch>"
./启动Docker安装.sh
```

正常流程不应要求安装人员再手工执行：

- yum/dnf 安装 Docker；
- docker pull；
- docker build；
- docker compose 手工拼参数；
- pip/npm；
- 修改 systemd unit；
- 手工导入数据库。

如必须执行这些手册外命令，视为安装包缺陷。

---

## 5. 安装向导必须自动完成

安装脚本必须依次完成：

1. 校验安装介质 SHA256 / manifest；
2. 校验银河麒麟 V10；
3. 校验 CPU 架构；
4. 检测 Docker 是否已存在；
5. 若无 Docker，则从介质离线安装 Docker Engine；
6. 若已有 Docker，则检查版本/架构/运行状态，兼容则复用，不得无理由覆盖；
7. 安装或确认 Docker Compose v2；
8. 启动并验证 Docker daemon；
9. 选择程序、配置、数据、日志目录；
10. 检查端口；
11. 离线导入应用镜像 tar；
12. 生成 compose 配置；
13. 创建宿主机持久化目录；
14. 启动容器；
15. 执行 health/readiness；
16. 首次安装时幂等导入 6 个方案和默认同义词；
17. 生成安装报告。

---

## 6. Docker 已存在时的处理

如果客户服务器已有 Docker：

- 先检测，不得直接覆盖；
- 版本和架构满足要求时优先复用；
- 不得删除客户已有 image/container/volume/network；
- 不得执行 `docker system prune -a`；
- 不得修改与本系统无关的 daemon 配置；
- 如发现版本不兼容，必须给出明确提示并停止或请求管理员确认。

本系统应使用独立的：

- compose project name；
- container name；
- network；
- bind mount 目录；

避免与客户其他容器冲突。

---

## 7. 数据必须放在宿主机

正式 Docker 方案必须使用宿主机 bind mount 保存：

- 配置；
- SQLite/metadata；
- uploads；
- indexes；
- results；
- evaluation history；
- logs；
- 必要的模型/缓存。

**禁止把 metadata DB 只放在匿名 Docker volume 或容器可写层。**

建议逻辑目录保持：

```text
/etc/material_matcher
/var/lib/material_matcher
/var/log/material_matcher
```

即使容器重建，数据仍然存在。

---

## 8. 端口与网络

默认端口建议：

```text
18080
```

若端口被占用：

- 安装向导必须明确提示；
- 建议可用端口；
- 用户确认后再继续。

安装成功后输出：

- 本机 URL；
- 局域网 URL；
- 实际服务端口。

Docker 方式不得默默开放额外管理端口。

---

## 9. 管理员密码

首次安装：

- 可由用户输入；
- 或安全自动生成；
- 终端输入时不明文回显；
- 自动生成密码只在成功输出中显示一次；
- 不得写入世界可读日志；
- 不得进入诊断包。

升级时不得重置已有管理员密码。

---

## 10. 默认业务数据

首次安装完成后必须自动存在：

- 6 个正式匹配方案；
- 当前正式同义词/归一化版本。

导入必须幂等：

- 第一次安装导入；
- 重复运行不重复生成；
- 升级不覆盖客户后续修改；
- 不导入测试账号、历史任务、真实客户 Excel。

---

## 11. 安装成功验收

Docker 方式只有以下全部通过才能判定安装成功：

- Docker daemon 正常；
- Compose v2 可用；
- MATERIAL_MATCHER 容器处于 healthy/running；
- `/api/health` 正常；
- `/api/health/ready` 正常；
- 浏览器可打开；
- admin 可登录；
- 关于页版本/commit 与安装包一致；
- 6 个默认方案存在；
- 默认同义词存在；
- STEP1 → STEP4 最小业务 smoke 成功；
- 最终 Excel 可以下载。

---

## 12. 升级

再次运行同一安装入口时，如检测到已有安装，应进入升级流程：

1. 记录现有版本；
2. 备份配置和 metadata；
3. 导入新镜像；
4. 保持宿主机数据目录不变；
5. 以新镜像启动；
6. readiness 通过后完成切换；
7. 失败则恢复前一镜像/compose 配置。

升级不得：

- 删除宿主机数据；
- 换一个新的 SQLite；
- 重置 admin；
- 覆盖客户修改后的方案/同义词；
- 清空历史任务。

---

## 13. 回滚

必须保留前一正式镜像标识和配置。

若新版本：

- health 失败；
- ready 失败；
- 启动失败；

安装器必须自动恢复上一版本，并验证旧版本恢复正常。

不能让普通用户手工输入复杂 Docker 命令修复。

---

## 14. 维护入口

介质/安装后应提供统一维护脚本，例如：

```bash
./维护工具-Docker.sh
```

至少提供：

- 查看状态；
- 启动；
- 停止；
- 重启；
- 查看日志；
- doctor；
- 备份；
- 恢复；
- 导出诊断包；
- 查看版本。

维护工具内部可以调用 Docker/Compose，但普通用户不需要记 Docker 命令。

---

## 15. Clean-room 验证要求

正式交付前必须在一台**没有预装 Docker**的干净银河麒麟 V10 环境完成：

- 完全断网；
- 只使用本介质；
- `./启动Docker安装.sh`；
- 自动安装 Docker Engine；
- 自动安装 Compose；
- 自动导入镜像；
- 启动系统；
- 完整业务 smoke。

还必须额外验证：

- 已安装兼容 Docker 的服务器：能够安全复用；
- 端口冲突；
- 损坏介质；
- 重复安装；
- 升级；
- readiness 失败自动回滚；
- backup/restore；
- seed 幂等；
- 容器删除并重建后业务数据仍存在。

**如果任何步骤需要访问公网或手工补 Docker 依赖，则验收失败。**

---

## 16. 最终 PASS 记录

最终 Evidence 必须记录：

- 软件版本；
- main commit；
- Docker Engine 版本；
- Docker Compose 版本；
- 镜像 tag/digest；
- 安装包文件名；
- SHA256；
- Kylin V10 版本；
- CPU 架构；
- 是否全程断网；
- clean install；
- 已有 Docker 兼容场景；
- upgrade；
- rollback；
- backup/restore；
- 6 方案 seed；
- 同义词 seed；
- STEP1～STEP4 smoke。

全部 PASS 后，Docker 方式才可以对客户交付。


---

## 17. 客户端 Win7 浏览器离线工具包

服务器安装完成后，客户可能使用 Windows 7 PC 访问系统。为避免现场浏览器版本过旧导致登录页、Vue 页面或现代 JavaScript/CSS 不兼容，正式安装介质必须附带一个**独立的 Win7 浏览器离线工具包**。

这不是服务器安装步骤，不要求在银河麒麟服务器上安装浏览器。浏览器安装包用于客户 Windows 7 终端，由现场人员按需安装。

最终介质建议包含：

```text
客户端浏览器-Win7/
├── README-浏览器选择.txt
├── Firefox-ESR-115.41.0-Win7-x64.exe
├── Chrome-109.0.5414.120-Win7-x64.exe
├── SHA256SUMS.txt
└── LICENSES-AND-SOURCES.txt
```

本次默认按 **Windows 7 64 位**准备一套 Firefox 和一套 Chrome。若客户现场存在 32 位 Windows 7，必须另外准备对应 x86 介质，不能把 x64 安装包视为已支持 32 位系统。

### 推荐顺序

**首选：Firefox ESR 115.41.0**

- Firefox ESR 115 是 Windows 7 / 8 / 8.1 的兼容分支；
- 115.41.0 为 2026-09-15 发布的 ESR 115 更新；
- 用作本系统 Win7 客户端的主要推荐浏览器。

**备用：Chrome 109.0.5414.120**

- Chrome 109 是 Google 官方最后支持 Windows 7 / 8.1 的主版本；
- Windows 最后一个 109 稳定更新为 109.0.5414.119/.120；
- 该版本已停止长期安全更新，只作为隔离内网环境的兼容兜底，不建议用于日常公网浏览。

### 安装包来源与合规

浏览器二进制不得从第三方软件下载站抓取。

必须：

- 使用厂商官方/企业官方下载来源；
- 保留原始文件名或在文档中记录原文件名；
- 记录版本、下载来源、获取日期；
- 生成 SHA256；
- 保留对应许可证/再分发说明；
- 不修改浏览器安装程序；
- 如组织无法确认某个浏览器安装包具备可再分发条件，则在最终对外交付前必须先解决授权/合规问题，不能用未知来源替代。

### Win7 浏览器验收

正式交付前至少在真实或等价 Win7 x64 环境分别验证：

Firefox ESR：

1. 离线安装成功；
2. 打开 MATERIAL_MATCHER 登录页；
3. 登录成功；
4. STEP1～STEP4 主要页面可打开；
5. 上传控件、下拉框、弹窗、下载 Excel 正常；
6. 无白屏、关键按钮消失或严重布局错位。

Chrome 109：

执行同样的基础兼容 smoke。

如果两个浏览器表现不同，README 必须明确：

- **推荐 Firefox ESR**
- Chrome 仅备用

浏览器包本身也必须进入最终介质 SHA256/manifest 归档。
