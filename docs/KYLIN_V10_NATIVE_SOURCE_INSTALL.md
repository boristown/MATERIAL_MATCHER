# 银河麒麟 V10 · 原生源码部署

## 目标

原生部署保留完整应用源码，正式后端直接从 `release/source/src` 运行，Vue 源码保存在 `release/source/web`。生产前端静态文件独立位于 `release/web-dist`。这套结构便于客户内网现场审查和修改源码，不以隐藏 Python/Vue 源码为目标。

## Release 目录

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

`release-manifest.json` 的 `release_version` 来自 `pyproject.toml`，同时记录 `git_commit`、`build_time`、`deployment_mode=native-source`、源码和前端摘要。不要在构建脚本或安装向导中再维护第二份版本号。

## 源码级组装流程

本仓库提供构建源码，但本 PR 不生成最终大型运行时或安装介质。后续 OpenCode/构建机按以下顺序执行：

```bash
# 1. OpenCode 准备离线 Python runtime 与 wheelhouse（本仓库不内置二进制 runtime）
python3 scripts/prepare_runtime.py \
  --base-runtime-dir <base-runtime> \
  --wheelhouse-dir <wheelhouse> \
  --output-dir <python-runtime> \
  --target-arch x86_64

# 2. 在有离线前端依赖的构建机生成 production dist
cd web
npm ci
npm run build
cd ..

# 3. 组装源码可见 release
python3 scripts/build_native_source_bundle.py \
  --runtime-dir <python-runtime> \
  --web-dist-dir web/dist \
  --output-dir <release-dir> \
  --target-arch x86_64

# 4. 后续再由 OpenCode 准备模型/wheelhouse并组装最终离线介质
python3 scripts/build_offline_bundle.py \
  --release-dir <release-dir> \
  --model-dir <model-dir> \
  --wheelhouse-dir <wheelhouse> \
  --output-dir <offline-media> \
  --target-arch x86_64
```

`--release-version` 仅作为可选一致性校验；正常情况下构建脚本直接读取 `pyproject.toml`。

## 安装入口

最终介质根目录包含：

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

普通用户优先双击 `.desktop`。图形环境有 `zenity` 时使用 Zenity，有 `kdialog` 时使用 KDialog；都没有时自动退化为终端交互。向导最终仍调用 `install.sh`，不会绕开底层数据保护逻辑。

## 数据安全与升级

`/etc/material_matcher/storage.env` 是持久化数据目录的唯一来源。已有安装再次运行向导时，如果用户选择的数据目录与 `storage.env` 不一致，安装器会拒绝自动切换。若配置数据目录和遗留 `/var/lib/material_matcher` 同时存在 metadata DB，也会拒绝继续。

升级时顺序是：校验离线介质 → 将新 release 放入版本目录 → 旧服务仍运行时对新版本执行 doctor → 短暂停服务 → 原子切换 `current` → 启动并 readiness 检查。启动或 readiness 失败则恢复旧 release/model 链接。安装器不删除数据库、索引、结果，也不会因升级重置已有账号。

## 运行路径

systemd 服务通过：

```text
PYTHONPATH=<install-root>/current/source/src
MATERIAL_MATCHER_WEB_DIST_DIR=<install-root>/current/web-dist
MATERIAL_MATCHER_RELEASE_MANIFEST=<install-root>/current/release-manifest.json
MATERIAL_MATCHER_DEPLOYMENT_MODE=native-source
```

启动 `runtime/bin/material-matcher`。因此客户现场修改 Python 源码后重启服务即可加载；修改 Vue 后请使用 `tools/rebuild_frontend.sh` 进行离线构建和安全切换。

## 边界

本仓库阶段完成的是构建脚本、安装器源码、维护工具和文档。Python Runtime 二进制包、Node Runtime 二进制包、离线 npm 依赖、Docker image tar、离线 RPM 和最终大型安装介质仍由后续 OpenCode Agent 在目标架构/麒麟环境实际制作并验收。
