银河麒麟 Linux Advanced Server V10 (Lance)，x86_64；宿主 SLES12-SP5 以 privileged systemd 容器模拟（镜像 mm/kylin-v10-snapshot0:20260917，每轮从 Snapshot-0 全新创建）。
网络：全部测试容器 --network=none（0 条路由），完全断网。
限制声明：容器非真实虚拟机——桌面 GUI/pkexec/物理 reboot/防火墙界面无法等价验证；reboot 以 docker restart 容器等效（如实标注）。Docker 存储为宿主 ext4 目录 bind 进容器 /var/lib/docker（测试台布置；正式客户机为本地磁盘）。
