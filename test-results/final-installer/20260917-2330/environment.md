# Clean-room 环境

- 宿主：SUSE Linux Enterprise Server 12-SP5 x86_64（运维服务器；磁盘检查见下）
- 磁盘：/ 149G/200G 使用、/oracle 2.2T/3.0T 使用（可用 830G+）。未清理任何旧容器/镜像，未运行任何 prune。
  xiaogang 平台既有容器/卷/ISO 全部原位保留（空间充足，按规则不动）。
- 客户机模拟：镜像 `mm/kylin-v10-snapshot0:20260917`（ID ac6e7059573f，commit 自
  `xiaogang/kylin-v10-sp3-cleanroom:20260906` 全新启动态，未含任何项目文件）
  - Kylin Linux Advanced Server V10 (Lance)，systemd 为 PID 1（容器化 systemd，privileged + cgroupns=host）
  - 每次测试从该 snapshot 新建容器（等效 "SNAPSHOT-0-CLEAN 恢复"）
- 网络：所有测试容器 `--network=none`（`ip route` 输出 0 条），全程物理断公网；
  介质在联网构建机预构建，安装期间无任何 PyPI/npm/GitHub/HF 需求。
- Clean-room 初始状态：无项目 Python 环境、无 node、无 wheelhouse、无模型、无源码、无 systemd 单元、
  无 /etc/material_matcher、无 material_matcher 用户（每容器启动时核验）。
- 已知环境差异（如实申报）：
  1. 非物理机/虚拟机：桌面双击、pkexec 授权弹窗、防火墙、真实重启无法在容器内完整等价验证；
     向导在无 DISPLAY 时按手册走“终端 ./启动安装.sh”分支（手册明示的合法路径）。
  2. 容器时钟为 UTC，宿主为 UTC+8，日志时间戳差 8 小时。
  3. VM 条件不具备：宿主机无 qemu/kvm 工具链、zypper 仓库源不可达、无麒麟 ISO（检索全盘仅 xiaogang 介质盘）。
     故本轮为“预验收 + 完整功能/安全矩阵”，VM 轮列为剩余项。
