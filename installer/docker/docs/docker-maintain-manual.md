# 物料集团码智能匹配平台 · 维护手册（Docker 方式 · 介质版）

以 root 运行介质内 `./menu.sh`（中文菜单），或命令行：

```bash
sudo ./menu.sh status     # 查看状态
sudo ./menu.sh restart    # 重启服务
sudo ./menu.sh logs       # 最近日志
sudo ./menu.sh doctor     # 健康诊断（前端/模型/版本清单）
sudo ./menu.sh backup     # 备份（数据库一致性备份+配置，root-only）
sudo ./menu.sh verify <备份文件>
sudo ./menu.sh restore <备份文件>   # 恢复前自动留存当前库
sudo ./menu.sh export     # 导出诊断包（不含密码/会话/客户数据）
sudo ./menu.sh version
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
- **端口冲突**：运行 `./run.sh` 升级流程时选择新端口。
- **磁盘满**：先 `backup` 备份，再清理，或迁移 `/var/lib/material_matcher` 到大磁盘（迁移后联系维护人员确认）。
- **需要完全重装（保数据）**：`docker rm -f material_matcher-app` 不会删除宿主机数据；重新运行安装向导即可在原数据上重建。
- **开机自启**：安装器已启用 docker.service 并将容器设为自动重启策略；重启服务器后服务自动恢复。

## 安全边界

- 维护工具仅操作 material_matcher 项目自身容器；不会执行 prune、不会修改其它容器；
- 备份与诊断包权限均为 root-only；诊断包不包含密码明文、会话、客户 Excel 正文与完整数据库。

## 磁盘清理（clean.sh）

平台上传文件具备**自动去重**：同名或不同名但内容（SHA-256）与字节数完全一致的 Excel，
只会保存一份物理文件，多次上传直接引用原文件，不重复占用磁盘。

随介质提供清理工具（以 root 在介质目录运行，两种安装方式通用）：

    ./clean.sh            # 预演：列出可回收的孤立上传/结果文件、过期临时分块、过旧备份
    ./clean.sh --apply    # 实际回收：文件移入数据目录 .trash/ 回收区（不物理删除，管理员确认后可再删）

说明：
- “孤立文件”＝不再被任何任务、草稿、标准目录或结果引用的上传文件；
- 备份自动保留最近 7 份（--keep-backups=N 可调）；超过 7 天的分块上传临时文件可回收（--tmp-days=N）；
- 建议每季度执行一次，先预演后 --apply。
