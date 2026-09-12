# MATERIAL_MATCHER 麒麟 V10 一键部署、运行与 B/S UI 设计

> 文档状态：Normative Draft
>
> 本文定义 MATERIAL_MATCHER 在客户现场的**强制部署与运行规范**。目标环境为银河麒麟 Linux V10，默认无 Docker。所有客户应使用同一套安装包结构、同一套逻辑目录、同一套 systemd 服务约定和同一套 B/S 管理界面。客户差异只允许通过 Profile / Catalog / Mapping / Dictionary / Template 配置体现。

---

## 1. 设计目标

MATERIAL_MATCHER 服务端必须满足以下要求：

1. 目标操作系统为银河麒麟 Linux V10；
2. **不依赖 Docker / Docker Compose / Kubernetes**；
3. 支持完全离线安装，不要求目标服务器访问互联网；
4. 提供一键安装入口，例如：

```bash
sudo ./install.sh
```

5. 安装包自带运行时、Python 依赖、Native 依赖、Vue 构建产物、向量存储组件、BBQ 匹配引擎和 Excel 模板配置引擎；
6. 自动检测 CPU 架构、磁盘、可用空间、端口、systemd 等运行环境；
7. 自动推荐可用空间最大的磁盘作为大数据存储位置；
8. 所有客户使用**完全一致的逻辑安装路径**；
9. 自动选择一个未被占用的高位端口，优先使用 10000 以上的不常见端口；
10. B/S 架构，浏览器直接操作；
11. 不建设多用户/租户系统，仅固定一个 `admin` 管理账号；
12. 首次安装自动生成随机 10 位密码并安全保存到固定路径；
13. 自动创建并启动 systemd 服务，并设置开机自动启动；
14. 上传文件、中间数据、临时索引、预览文件等必须具备可管理的生命周期；
15. 浏览器端可查看临时空间占用，并按任务/时间/类型选择清理；
16. 管理界面基于 Vue 3，提供现代化、可视化、低学习成本的配置体验；
17. 换客户时不得修改服务端核心代码和前端核心代码，只允许切换/新增配置包。

---

## 2. 总体部署形态

推荐部署形态：

```text
浏览器
  │
  │ HTTP/HTTPS
  ▼
Material Matcher Server
  ├── Vue 3 静态前端
  ├── REST API
  ├── 任务调度
  ├── Profile/模板配置引擎
  ├── Excel/CSV 数据接入
  ├── DatasetGraph / Join
  ├── Matcher / Score / Decision
  ├── BBQ 批量向量召回
  ├── Vector Store / Index
  └── 临时文件管理
```

第一阶段优先采用**单机、少进程、少服务**原则。

如果向量后端能够以内嵌库方式运行，则默认与主服务同进程/同安装包工作，避免现场额外维护独立数据库服务。

如果后续实现需要独立向量 daemon，则仍必须：

- 随安装包一并离线交付；
- 由安装脚本自动安装；
- 由 systemd 自动管理；
- 不允许要求现场单独部署 Docker 容器；
- 对用户隐藏内部组件端口，用户只需要访问主 B/S 端口。

---

## 3. 标准安装包

建议发布物：

```text
material_matcher-<version>-kylin10-<arch>.tar.gz
```

例如：

```text
material_matcher-1.0.0-kylin10-x86_64.tar.gz
material_matcher-1.0.0-kylin10-aarch64.tar.gz
```

解压后：

```text
material_matcher-installer/
├── install.sh
├── uninstall.sh
├── upgrade.sh
├── healthcheck.sh
├── package/
│   ├── app/
│   ├── runtime/
│   ├── wheelhouse/
│   ├── native/
│   ├── web/
│   │   └── dist/
│   ├── plugins/
│   ├── models/
│   ├── schemas/
│   └── migrations/
├── systemd/
├── templates/
└── VERSION
```

现场安装不得要求：

```text
npm install
npm run build
pip install <公网包>
git clone
Docker pull
现场 gcc 编译
```

Vue 生产文件必须在发布阶段构建完毕，作为静态资源进入安装包。

---

## 4. 全客户统一目录规范

所有客户必须使用相同的**逻辑路径**。禁止出现：

```text
/opt/13s_material_matcher
/opt/customer_a_matcher
/home/user/matcher
```

统一规范如下。

### 4.1 程序目录

```text
/opt/material_matcher/
├── current/             # 当前版本程序
├── releases/            # 可选历史版本
└── plugins/             # 外部通用插件
```

程序目录原则上不存客户业务数据。

### 4.2 配置目录

```text
/etc/material_matcher/
├── material_matcher.yaml
├── server.env
├── storage.env
├── profiles/
├── catalogs/
├── mappings/
├── dictionaries/
├── templates/
└── secret/
    └── admin_password.env
```

### 4.3 运行数据逻辑目录

```text
/var/lib/material_matcher/
├── datasets/
├── vector/
├── indexes/
├── models/
├── uploads/
├── results/
├── jobs/
└── tmp/
```

### 4.4 日志、缓存、运行态

```text
/var/log/material_matcher/
/var/cache/material_matcher/
/run/material_matcher/
```

所有运维文档、脚本、UI 和健康检查只引用以上逻辑路径。

---

## 5. 最大磁盘自动探测与固定逻辑路径兼容

“自动使用大空间磁盘”与“所有客户路径统一”不能互相冲突。

因此定义：

> **逻辑路径永远固定；大体积数据的物理存储位置可由安装器自动选择。**

### 5.1 探测目标

安装脚本应识别所有可写的本地持久化文件系统，并计算：

- 挂载点；
- 文件系统类型；
- 总空间；
- 已用空间；
- 可用空间；
- 是否只读；
- 是否可写；
- 是否为临时/虚拟文件系统；
- 是否为可移动介质。

推荐使用：

```bash
lsblk
findmnt
df
```

也可通过 Python/系统 API 统一解析。

### 5.2 排除项

默认排除：

- `/boot`；
- `/boot/efi`；
- `tmpfs`；
- `devtmpfs`；
- `proc`；
- `sysfs`；
- `cgroup`；
- `overlay`；
- `squashfs`；
- 只读挂载；
- USB/可移动临时盘（除非管理员明确指定）；
- 明显不适合作为持久化业务数据盘的挂载点。

### 5.3 排序规则

默认按**可用空间**而不是磁盘标称总容量排序：

```text
available_bytes DESC
```

推荐安装器输出：

```text
检测到可用持久化磁盘：

1. /data      可用 1.82 TB   [推荐]
2. /          可用 186 GB
3. /backup    可用 95 GB

建议大数据存储位置：/data/material_matcher
```

### 5.4 固定路径实现

如果最大空间磁盘为 `/data`，可以实际创建：

```text
/data/material_matcher/
├── datasets/
├── vector/
├── indexes/
├── uploads/
├── results/
├── jobs/
└── tmp/
```

然后让固定逻辑目录：

```text
/var/lib/material_matcher/
```

映射到该物理位置。

实现可选择：

1. 符号链接；
2. bind mount；
3. 固定根目录 + 大目录分别链接。

第一阶段推荐简单且透明的**固定根目录 + 大数据子目录链接**。

无论实际磁盘位于 `/data`、`/data1`、`/u01` 还是其他挂载点，程序永远只访问：

```text
/var/lib/material_matcher/...
```

从而保证所有客户运维路径完全一致。

### 5.5 存储配置记录

实际物理路径写入：

```text
/etc/material_matcher/storage.env
```

例如：

```bash
MATERIAL_MATCHER_STORAGE_ROOT=/data/material_matcher
MATERIAL_MATCHER_LOGICAL_DATA_ROOT=/var/lib/material_matcher
```

---

## 6. 自动端口选择

### 6.1 原则

主 B/S 服务：

- 不使用 80/443 作为强制默认；
- 不使用 8080 等常见开发端口作为唯一默认；
- 优先选取 `10000+` 的不常见端口；
- 安装时自动探测端口是否占用；
- 选择结果永久写入固定配置文件；
- 升级时沿用原端口，不重新随机。

### 6.2 推荐范围

第一阶段建议随机范围：

```text
12000 ~ 29999
```

理由：

- 满足 10000+；
- 避免常见系统服务端口；
- 尽量避开很多 Linux 系统默认的高位临时端口区间；
- 足够大的随机空间。

### 6.3 选择算法

安装器：

```text
1. 若已有 /etc/material_matcher/server.env，则复用现有端口；
2. 否则使用 CSPRNG 随机生成候选端口；
3. 检查监听表；
4. 实际尝试 bind 0.0.0.0:<port>；
5. 成功后立即释放，并锁定该端口；
6. 最多重试 N 次；
7. 极端情况下回退顺序扫描可用高位端口。
```

不能只通过 `ss` 文本判断，最终必须以实际 socket bind 为准。

### 6.4 固化配置

```text
/etc/material_matcher/server.env
```

例如：

```bash
MATERIAL_MATCHER_HOST=0.0.0.0
MATERIAL_MATCHER_PORT=17843
```

安装完成时输出：

```text
访问地址：http://<服务器IP>:17843
```

---

## 7. 固定 admin 登录模型

### 7.1 不建设用户系统

第一阶段明确：

- 不做用户注册；
- 不做组织机构；
- 不做角色管理；
- 不做权限矩阵；
- 不做多租户。

系统只有：

```text
username = admin
```

### 7.2 随机 10 位密码

首次安装使用操作系统安全随机源生成**恰好 10 位**密码。

建议字符集：

```text
A-Z
a-z
0-9
```

可排除容易人工混淆的：

```text
0 O o 1 I l
```

并保证至少包含：

- 1 个大写字母；
- 1 个小写字母；
- 1 个数字。

禁止使用时间戳、PID、`$RANDOM` 单独作为密码源。

### 7.3 密码固定存储位置

按要求固定：

```text
/etc/material_matcher/secret/admin_password.env
```

内容例如：

```bash
MATERIAL_MATCHER_ADMIN_USERNAME=admin
MATERIAL_MATCHER_ADMIN_PASSWORD=Ab7xQ9mK2R
```

文件权限：

```text
owner: root
mode : 0600
```

主 systemd 服务通过 `EnvironmentFile=` 读取，应用不需要开放读取该文件的 HTTP API。

### 7.4 安装完成展示

安装脚本应在最后明确输出：

```text
MATERIAL_MATCHER 安装完成
地址    : http://10.x.x.x:17843
用户名  : admin
密码文件: /etc/material_matcher/secret/admin_password.env
```

可选择同时显示一次初始密码。

### 7.5 密码修改

UI 支持“修改 admin 密码”。修改后：

- 原子写入 secret 文件；
- 保持 `0600`；
- 当前会话可选择失效；
- 不引入额外用户表。

---

## 8. Web 登录与会话安全

即使只有一个 admin，也必须避免把密码直接长期放在浏览器 LocalStorage 中。

建议：

```text
admin + password
      ↓
POST /api/auth/login
      ↓
服务端校验
      ↓
短期 Session / Signed Token
      ↓
HttpOnly Cookie
```

Cookie 建议：

- `HttpOnly`；
- `SameSite=Strict` 或 `Lax`；
- HTTPS 环境下设置 `Secure`；
- 明确过期时间；
- 支持退出登录立即失效。

不得提供匿名修改配置、重建索引、删除临时文件等管理接口。

---

## 9. systemd 服务规范

### 9.1 服务名固定

主服务固定：

```text
material_matcher.service
```

如果向量后端必须独立进程：

```text
material_matcher_vector.service
```

如果后续加入后台 worker，可使用：

```text
material_matcher_worker.service
```

但第一阶段优先减少服务数量。

### 9.2 独立系统用户

安装器创建：

```text
user: material_matcher
```

要求：

- 系统用户；
- 默认无交互 Shell；
- 无 sudo；
- 仅拥有业务运行目录权限。

### 9.3 systemd 核心要求

服务应包括：

```text
Restart=on-failure
RestartSec=3
WorkingDirectory=/opt/material_matcher/current
EnvironmentFile=/etc/material_matcher/server.env
EnvironmentFile=/etc/material_matcher/storage.env
EnvironmentFile=/etc/material_matcher/secret/admin_password.env
```

并：

```bash
systemctl enable --now material_matcher.service
```

安装脚本必须等待健康检查通过后才报告“安装成功”。

### 9.4 健康检查

提供：

```text
GET /api/health
GET /api/health/ready
```

至少检查：

- Web/API 正常；
- 配置可读；
- 数据目录可写；
- 向量后端可用；
- BBQ backend 加载成功；
- 临时目录可用；
- 剩余磁盘空间达到最低阈值。

---

## 10. 一键安装流程

`install.sh` 必须是幂等的，既能首次安装，也能识别已有安装。

建议流程：

```text
[1] 检测 root/sudo 权限
[2] 检测 Kylin V10 / CPU 架构
[3] 检查基础 ABI 与系统命令
[4] 检测所有持久化磁盘与可用空间
[5] 推荐最大可用空间磁盘
[6] 创建标准系统用户与目录
[7] 安装自包含 runtime/native 依赖
[8] 安装主服务
[9] 安装向量存储 / BBQ 引擎
[10] 安装 Excel 模板配置引擎
[11] 安装 Vue 静态前端
[12] 随机选择未占用高位端口
[13] 生成 admin 10 位密码
[14] 写入固定配置/secret 路径
[15] 注册 systemd
[16] enable + start
[17] 执行 healthcheck
[18] 输出地址、账号、密码路径、数据路径、日志路径
```

安装失败必须：

- 输出明确错误步骤；
- 不留下半安装状态；
- 能够重新运行继续/修复；
- 对已有配置和数据采取保护策略。

---

## 11. 安装器交互方式

### 11.1 默认交互模式

```bash
sudo ./install.sh
```

展示：

```text
推荐数据盘：/data （可用 1.82 TB）
逻辑数据目录：/var/lib/material_matcher
推荐端口：17843

继续安装？ [Y/n]
```

### 11.2 无人值守模式

支持：

```bash
sudo ./install.sh --yes
```

使用推荐值自动完成。

### 11.3 可覆盖参数

可选支持：

```bash
sudo ./install.sh \
  --storage-root /data/material_matcher \
  --port 17843 \
  --bind 0.0.0.0
```

无论物理存储参数如何变化，逻辑路径仍保持固定。

---

## 12. 防火墙与网络

服务对局域网浏览器开放时，默认绑定：

```text
0.0.0.0:<selected_port>
```

安装器应检测：

- `firewalld` 是否启用；
- 当前端口是否已允许；
- 是否有基础网络访问限制。

推荐策略：

- 交互安装：提示是否自动放行选定 TCP 端口；
- `--yes` 模式：可由安装策略决定自动放行，或通过 `--open-firewall` 显式控制；
- 不修改与 MATERIAL_MATCHER 无关的防火墙规则。

安装报告中必须显示端口和防火墙状态。

---

## 13. 向量数据库 / Vector Store 自动安装

### 13.1 原则

向量能力属于产品自身组成部分，不应要求客户单独部署第三方平台。

安装包必须自动安装：

- 向量数据存储层；
- BBQ 1-bit Target Index；
- Query 量化与批量检索组件；
- 索引元数据；
- mmap / HNSW / Flat 等已实现后端；
- 索引版本和 Profile hash 元数据。

### 13.2 默认数据位置

固定逻辑路径：

```text
/var/lib/material_matcher/vector/
/var/lib/material_matcher/indexes/
```

底层可以自动映射到最大空间磁盘。

### 13.3 用户体验

用户不需要：

- 安装 Elasticsearch；
- 配置 Docker；
- 安装 Milvus；
- 手动启动向量服务；
- 手工创建 index；
- 理解内部 BBQ 文件格式。

UI 只需要提供：

```text
创建/导入集团码 Catalog
→ 构建索引
→ 显示进度
→ 索引 Ready
```

---

## 14. BBQ 匹配引擎自动安装

BBQ 引擎作为产品内置组件随发行包交付。

安装器必须自动检测 CPU 能力，例如：

- x86_64；
- AVX / AVX2；
- POPCNT；
- AVX-512（若构建版本支持且实测启用）；
- aarch64 / NEON。

然后自动选择兼容实现：

```text
最佳 SIMD backend
    ↓
兼容 SIMD backend
    ↓
scalar fallback
```

不得要求现场重新编译 Native 扩展。

运行时 UI 的“系统状态”页应显示：

```text
BBQ backend: AVX2 + POPCNT
Vector dimension: 512
Target quantization: 1 bit/dim
Query quantization: 4 bit/dim
Index mode: Flat / HNSW / mmap
```

---

## 15. Excel 自定义模板配置引擎

这是 B/S 管理端的核心能力之一。

目标是让现场人员面对一个全新的所/新格式时，可以通过浏览器完成配置，而不是修改 YAML 源码。

### 15.1 配置向导

推荐流程：

```text
上传 Source 样例 Excel
      ↓
自动识别 Sheet / 表头行 / 列
      ↓
上传 Target/集团码样例 Excel
      ↓
自动识别 Catalog 结构
      ↓
字段映射
      ↓
组合/回退/字典/归一化
      ↓
匹配算法选择
      ↓
权重配置
      ↓
物料组/Catalog 路由
      ↓
阈值/敏感性
      ↓
Top-N / 输出模板
      ↓
校验
      ↓
小样本 Dry Run
      ↓
保存 Profile
```

### 15.2 字段映射 UI

前端应支持拖拽或下拉方式配置：

```text
SAP 字段              逻辑字段             集团字段
------------------------------------------------------
ZXHGG            →    specification    →    规格
ZSCCJ            →    manufacturer     →    生产厂家
ZCGBZ + ZJSBZ    →    standard         →    采用标准
```

### 15.3 一对多/多对一/多对多

UI 必须能表达：

- 1 → 1；
- 1 → N；
- N → 1；
- N → N；
- concat；
- coalesce；
- best_of；
- dictionary_map；
- nullify；
- value_map。

### 15.4 权重与阈值 UI

提供：

- 数值输入；
- Slider；
- 权重总和提示；
- 自动归一化；
- 不同 Rule Set 权重；
- 不同物料组阈值；
- MATCHED / REVIEW / UNMATCHED 区间可视化。

### 15.5 配置保存

UI 最终生成标准 Profile，而不是生成客户专用代码。

保存到：

```text
/etc/material_matcher/profiles/
/etc/material_matcher/catalogs/
/etc/material_matcher/mappings/
/etc/material_matcher/dictionaries/
```

配置发布前必须经过 Schema Validator。

---

## 16. B/S 前端技术栈

推荐：

```text
Vue 3
TypeScript
Vite
Vue Router
Pinia
Element Plus（推荐）
ECharts（需要统计图时）
```

原则：

- 现代化 UI；
- 中文友好；
- 表格操作性能稳定；
- 大量字段配置时仍然易用；
- 不要求现场安装 Node.js；
- 发布时编译成静态文件；
- 与 API 同源部署，尽量避免现场 CORS 配置。

主服务可直接提供：

```text
/          Vue SPA
/api/*     REST API
```

这样用户只需要一个端口。

---

## 17. UI 信息架构

第一阶段建议页面：

### 17.1 登录

- 固定账号 `admin`；
- 密码输入；
- 登录状态；
- 修改密码入口。

### 17.2 首页 / Dashboard

显示：

- 服务状态；
- 当前版本；
- 服务器 IP/端口；
- CPU/内存；
- 数据盘总空间/可用空间；
- 临时文件空间；
- Catalog 数量；
- 索引数量；
- 最近匹配任务；
- 最近错误。

### 17.3 数据源管理

- 上传 Source；
- 上传 Target；
- Sheet 预览；
- 表头检测；
- 列类型/样例值；
- 文件大小；
- 数据行数；
- 数据质量提示。

### 17.4 Profile / 模板配置

- Source/Target 字段映射；
- Dataset Join；
- Catalog 路由；
- 字段组合；
- 标准化；
- 同义词；
- Matcher；
- 权重；
- 阈值；
- 输出模板；
- Profile 版本；
- 导入/导出配置包。

### 17.5 Catalog 与向量索引

- Catalog 列表；
- 数据版本；
- 向量模型；
- 维数；
- BBQ backend；
- 索引模式；
- 索引大小；
- 构建时间；
- 状态；
- 构建/重建/删除。

### 17.6 匹配任务

创建任务时选择：

- Source 数据；
- Profile；
- Target Catalog；
- 是否覆盖参数；
- Top-N；
- 输出格式。

运行中显示：

```text
读取
标准化
Embedding
BBQ 检索
精排
决策
导出
```

并显示百分比、已处理行数、耗时、预计剩余时间。

### 17.7 结果中心

至少支持：

- MATCHED；
- REVIEW；
- UNMATCHED；
- Top-N 候选；
- 字段级得分；
- 搜索/过滤；
- Excel 导出。

### 17.8 临时文件管理

详见下一节。

### 17.9 系统设置 / 诊断

- admin 密码；
- 当前端口；
- 存储根目录；
- 运行版本；
- systemd 状态；
- BBQ backend；
- 日志下载/查看；
- 健康检查。

---

## 18. 临时文件生命周期管理

### 18.1 临时数据分类

必须区分：

1. 上传 staging；
2. Excel 解析缓存；
3. 预览文件；
4. 中间转换文件；
5. 临时 embedding；
6. 任务中间候选；
7. 临时导出；
8. 失败任务残留。

不得把以下数据错误归类为临时文件：

- 已发布 Profile；
- Dictionary；
- Catalog 原始正式数据（除非用户明确删除）；
- 正式 BBQ 索引；
- 正式匹配结果；
- 模型；
- 配置；
- 审计元数据。

### 18.2 固定临时目录

```text
/var/lib/material_matcher/tmp/
```

建议：

```text
/var/lib/material_matcher/tmp/
├── uploads/
├── previews/
├── jobs/<job_id>/
├── exports/
└── failed/
```

### 18.3 临时文件 Manifest

每项临时数据记录：

- id；
- job_id；
- 类型；
- 路径；
- 创建时间；
- 最后访问时间；
- 大小；
- 是否正在使用；
- 是否可删除；
- TTL；
- 来源任务。

禁止前端直接拼接磁盘路径执行删除。

### 18.4 UI 清理能力

页面显示：

```text
临时文件总大小：38.6 GB

任务              类型          大小        时间       状态
------------------------------------------------------------
JOB-001          中间文件       12.4 GB     ...        可清理
JOB-002          上传缓存        8.1 GB     ...        使用中
JOB-003          失败任务        2.7 GB     ...        可清理
```

支持：

- 清理选中；
- 清理指定任务；
- 清理超过 N 天；
- 清理所有可安全删除项；
- 仅预览，不执行；
- 二次确认。

### 18.5 安全保护

清理 API 必须检查：

- 是否在允许的 temp root 内；
- 是否为活动任务；
- 是否被正式结果引用；
- 是否为当前索引；
- 是否为配置/模型目录；
- 是否存在路径穿越。

禁止使用前端传入的任意绝对路径执行 `rm -rf`。

### 18.6 自动清理

支持配置：

```yaml
temp:
  auto_cleanup: true
  retention_days: 7
  failed_job_retention_days: 14
  minimum_free_space_gb: 20
```

自动清理与手工清理共用同一安全策略。

---

## 19. 空间不足保护

在执行大任务之前预估：

- 输入文件；
- 解压/解析膨胀；
- embedding 中间数据；
- BBQ index；
- Top-N 中间结果；
- Excel 输出。

如果预计剩余空间低于阈值，任务必须提前阻止并提示，而不是运行到一半把磁盘写满。

Dashboard 显示：

```text
数据盘：1.82 TB 可用 / 2.00 TB
临时目录：38.6 GB
索引：67.4 GB
结果：18.2 GB
```

---

## 20. 配置与数据备份边界

升级/重装必须保护：

```text
/etc/material_matcher/
/var/lib/material_matcher/datasets/
/var/lib/material_matcher/indexes/
/var/lib/material_matcher/results/
```

版本升级时：

1. 备份旧配置；
2. 校验配置 Schema；
3. 执行必要 migration；
4. 保留 admin 密码；
5. 保留原端口；
6. 保留物理存储位置；
7. 更新程序；
8. 重启服务；
9. healthcheck；
10. 失败可回滚 previous release。

---

## 21. 卸载策略

默认卸载：

```bash
sudo ./uninstall.sh
```

只删除：

- systemd unit；
- 程序二进制；
- runtime；
- Web 静态资源。

默认**不删除业务数据、配置、密码和结果**。

只有显式：

```bash
sudo ./uninstall.sh --purge
```

并二次确认后，才允许清理数据目录。

---

## 22. 日志规范

固定：

```text
/var/log/material_matcher/
```

建议：

```text
app.log
access.log
job.log
install.log
upgrade.log
```

必须有日志滚动策略，防止日志写满磁盘。

日志不得明文打印：

- admin 密码；
- Session token；
- secret env 内容。

---

## 23. 安装完成验收

一键安装成功必须同时满足：

```text
[PASS] Kylin V10 环境检查
[PASS] 标准路径创建
[PASS] 大数据盘已选择
[PASS] 固定逻辑数据路径可写
[PASS] 主端口可用
[PASS] admin 密码已生成
[PASS] 向量存储可用
[PASS] BBQ 引擎可用
[PASS] Excel 模板引擎可用
[PASS] Vue UI 可访问
[PASS] systemd enabled
[PASS] systemd active
[PASS] /api/health ready
```

然后输出：

```text
访问地址 : http://<IP>:<PORT>
用户名   : admin
密码路径 : /etc/material_matcher/secret/admin_password.env
配置路径 : /etc/material_matcher
数据路径 : /var/lib/material_matcher
日志路径 : /var/log/material_matcher
```

---

## 24. 零代码客户切换在 B/S 中的体现

后续其他所上线时，现场实施流程应该是：

```text
安装同一个 MATERIAL_MATCHER 安装包
        ↓
浏览器登录 admin
        ↓
上传该所 SAP/ERP 样例
        ↓
上传集团码模板
        ↓
通过 UI 建立字段映射 / Join / Catalog 路由
        ↓
配置同义词 / 权重 / 阈值
        ↓
Dry Run
        ↓
发布 Profile
        ↓
正式批量匹配
```

不应该出现：

```text
重新拉代码
修改 Python
修改 Vue
现场重新编译
为客户重新制作 Docker 镜像
```

因此 UI 的 Template/Profile 配置能力本身就是“插件化/零代码客户适配”的产品化入口。

---

## 25. 客户安装目录一致性验收

至少在 3 个完全不同客户环境验证：

```text
/opt/material_matcher
/etc/material_matcher
/var/lib/material_matcher
/var/log/material_matcher
```

必须完全一致。

允许变化的只有：

- `/var/lib/material_matcher` 背后的实际大容量物理磁盘；
- B/S 自动选择的主端口；
- admin 随机密码；
- Profile / Catalog / Mapping / Dictionary；
- 客户业务数据。

---

## 26. 第一阶段技术实现建议

### 后端

建议：

```text
Python 3 自包含 Runtime
FastAPI 或等价轻量 REST 框架
Pydantic/JSON Schema 配置校验
systemd
```

不依赖系统 Python。

### 前端

建议：

```text
Vue 3 + TypeScript + Vite + Element Plus
```

发布后仅保留 `dist/`。

### 数据与向量

```text
本地文件/元数据存储
Embedded Vector Store
BBQ 1-bit Index
mmap
SIMD/POPCNT Native Core
```

优先避免引入需要独立复杂运维的重型服务。

---

## 27. 后续开发优先级

部署/UI 方向建议按以下顺序落地：

1. 固定目录规范；
2. install.sh 环境与磁盘探测；
3. 自动端口；
4. admin secret 生成；
5. systemd + healthcheck；
6. 单服务 Vue SPA + API；
7. Profile/Template 配置 API；
8. Excel Schema 检测与字段映射 UI；
9. Catalog/BBQ 索引管理；
10. 匹配任务 UI；
11. 结果中心；
12. 临时文件管理；
13. upgrade/rollback/uninstall；
14. x86_64 / aarch64 麒麟 V10 安装验证。

---

## 28. 最终约束

以下内容视为产品级硬约束：

1. **不以 Docker 作为运行前提**；
2. **客户现场可完全离线一键安装**；
3. **所有客户逻辑路径完全一致**；
4. **自动推荐最大可用空间数据盘**；
5. **自动选择未占用的 10000+ 高位端口并持久化**；
6. **固定 admin，安装时生成随机 10 位密码**；
7. **密码固定保存在 `/etc/material_matcher/secret/admin_password.env`**；
8. **自动安装并启动向量存储、BBQ 引擎、Excel 模板配置能力**；
9. **systemd 自动启动和故障恢复**；
10. **B/S + Vue 3 现代化管理 UI**；
11. **浏览器可管理并安全清理临时文件**；
12. **换客户只换 Profile/Catalog/Mapping/Dictionary，不改代码**。
