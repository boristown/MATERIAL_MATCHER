# 银河麒麟 V10 · Docker 源码部署

## 适用场景

Docker 源码版用于客户允许 Docker/Compose、并希望源码在宿主机直接可见的环境。它不是“隐藏代码”的方案。`src/`、`web/`、`pyproject.toml` 都保留在宿主机；业务数据、配置和日志也全部使用宿主机 bind mount。

## 文件

```text
docker/
├── Dockerfile
├── compose.yaml
└── env.template
```

先复制配置模板：

```bash
cd docker
cp env.template .env
```

必须修改 `MM_ADMIN_PASSWORD`。数据目录、配置目录和日志目录默认是 `docker/data`、`docker/config`、`docker/logs`，也可以改成客户规定的绝对路径。

## 启动

联网/构建环境可直接：

```bash
docker compose build
docker compose up -d
```

银河麒麟离线现场不应临时访问公网。后续 OpenCode 应提前准备并导入 Python/Node 基础镜像或最终 Docker image tar，再使用同一份 `compose.yaml`。本 PR 只准备 Docker 构建与部署源码，不声称已经生成 image tar。

## 持久化规则

Compose 明确绑定：

```text
宿主机 MM_DATA_DIR   -> /data
宿主机 MM_CONFIG_DIR -> /config
宿主机 MM_LOG_DIR    -> /logs
宿主机 ../src        -> /app/src（只读）
宿主机 ../web        -> /app/web-source（只读）
宿主机 ../pyproject.toml -> /app/pyproject.toml（只读）
```

数据库位于 `MM_DATA_DIR` 下，不使用匿名 Docker volume。执行：

```bash
docker compose down
```

只停止/删除容器和网络，不会删除上述宿主机目录，因此不会因为 `down` 丢失 metadata DB、索引或结果。

## 源码修改

Python 运行时的 `PYTHONPATH=/app/src`，Compose 将宿主机 `src/` 绑定到该目录。修改 Python 后执行：

```bash
docker compose restart material-matcher
```

即可重新加载源码。

Vue production dist 在镜像构建阶段生成。修改 `web/` 后应在具备完整离线 Node 依赖的构建环境重新构建镜像：

```bash
docker compose build material-matcher
docker compose up -d material-matcher
```

原生源码部署如需现场直接重建 Vue，请使用 `tools/rebuild_frontend.sh`；Docker 部署建议通过重新构建镜像保持可复现性。

## 关于页面

容器固定设置：

```text
MATERIAL_MATCHER_DEPLOYMENT_MODE=docker-source
```

因此“系统设置 · 关于”会显示 **Docker 源码部署**。可在 `.env` 中提供 `MM_GIT_COMMIT` 和 `MM_BUILD_TIME`，便于现场确认构建来源。

## 注意

- 不要给 `/data` 使用匿名 volume。
- 不要把客户真实密码提交到 `.env.template` 或 Git。
- 数据备份仍应以宿主机 `MM_DATA_DIR` 为准。
- Python Runtime/基础镜像、Node Runtime/基础镜像、Docker image tar、离线 RPM 和最终离线介质均由后续 OpenCode 在目标环境制作和验证。
