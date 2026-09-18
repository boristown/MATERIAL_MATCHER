# 物料集团码智能匹配平台 · 维护手册（Docker 方式 · 介质版）

以 root 运行介质内 `./维护工具-Docker.sh`（中文菜单），或命令行：

```bash
sudo ./维护工具-Docker.sh status     # 查看状态
sudo ./维护工具-Docker.sh restart    # 重启服务
sudo ./维护工具-Docker.sh logs       # 最近日志
sudo ./维护工具-Docker.sh doctor     # 健康诊断（前端/模型/版本清单）
sudo ./维护工具-Docker.sh backup     # 备份（数据库一致性备份+配置，root-only）
sudo ./维护工具-Docker.sh verify <备份文件>
sudo ./维护工具-Docker.sh restore <备份文件>   # 恢复前自动留存当前库
sudo ./维护工具-Docker.sh export     # 导出诊断包（不含密码/会话/客户数据）
sudo ./维护工具-Docker.sh version
```

## 目录约定

```text
/etc/material_matcher        配置（docker.env：镜像标签与端口；secret/ 仅 root 可读）
/var/lib/material_matcher    业务数据（容器 bind mount，删除容器不丢数据）
/var/log/material_matcher    日志与安装报告
/opt/material_matcher/docker Compose 项目目录
```

## 常见问题

- **升级后打不开**：`status` 看容器是否 running；`logs` 看最后输出；必要时导出诊断包联系原厂。
- **端口冲突**：运行 `./启动Docker安装.sh` 升级流程时选择新端口。
- **磁盘满**：先 `backup` 备份，再清理，或迁移 `/var/lib/material_matcher` 到大磁盘（迁移后联系维护人员确认）。
- **需要完全重装（保数据）**：`docker rm -f material_matcher-app` 不会删除宿主机数据；重新运行安装向导即可在原数据上重建。
- **开机自启**：安装器已启用 docker.service 并将容器设为自动重启策略；重启服务器后服务自动恢复。

## 安全边界

- 维护工具仅操作 material_matcher 项目自身容器；不会执行 prune、不会修改其它容器；
- 备份与诊断包权限均为 root-only；诊断包不包含密码明文、会话、客户 Excel 正文与完整数据库。
