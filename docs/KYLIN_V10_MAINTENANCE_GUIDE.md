# 银河麒麟 V10 · 维护指南

安装后的维护入口位于当前 release 的 `tools/`。普通维护人员优先运行：

```bash
./tools/维护工具.sh
```

也可以直接使用：

```bash
./tools/mmctl.sh <命令>
```

## 常用操作

```bash
./tools/mmctl.sh status             # 查看服务状态
./tools/mmctl.sh start              # 启动
./tools/mmctl.sh stop               # 停止
./tools/mmctl.sh restart            # 重启并做 readiness 检查
./tools/mmctl.sh logs               # 查看/跟踪 systemd 日志
./tools/mmctl.sh doctor             # 检查目录、前端、版本链等
./tools/mmctl.sh diagnostics .       # 导出诊断包，不包含 admin 密码
./tools/mmctl.sh version            # 查看版本、构建时间、commit、部署方式
```

## 备份

```bash
./tools/mmctl.sh backup /安全磁盘/material_matcher_backup.tar.gz
```

为保证 SQLite 备份一致性，工具会在备份期间短暂停止服务，并在完成后恢复原运行状态。备份覆盖 `storage.env` 当前指向的数据目录，包括 metadata DB、上传文件、结果、索引和缓存。

## 恢复

```bash
./tools/mmctl.sh restore /安全磁盘/material_matcher_backup.tar.gz
```

恢复不是“覆盖原目录”。工具会：

1. 检查压缩包路径安全性；
2. 解压到新的 `material_matcher_restore_时间` 目录；
3. 确认存在 `meta/material_matcher.db`；
4. 备份现有 `storage.env`；
5. 短暂停服并把 `storage.env` 指向新目录；
6. 启动并做 readiness 检查；
7. 如果失败，恢复原 `storage.env` 并重新启动旧数据；
8. 成功后仍保留旧数据目录，不自动删除。

因此恢复操作不会先清空现有数据库/索引/结果。

## 导出诊断包

```bash
./tools/mmctl.sh diagnostics /tmp
```

诊断包包含服务状态、最近 systemd 日志、doctor 输出、health/readiness、release manifest、`storage.env` 和 `server.env`。**不会打包 admin 密码文件**。

## 离线重建 Vue 前端

```bash
./tools/rebuild_frontend.sh
```

工具只使用本地资源，不联网。它按以下顺序查找 Node/依赖：

- `tools/node-runtime/bin/node`，或 `MATERIAL_MATCHER_NODE_HOME` 指定的 runtime；
- `tools/frontend-node_modules`；
- 或 `tools/npm-cache`，通过 `npm ci --offline` 安装。

这些 Node Runtime 和离线 npm 依赖由后续 OpenCode Agent 制作，本仓库只提供重建流程源码。

重建过程：复制 `source/web` 到临时目录 → 离线构建 → 校验 `dist/index.html` → 在同一文件系统生成新 `web-dist` → 备份旧 dist → 原子切换 → 调用本机 `/api/health` 并访问首页。健康检查失败时自动恢复旧 dist。

## 数据目录原则

始终以：

```text
/etc/material_matcher/storage.env
```

中的 `MATERIAL_MATCHER_DATA_DIR` 为唯一数据目录来源。不要手工在其它位置再创建一份 `material_matcher.db`。安装器发现配置目录与遗留目录各有一份 metadata DB 时会停止并要求人工确认，避免误启空库造成“账号/数据消失”的假象。

## 升级原则

不要删除：

- metadata DB；
- indexes；
- results；
- uploads；
- 账号数据。

正式升级继续使用安装向导/`install.sh`。新版本在旧服务仍运行时先执行 doctor，只有检查通过后才进入短暂停机和原子切换；失败会回滚 release/model 链接。
