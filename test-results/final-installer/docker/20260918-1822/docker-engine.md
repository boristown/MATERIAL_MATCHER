docker-27.1.1.tgz（Docker Inc 官方静态发布，含 dockerd/cli/containerd/runc/shim，Apache-2.0）。安装经 systemd 单元；已有 Docker（≥20.10）→ 复用不覆盖；不兼容 → rc=50 明示停止；绝无 prune/清理动作（testB-existing.log 中 images/volumes 计数前后不变）。
