# 物料集团码智能匹配平台 · 维护手册

安装完成后，系统提供中文维护入口，两种方式：

- 图形：双击安装介质中的「维护物料集团码智能匹配平台」或运行 `./维护工具.sh`；
- 命令行：`sudo mmctl <命令>`。

## 常用操作（维护菜单）

| 操作 | 命令行 | 说明 |
|---|---|---|
| 查看状态 | `mmctl status` | 服务是否运行、版本目录、健康检查 |
| 启动/停止/重启 | `mmctl start / stop / restart` | 服务生命周期 |
| 查看最近日志 | `mmctl logs [行数]` | 默认 80 行 |
| 健康诊断 | `mmctl doctor` | 检查运行环境、模型、前端、发布清单 |
| 查看版本 | `mmctl version` | 版本与 Git commit |
| 备份数据 | `mmctl backup [目录]` | 数据库一致性备份 + 配置，默认 /var/backups/material_matcher |
| 验证备份 | `mmctl verify <文件>` | 解包并检查数据库完整性 |
| 恢复数据 | `mmctl restore <文件>` | 恢复前自动保留当前库副本 |
| 导出诊断包 | `mmctl export` | 发给原厂；不含密码/会话/客户文件 |
| 前端离线重建 | `mmctl rebuild-frontend` | 高级：修改 source/web 后离线构建 |

## 目录约定

```text
/opt/material_matcher/current   当前版本（含 app 源码、web 源码与 dist、runtime）
/opt/material_matcher/releases  各版本目录
/etc/material_matcher           配置（storage.env 是数据目录唯一来源）
/var/lib/material_matcher       数据统一入口
/var/log/material_matcher       日志与安装报告
```

## 现场修改

- 修改 Python 代码：编辑 `/opt/material_matcher/current/app/material_matcher/` 下源码（或 `source/src/`，两者一致），保存后执行 `mmctl restart` 生效。
- 修改页面：编辑 `source/web/` 源码后执行 `mmctl rebuild-frontend`，再 `mmctl restart`。需要介质中的离线 Node 资源已安装（安装向导会自动放置到 `/opt/material_matcher/tools/node-offline`）。

## 升级

用新版本介质重复一次安装流程即可：向导会自动识别“升级安装”，保留账号、密码、任务、数据库、索引与结果；升级前自动执行备份窗口内的诊断，切换失败会自动回滚到旧版本。

## 数据保护红线

- 不要手工删除或移动 `/etc/material_matcher/storage.env` 指向的数据目录；
- 出现“检测到两份业务数据库”提示时立即停止，导出诊断包并联系原厂；
- 任何“重装前先备份”都可以通过维护菜单的备份功能完成。
