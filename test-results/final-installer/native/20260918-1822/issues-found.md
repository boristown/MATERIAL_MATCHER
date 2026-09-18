最终轮无新缺陷。本周期修复：#72 pipefail（native 在无全局网卡容器内 96% 后 rc=1——修复后 1.2.2/1.2.3 全绿）；#71 LAN。观察项：smoke 改密后的新密码缓存于 /var/tmp/mm-smoke-admin.pw（0600，root），建议维护文档补注（docs 级）。
