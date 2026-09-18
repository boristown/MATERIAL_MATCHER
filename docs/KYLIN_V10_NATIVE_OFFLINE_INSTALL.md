# 银河麒麟 V10 离线安装手册（非 Docker / Native Source 方式）

> **适用场景：客户不允许 Docker，或现场明确要求直接运行源码服务时使用。**
>
> 本手册是一条完整、独立的安装路径。**只按本手册安装即可，不需要执行“Docker 安装手册”。**
>
> 目标：在完全离线的银河麒麟 V10 服务器上，不依赖 Docker，通过自包含 Runtime + 源码可见方式完成安装。

---

## 1. 安装完成后会得到什么

安装完成后：

- MATERIAL_MATCHER 直接以 systemd 服务运行；
- Python 正式 Runtime 由安装介质提供；
- 不依赖系统预装 Python/Node/npm；
- Python/Vue 源码在安装目录中可查看；
- 客户数据、配置、日志位于固定宿主机目录；
- 默认包含 6 个正式匹配方案；
- 默认包含经过验证的同义词/归一化配置；
- 同义词支持批量勾选、批量删除；
- 完全断网可运行。

---

## 2. 客户服务器前提

只要求：

- 银河麒麟 V10；
- CPU 架构与介质一致；
- root 或 sudo 管理权限；
- systemd 可用；
- 足够磁盘空间；
- 可使用终端。

**不要求预装：**

- Docker；
- Python 应用环境；
- pip；
- Node.js；
- npm；
- Git。

---

## 3. Native 安装介质必须包含

```text
MATERIAL_MATCHER-Native-KylinV10-<version>-<arch>/
├── 启动本地安装.sh
├── README-请先阅读.txt
├── 安装手册-非Docker方式.md
├── SHA256SUMS
├── BUILD_INFO.txt
├── bootstrap/
├── release/
│   ├── runtime/
│   ├── web-dist/
│   ├── source/
│   └── tools/
├── wheelhouse/
├── models/
├── seed/
│   ├── profiles/
│   └── synonyms/
├── smoke/
└── tools/
```

安装介质必须自带：

- installer bootstrap runtime；
- 正式 Python Runtime；
- wheelhouse；
- embedding 模型；
- production web dist；
- Python/Vue 源码；
- 6 方案 seed；
- 同义词 seed。

---

## 4. 正式安装入口

复制整个安装目录到服务器本地磁盘。

执行：

```bash
cd "/path/to/MATERIAL_MATCHER-Native-KylinV10-<version>-<arch>"
./启动本地安装.sh
```

普通安装人员不直接执行底层 install.sh，也不手工设置 Python 环境变量。

---

## 5. 安装向导自动完成

必须自动执行：

1. 校验介质；
2. 校验银河麒麟 V10；
3. 校验 CPU；
4. 检查 systemd；
5. 检查磁盘；
6. 检查端口；
7. 创建系统用户；
8. 创建程序/配置/数据/日志目录；
9. 安装 bootstrap / release runtime；
10. 安装应用 release；
11. 安装模型；
12. 写入唯一 storage.env；
13. 配置 systemd；
14. 设置权限；
15. 首次创建/保存 admin；
16. 启动服务；
17. readiness；
18. 幂等导入 6 个方案和默认同义词；
19. 输出安装报告。

---

## 6. 推荐目录

```text
/opt/material_matcher
/etc/material_matcher
/var/lib/material_matcher
/var/log/material_matcher
```

`/etc/material_matcher/storage.env` 是唯一数据目录来源。

不得因为升级或重装重新猜数据盘。

---

## 7. 数据保护

不得：

- 自动切换已有数据目录；
- 创建第二份 metadata DB 后继续；
- 清历史任务；
- 清 uploads；
- 清 indexes；
- 清 results；
- 重置 admin；
- 覆盖客户方案和同义词。

发现多份 metadata DB 时必须停止并提示，不得自动选择。

---

## 8. 管理员密码

首次安装可以：

- 用户输入；
- 或安全自动生成。

要求：

- 输入不回显；
- 自动密码只在终端成功信息中显示一次；
- 日志不保存明文；
- 密码文件仅 root 可读；
- 诊断包不能包含密码。

升级不得重置密码。

---

## 9. 默认业务数据

首次安装后必须存在：

- A001 元器件；
- A002 标准紧固件；
- A003 金属材料；
- A005 非金属材料；
- A006 复合材料；
- A007 物资类其他（跨类目）；
- 默认同义词/归一化版本。

seed 导入必须幂等且可追溯，不得带入测试任务、测试账号和真实客户文件。

---

## 10. 安装成功验收

必须全部通过：

- systemd 服务 active；
- 开机自启 enabled；
- `/api/health` 成功；
- `/api/health/ready` ready；
- 浏览器打开；
- admin 登录；
- 关于页版本/commit 正确；
- 6 个默认方案存在；
- 默认同义词存在；
- STEP1 → STEP4 smoke 成功；
- 最终结果 Excel 可下载。

---

## 11. 升级

检测到旧版本后：

1. 记录旧版本；
2. 备份 metadata 和配置；
3. 准备新 release/model；
4. 旧服务仍运行时 doctor；
5. doctor 通过；
6. 短暂停服务；
7. current/previous 原子切换；
8. 启动新版本；
9. readiness；
10. 完成。

升级不能改变 storage.env 指向。

---

## 12. 自动回滚

若新版本启动/readiness 失败：

- 停止新服务；
- current 恢复 previous；
- model 恢复 previous；
- 恢复必要配置；
- 启动旧服务；
- 验证旧版本 health。

不能让普通用户手工修改 symlink/systemd。

---

## 13. 维护

提供：

```bash
./维护工具-非Docker.sh
```

至少支持：

- status；
- start；
- stop；
- restart；
- logs；
- doctor；
- diagnostics；
- backup；
- restore；
- show version；
- 离线 rebuild frontend（高级）。

---

## 14. Clean-room 验证

正式交付前必须在干净银河麒麟 V10 环境：

- 完全断网；
- 无项目 Python；
- 无 Node/npm；
- 无 Git；
- 无 MATERIAL_MATCHER；
- 只使用本介质；
- 执行 `./启动本地安装.sh`；
- 完成 STEP1～STEP4 smoke。

还必须验证：

- 端口冲突；
- 损坏介质；
- 重复安装；
- 升级；
- readiness 故障回滚；
- backup/restore；
- 双 DB 风险阻断；
- seed 幂等；
- reboot 后 systemd 自动启动。

---

## 15. 最终 PASS 记录

Evidence 至少记录：

- 软件版本；
- main commit；
- 安装包文件名；
- SHA256；
- Python Runtime 版本；
- 模型版本；
- Kylin V10 版本；
- CPU 架构；
- 断网状态；
- clean install；
- upgrade；
- rollback；
- backup/restore；
- 6 方案 seed；
- 同义词 seed；
- STEP1～STEP4 smoke。

全部 PASS 后，非 Docker 方式才可以对客户交付。


---

## 16. 客户端 Win7 浏览器离线工具包

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
