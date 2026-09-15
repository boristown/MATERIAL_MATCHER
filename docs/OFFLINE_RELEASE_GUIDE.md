# MATERIAL_MATCHER v0.8 正式离线交付指南

> 状态：v0.8 实施契约  
> 目标环境：银河麒麟 Linux V10，无 Docker、无公网依赖  
> 原则：Git 仓库只保存源码和文本配置；Python Runtime、wheel、ONNX 模型、Vue `dist`、最终离线介质均在发布流水线外生成，不提交到仓库。

## 1. 交付链路

正式离线介质必须按以下顺序生成：

```text
目标架构基础 Python Runtime
+ 完整 wheelhouse
        ↓
scripts/prepare_runtime.py
        ↓
runtime/ + runtime-manifest.json

Vue 源码
        ↓
npm run build
        ↓
web/dist

runtime + web/dist + 当前后端源码
        ↓
scripts/build_release.py
        ↓
release/ + release-manifest.json

release + 正式模型 + wheelhouse
        ↓
scripts/build_offline_bundle.py
        ↓
离线发布目录 + offline-manifest.json
        ↓
installer/verify_offline_bundle.py
        ↓
sudo ./install.sh
        ↓
material-matcher doctor + systemd + /api/health/ready
```

任何一步失败都不得跳过校验继续发布。

## 2. 外部准备项

发布机需要事先准备三类**不进入 Git**的输入。

### 2.1 基础 Python Runtime

基础 Runtime 必须：

- 与目标 CPU 架构一致，只支持 `x86_64` 或 `aarch64`；
- 自带可执行的 `bin/python3`；
- 自带 `pip`；
- 可整体复制后运行；
- 符号链接只能使用包内相对路径，禁止指向 `/usr/bin/python3` 等主机绝对路径。

推荐目录示例：

```text
staging/python-base/
└── bin/python3
```

### 2.2 wheelhouse

wheelhouse 必须包含当前 `pyproject.toml` 的正式依赖及其全部传递依赖，并与基础 Python 版本和目标 CPU 架构匹配。

至少应包含：

- FastAPI / Uvicorn / Pydantic；
- openpyxl / python-multipart / NumPy；
- `onnxruntime`；
- `tokenizers`；
- 上述包依赖的所有离线 wheel。

`prepare_runtime.py` 强制使用 `pip --no-index --find-links`，不会在缺 wheel 时回退到公网下载。

### 2.3 Embedding 模型

默认模型：

```text
BAAI/bge-base-zh-v1.5
```

模型目录至少包含：

```text
tokenizer.json
model_int8.onnx
```

也允许使用 `model.onnx` 代替 `model_int8.onnx`。模型二进制不得提交到 Git。

## 3. 准备自包含 Python Runtime

示例：

```bash
python3 scripts/prepare_runtime.py \
  --base-runtime-dir /release-input/python-base \
  --wheelhouse-dir /release-input/wheelhouse \
  --output-dir /release-work/runtime \
  --target-arch x86_64
```

该步骤会：

1. 复制基础 Runtime；
2. 使用 `--no-index` 从本地 wheelhouse 安装项目正式依赖与 Embedding 依赖；
3. 执行 `pip check`；
4. 实际 import FastAPI、NumPy、ONNX Runtime、tokenizers 等关键模块；
5. 校验 CPU 架构；
6. 生成 `bin/material-matcher` 启动器；
7. 生成 `runtime-manifest.json`；
8. 将整个 Runtime 文件树 SHA-256 固化进 manifest。

`bin/material-matcher` 属于 Runtime 完整性的一部分，后续 release 阶段不得再改写。

## 4. 构建 Vue production dist

在有 Node 构建环境的发布机执行：

```bash
cd web
npm install --no-audit --no-fund
npm run build
cd ..
```

正式客户服务器不执行 `npm install`，只接收已构建的 `web/dist`。

## 5. 构建 release

当前 v0.8 版本示例：

```bash
python3 scripts/build_release.py \
  --runtime-dir /release-work/runtime \
  --web-dist-dir web/dist \
  --output-dir /release-work/release \
  --release-version 0.8.0 \
  --target-arch x86_64
```

`build_release.py` 强制校验：

- `pyproject.toml` 版本与 `material_matcher.__version__` 一致；
- 参数中的 release version 与项目版本一致；
- Runtime manifest 存在且文件树摘要未被篡改；
- Runtime manifest 架构、实际 Python 架构、目标架构一致；
- 正式依赖可 import；
- `material-matcher --help` 可执行；
- Vue `index.html` 存在。

输出结构：

```text
release/
├── app/material_matcher/
├── runtime/
│   ├── bin/python3
│   ├── bin/material-matcher
│   └── runtime-manifest.json
├── web/dist/
└── release-manifest.json
```

`release-manifest.json` 固化：

- release version；
- CPU 架构；
- Python 版本；
- runtime manifest SHA-256；
- 后端源码树 SHA-256；
- 前端 dist 树 SHA-256。

## 6. 组装正式离线目录

```bash
python3 scripts/build_offline_bundle.py \
  --release-dir /release-work/release \
  --model-dir /release-input/models/BAAI/bge-base-zh-v1.5 \
  --wheelhouse-dir /release-input/wheelhouse \
  --output-dir /release-output/material-matcher-0.8.0-x86_64 \
  --release-version 0.8.0 \
  --target-arch x86_64 \
  --model-id BAAI/bge-base-zh-v1.5
```

最终目录包含：

```text
material-matcher-0.8.0-x86_64/
├── install.sh
├── verify_offline_bundle.py
├── offline-manifest.json
├── release/
├── models/BAAI/bge-base-zh-v1.5/
└── wheelhouse/
```

组装器本身不会联网，并在完成后自动调用离线包校验器。

## 7. 三层完整性链

v0.8 使用三层 manifest：

```text
runtime-manifest.json
        ↓ SHA-256
release-manifest.json
        ↓ SHA-256
offline-manifest.json
```

校验器不仅验证 manifest 文件本身，还会重新计算：

- Runtime 文件树；
- release 后端源码树；
- release Vue dist 文件树；
- 离线包每一个登记文件的大小与 SHA-256。

并拒绝：

- 未登记文件；
- 缺失文件；
- 文件篡改；
- 非安全相对路径；
- 绝对或逃逸符号链接；
- release/runtime/offline 版本不一致；
- CPU 架构不一致；
- 与目标架构不匹配的 `onnxruntime` / `tokenizers` wheel；
- 缺模型、tokenizer、前端、启动器或 Runtime。

可在发布机预检：

```bash
python3 /release-output/material-matcher-0.8.0-x86_64/verify_offline_bundle.py \
  /release-output/material-matcher-0.8.0-x86_64 \
  --skip-arch
```

`--skip-arch` 只允许用于发布机构建预检。客户安装时 `install.sh` 不使用该参数，必须检查现场 CPU 架构。

## 8. 客户现场安装

将完整离线目录复制到银河麒麟 V10 后：

```bash
cd material-matcher-0.8.0-x86_64
sudo ./install.sh
```

安装器会：

1. 校验离线包完整性与当前 CPU 架构；
2. 校验正式麒麟环境；
3. 选择可写本地持久化磁盘中可用空间最大的磁盘；
4. 保持统一逻辑路径 `/var/lib/material_matcher`；
5. 保留既有端口和 admin 密码；首次安装才生成新值；
6. 将 release/model 复制到版本化目录；
7. 在**旧服务仍在线**时以 `material_matcher` 运行用户执行新版本 `doctor`；
8. 只有 doctor 全通过后才停止旧服务；
9. 原子切换 `current`；
10. 启动 systemd 并等待 `/api/health/ready`；
11. 新版本启动失败时恢复安装前 release/model，并在升级场景重启旧服务。

## 9. 部署前 doctor

命令：

```bash
material-matcher doctor \
  --require-frontend \
  --require-embedding \
  --require-release-manifest
```

正式安装器自动以服务运行用户执行该命令。诊断项包括：

- 数据目录可写；
- tmp 可写；
- 配置目录存在；
- 日志目录可写；
- Vue dist 已安装；
- ONNX Runtime/tokenizers 与模型/tokenizer ready；
- release manifest 版本与当前运行代码版本一致；
- release manifest CPU 架构与当前 CPU 一致。

## 10. 升级停机边界

v0.8 不允许在复制或依赖验证阶段提前停止旧服务。

正确顺序：

```text
校验离线包
→ 复制新 release/model
→ 新 Runtime / 模型 / 前端 / 版本链 doctor
→ 全部通过
→ 停止旧服务
→ 原子切换 current
→ 启动新服务
→ readiness
→ 成功结束
```

如新服务启动或 readiness 失败：

```text
停止失败的新服务
→ current 恢复旧 release
→ model current 恢复旧 model
→ daemon-reload
→ 若安装前旧服务正在运行，则重新启动旧服务
```

首次安装失败不会尝试启动不存在的 previous release。

## 11. 大数据目录权限处理

升级不得每次对整个 `/var/lib/material_matcher` 执行递归 `chown -R`。百万级索引、缓存、结果文件可能使这种操作显著拉长升级时间。

v0.8 只调整固定目录本身的所有权，并仅对**本次新复制的模型版本**递归设置所有权；历史索引和结果不做无意义全量遍历。

## 12. 尚未完成的现场验收

代码层离线构建、完整性校验、SPA 托管、doctor、版本化安装、短停机切换和失败回滚已经实现并进入 CI。

以下内容仍必须在真实交付环境验证，不能因为仓库测试通过而宣称完成：

- 正式银河麒麟 Linux V10 实机安装；
- 目标 CPU 对应的真实基础 Python Runtime；
- 完整正式 wheelhouse 的离线安装；
- `BAAI/bge-base-zh-v1.5` 正式 ONNX/tokenizer 介质；
- systemd 权限、SELinux/安全策略、文件系统挂载差异；
- 真实 100 万 Target / 10 万 Source 的性能、内存、磁盘与 Recall@K 验收。

只有上述实机测试完成后，才能把“麒麟正式离线交付”标记为生产验收完成。
