# MATERIAL_MATCHER 1.0 正式离线交付指南

> 目标环境：银河麒麟 Linux V10，无 Docker、无公网依赖。  
> 当前代码版本：`1.0.0`。  
> 本文说明“如何生成和安装可信离线介质”；完整生产上线、金标、百万级性能和最终验收请严格执行仓库根目录 [`agent.md`](../agent.md)。

## 1. 交付链路

```text
目标架构基础 Python Runtime + 完整 wheelhouse
  ↓
scripts/prepare_runtime.py
  ↓
runtime/ + runtime-manifest.json

Vue source
  ↓ npm run build
web/dist

runtime + web/dist + 后端源码
  ↓
scripts/build_release.py
  ↓
release/ + release-manifest.json

release + 正式模型 + wheelhouse
  ↓
scripts/build_offline_bundle.py
  ↓
offline bundle + offline-manifest.json
  ↓
installer/verify_offline_bundle.py
  ↓
sudo ./install.sh
  ↓
material-matcher doctor + systemd + /api/health/ready
```

任一步失败都不得跳过继续发布。

## 2. 外部输入

这些内容**不得提交 Git**：

### 基础 Python Runtime

- 与目标 CPU 一致：`x86_64` 或 `aarch64`；
- 带可执行 `bin/python3` 与 pip；
- 可整体复制；
- Runtime 内符号链接只能使用包内安全相对路径，不能依赖目标机 `/usr/bin/python3`。

### wheelhouse

必须包含 `pyproject.toml` 正式依赖和全部传递依赖，以及：

- `onnxruntime`
- `tokenizers`

`prepare_runtime.py` 强制 `--no-index --find-links`；缺 wheel 时必须失败，不能访问公网补包。

### 正式模型

默认：

```text
BAAI/bge-base-zh-v1.5/
  tokenizer.json
  model_int8.onnx   # 或 model.onnx
```

## 3. 准备 Runtime

```bash
TARGET_ARCH=x86_64  # 或 aarch64
python3 scripts/prepare_runtime.py \
  --base-runtime-dir /release-input/python-base \
  --wheelhouse-dir /release-input/wheelhouse \
  --output-dir /release-work/runtime \
  --target-arch "$TARGET_ARCH"
```

该步骤会执行：

- Runtime 复制；
- 完全离线依赖安装；
- `pip check`；
- FastAPI/NumPy/ONNX Runtime/tokenizers 等关键 import；
- CPU 架构校验；
- `bin/material-matcher` 启动器生成；
- `runtime-manifest.json`；
- Runtime 文件树 SHA-256。

后续阶段不得修改已经纳入 Runtime 摘要的文件。

## 4. 构建 Vue production dist

```bash
cd web
npm install --no-audit --no-fund
npm run build
cd ..
```

客户服务器不执行 npm，只接收 `web/dist`。

## 5. 构建 1.0.0 Release

```bash
python3 scripts/build_release.py \
  --runtime-dir /release-work/runtime \
  --web-dist-dir web/dist \
  --output-dir /release-work/release \
  --release-version 1.0.0 \
  --target-arch "$TARGET_ARCH"
```

构建器强制校验：

- `pyproject.toml` 和 `material_matcher.__version__` 都是 `1.0.0`；
- 参数版本与源码版本一致；
- Runtime manifest 和文件树一致；
- Runtime/Python/目标 CPU 架构一致；
- 正式依赖可 import；
- `material-matcher --help` 可执行；
- `web/dist/index.html` 存在。

产物：

```text
release/
  app/material_matcher/
  runtime/
    bin/python3
    bin/material-matcher
    runtime-manifest.json
  web/dist/
  release-manifest.json
```

## 6. 组装离线 Bundle

```bash
python3 scripts/build_offline_bundle.py \
  --release-dir /release-work/release \
  --model-dir /release-input/models/BAAI/bge-base-zh-v1.5 \
  --wheelhouse-dir /release-input/wheelhouse \
  --output-dir "/release-output/material-matcher-1.0.0-${TARGET_ARCH}" \
  --release-version 1.0.0 \
  --target-arch "$TARGET_ARCH" \
  --model-id BAAI/bge-base-zh-v1.5
```

结构：

```text
material-matcher-1.0.0-<arch>/
  install.sh
  verify_offline_bundle.py
  offline-manifest.json
  release/
  models/BAAI/bge-base-zh-v1.5/
  wheelhouse/
```

组装过程不联网，并会自动执行 bundle 校验。

## 7. 三层完整性链

```text
runtime-manifest.json
        ↓ SHA-256
release-manifest.json
        ↓ SHA-256
offline-manifest.json
```

校验器会重新检查：

- Runtime 文件树；
- release 后端源码树；
- Vue dist 文件树；
- bundle 登记文件大小与 SHA-256；
- CPU 架构；
- release/runtime/offline 版本一致性；
- ONNX/tokenizers wheel 架构；
- 模型、tokenizer、前端、启动器和 Runtime 完整性；
- 禁止绝对/逃逸 symlink；
- 禁止未登记文件或篡改文件。

发布机可以：

```bash
python3 /release-output/material-matcher-1.0.0-${TARGET_ARCH}/verify_offline_bundle.py \
  /release-output/material-matcher-1.0.0-${TARGET_ARCH} \
  --skip-arch
```

`--skip-arch` 只允许发布机预检。正式客户机校验禁止使用。

## 8. 客户现场安装

```bash
cd material-matcher-1.0.0-<arch>
python3 verify_offline_bundle.py .
sudo ./install.sh
```

安装器会：

1. 校验 bundle 完整性和当前 CPU；
2. 验证银河麒麟环境；
3. 选择可写本地持久化磁盘并保持逻辑路径 `/var/lib/material_matcher`；
4. 首次安装选择 12000–29999 可用端口并生成 bootstrap admin 密码；
5. 版本化复制 release/model；
6. 在旧服务仍运行时，以正式 `material_matcher` 用户执行新版本 doctor；
7. doctor 成功后才停止旧服务；
8. 原子切换 release/model `current`；
9. systemd 启动并轮询 `/api/health/ready`；
10. 新版本启动/readiness 失败时恢复安装前 release/model；
11. 升级不会递归 `chown -R` 海量历史索引、缓存和结果。

正式逻辑目录：

```text
/opt/material_matcher
/etc/material_matcher
/var/lib/material_matcher
/var/log/material_matcher
```

## 9. 严格 doctor

```bash
sudo -u material_matcher env \
  MATERIAL_MATCHER_DATA_DIR=/var/lib/material_matcher \
  MATERIAL_MATCHER_CONFIG_DIR=/etc/material_matcher \
  MATERIAL_MATCHER_LOG_DIR=/var/log/material_matcher \
  MATERIAL_MATCHER_MODEL_ROOT=/var/lib/material_matcher/models/current \
  MATERIAL_MATCHER_WEB_DIST_DIR=/opt/material_matcher/current/web/dist \
  /opt/material_matcher/current/runtime/bin/material-matcher doctor \
  --require-frontend --require-embedding --require-release-manifest
```

检查范围包括：目录权限、前端、ONNX Runtime/tokenizer/model readiness、Release 版本与 CPU 架构。

## 10. 升级与回滚边界

升级顺序固定：

```text
校验 bundle
→ 复制新 release/model（旧服务在线）
→ 新版本 doctor（旧服务在线）
→ 停止旧服务
→ 原子切换 current
→ 启动新服务
→ readiness
```

启动/readiness 失败：

```text
停止失败新服务
→ current 恢复旧 release
→ model current 恢复旧 model
→ daemon-reload
→ 若安装前旧服务运行，则重启旧服务
```

安装器负责激活阶段自动回滚。上线后若因业务问题回滚，必须先评估数据库兼容性并使用安装前数据库/配置备份；不要只切旧代码而忽略数据结构。

## 11. 1.0 安全变化

- bootstrap `admin` 的随机初始密码只用于首次登录；
- 首次登录必须修改密码；
- 新密码不能与当前密码相同；
- 用户密码使用 scrypt + random salt 持久化；
- RBAC 为 admin/operator/reviewer/viewer；
- 角色变更、停用、密码重置会使旧 session 失效；
- 最后一个启用 admin 受保护。

初始密码文件仍为：

```text
/etc/material_matcher/secret/admin_password.env
```

必须保持 `root:root 0600`，不要复制到上线证据包或工单正文。

## 12. 生产验收不属于“安装成功”

安装器/doctor/readiness 全绿只表示软件成功安装，不表示真实业务已通过。

1.0 新增：

```bash
material-matcher acceptance
material-matcher acceptance --require-production-ready
```

生产门槛必须由项目方显式批准并通过环境变量提供：

```text
MATERIAL_MATCHER_ACCEPTANCE_MIN_TRUTH_ROWS
MATERIAL_MATCHER_ACCEPTANCE_MIN_TRUTH_COVERAGE
MATERIAL_MATCHER_ACCEPTANCE_MIN_TOP1_ACCURACY
MATERIAL_MATCHER_ACCEPTANCE_MIN_FINAL_ACCURACY
MATERIAL_MATCHER_ACCEPTANCE_MAX_REVIEW_RATE
MATERIAL_MATCHER_ACCEPTANCE_MAX_SCALE_HOURS
```

最终生产验收要求：

- 正式 Embedding 模型 ready + 正式吞吐 benchmark；
- vector Recall guard；
- 客户真实金标指标达到上述批准阈值；
- >=100K Source × >=1M Target 真实完成任务，并在批准的最大耗时内完成；
- 当前主机为银河麒麟 V10；
- 正式 release/前端/manifest；
- RBAC 和管理员密码轮换完成；
- `acceptance --require-production-ready` 退出 0，`production_ready=true`。

完整命令、证据要求、烟测和回滚流程以 [`agent.md`](../agent.md) 为准。
