# MATERIAL_MATCHER 源码可见离线发布指南

> 目标环境：银河麒麟 Linux V10，可采用原生源码部署或 Docker 源码部署。版本号不得写死在本文或构建命令中；唯一人工版本源是根目录 `pyproject.toml`。

## 1. 本阶段交付边界

本仓库提供：版本统一逻辑、source-visible release 组装源码、离线 bundle 组装源码、Native/Docker 部署源码、安装向导源码、维护工具源码和麒麟安装文档。

本阶段**不声称已经制作**：Python Runtime 二进制包、Node Runtime 二进制包、Docker image tar、离线 RPM、完整离线 npm 依赖或最终大型安装介质。这些由后续 OpenCode Agent 在目标 CPU/银河麒麟环境实际制作、拷贝和验收。

## 2. 版本链

```text
pyproject.toml [project].version
        ↓
material_matcher.__version__
        ↓
/api/health + /api/about
        ↓
release-manifest.json
        ↓
offline-manifest.json
        ↓
安装向导 + 前端运行时版本显示
```

`material_matcher.__version__` 在源码部署时从同一份 `pyproject.toml` 读取；只有在安装成 Python distribution 且源码 pyproject 不存在时才回退到 package metadata。构建脚本的 `--release-version` 只是可选一致性检查，不是第二个版本源。

## 3. 原生源码 Release 结构

```text
release/
├── source/
│   ├── src/material_matcher/
│   ├── web/
│   ├── scripts/
│   ├── installer/
│   ├── docker/
│   ├── pyproject.toml
│   └── README.md
├── runtime/
├── web-dist/
├── tools/
└── release-manifest.json
```

正式后端通过 `PYTHONPATH=release/source/src` 运行；客户可直接查看/修改 Python 和 Vue 源码。`web-dist` 是当前生产静态文件，不代替 `source/web`。

## 4. 发布链路

```text
目标架构基础 Python Runtime + 完整离线 wheelhouse
  ↓ scripts/prepare_runtime.py
runtime/ + runtime-manifest.json

Vue source + 已准备的离线 Node/依赖
  ↓ npm run build
web/dist

runtime + web/dist + 完整仓库源码
  ↓ scripts/build_native_source_bundle.py
source-visible release + release-manifest.json

release + 正式模型 + wheelhouse
  ↓ scripts/build_offline_bundle.py
offline media directory + offline-manifest.json
  ↓ installer/verify_offline_bundle.py
安装向导 / install.sh
```

任一步失败都不得跳过。

## 5. 构建 Runtime（由 OpenCode/构建机实际执行）

```bash
TARGET_ARCH=x86_64  # 或 aarch64
python3 scripts/prepare_runtime.py \
  --base-runtime-dir /release-input/python-base \
  --wheelhouse-dir /release-input/wheelhouse \
  --output-dir /release-work/runtime \
  --target-arch "$TARGET_ARCH"
```

脚本强制离线 pip 安装、`pip check`、关键 import、目标架构检查，并生成 `runtime-manifest.json` 和启动器。启动器指向 release 的 `source/src`。

## 6. 构建 Vue production dist

构建机必须提前准备 Node Runtime 和依赖；客户现场不应临时访问公网。

```bash
cd web
npm ci --no-audit --no-fund
npm run build
cd ..
```

安装后如果客户要在原生源码部署现场修改 Vue，使用 `tools/rebuild_frontend.sh`；该工具仅接受本地 Node runtime 与离线依赖，不联网下载。

## 7. 组装 Native Source Release

```bash
python3 scripts/build_native_source_bundle.py \
  --runtime-dir /release-work/runtime \
  --web-dist-dir web/dist \
  --output-dir /release-work/release \
  --target-arch "$TARGET_ARCH"
```

可选传入 `--git-commit`、`--build-time`。若未传 commit 且当前目录是 Git checkout，构建器会读取 HEAD。manifest 同时记录源码树、前端树和 Runtime manifest 的摘要。

## 8. 组装最终离线目录（源码已准备；大体积输入由 OpenCode 提供）

```bash
python3 scripts/build_offline_bundle.py \
  --release-dir /release-work/release \
  --model-dir /release-input/models/BAAI/bge-base-zh-v1.5 \
  --wheelhouse-dir /release-input/wheelhouse \
  --output-dir /release-output/material-matcher-${TARGET_ARCH} \
  --target-arch "$TARGET_ARCH" \
  --model-id BAAI/bge-base-zh-v1.5
```

最终目录会包含安装向导源码入口：

```text
安装物料集团码智能匹配平台.desktop
启动安装.sh
install_wizard.sh
install.sh
verify_offline_bundle.py
offline-manifest.json
release/
models/
wheelhouse/
```

组装器完成后自动运行 verifier。正式客户机再次运行 verifier 时不要使用 `--skip-arch`。

## 9. 三层完整性链

```text
runtime-manifest.json
        ↓ SHA-256
release-manifest.json
        ↓ SHA-256
offline-manifest.json
```

校验范围包括 Runtime 文件树、完整 source 树、web-dist、目标架构、版本一致性、模型/tokenizer、native wheels、启动器、安装向导和未登记/篡改文件。

## 10. 客户现场原生安装

普通用户参见 [KYLIN_V10_INSTALLATION_GUIDE.md](KYLIN_V10_INSTALLATION_GUIDE.md)。安装向导只询问安装路径、可选数据路径、端口、admin 密码/自动生成；底层仍由 `install.sh` 完成。

关键保护不得绕过：

- `/etc/material_matcher/storage.env` 是唯一数据目录；
- 配置数据目录和遗留目录同时存在 metadata DB 时拒绝继续；
- 升级前旧服务保持运行，先对新版本执行 doctor；
- doctor 通过后才进入短暂停机和 `current` 原子切换；
- 启动/readiness 失败恢复旧 release/model；
- 不清数据库、不清索引、不清结果、不重置已有账号。

## 11. Docker Source

Docker 源码见 `docker/`，详细步骤见 [KYLIN_V10_DOCKER_SOURCE_INSTALL.md](KYLIN_V10_DOCKER_SOURCE_INSTALL.md)。Compose 使用宿主机 bind mount 保存 `/data`、`/config`、`/logs`，不把 metadata DB 留在匿名 volume；`docker compose down` 不删除这些宿主机目录。

## 12. 关于系统与部署元数据

`/api/health` 只保留廉价的 `status/version`。登录后 `/api/about` 提供：

- 产品名称；
- version；
- build time；
- Git commit；
- deployment mode。

原生部署显示“原生源码部署”，Docker 部署显示“Docker 源码部署”。前端左栏的版本只读取当前后端实例，不维护静态版本号。

## 13. 维护与现场源码修改

参见 [KYLIN_V10_MAINTENANCE_GUIDE.md](KYLIN_V10_MAINTENANCE_GUIDE.md)。维护工具提供状态、启停、重启、日志、doctor、诊断包、备份、恢复、前端离线重建和版本查询。

安装成功只表示部署链路正常，不代表真实业务准确率/百万级规模验收通过；生产业务验收仍按项目 `agent.md` 和准确率基线执行。
