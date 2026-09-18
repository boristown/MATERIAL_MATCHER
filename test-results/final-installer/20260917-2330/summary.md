# MATERIAL_MATCHER 银河麒麟 V10 最终离线安装包 · 验收总结

日期：2026-09-17/18（UTC）
执行：OpenCode 构建 Agent（安装/升级/回滚）+ 三个相互独立的“非原厂操作员”会话（仅凭手册执行安装）

| 项 | 结果 |
|---|---|
| 手册冻结（#54 → main 9e94a55） | ✅ |
| 最终版本 / 冻结 commit | **1.1.22 / c4e974e72d39161a0f5678b3e4f4a23f9b4fa04f** |
| 最终介质 | MATERIAL_MATCHER-1.1.22-KylinV10-x86_64-offline.tar.gz（541,206,213 B） |
| 介质 SHA256 | ec722016e5f666e309ab8b82e5c60855559cf68c8d65d26b0c1cead995e78465 |
| Test A 首装（断网，Snapshot-0，仅凭手册） | ✅ PASS（testA6-run-operator.md） |
| Test B 无系统 Python | ✅ PASS（testB6-wizard.log） |
| Test C 端口冲突 | ✅ PASS（testC6-wizard.log，建议使用 18081 并成功） |
| Test D 损坏介质 | ✅ PASS（rc=41，系统零改动） |
| Test E 升级保数据 | ✅ PASS（1.1.15→1.1.22，DB inode 不变，users/tasks/sessions/files 全保留） |
| Test F 升级失败自动回滚 | ✅ PASS（rc=48，current 回旧版，服务恢复 active） |
| Test G 备份→验证→恢复 | ✅ PASS（中文菜单驱动；恢复前自动留存当前库） |
| Test H 非原厂模拟 | ✅ PASS（独立操作员会话，仅读手册；残留限制见 environment.md） |
| 最小业务 smoke STEP1-4 | ✅ 17/17（含首登改密、结果 Excel 下载 14KB） |
| 重启自动恢复 | ✅（docker restart 等价，5~16 秒） |
| 源码可见（app/ + source/web + scripts + installer + pyproject） | ✅（source-visibility.txt） |
| 前端离线重建（node-offline 248MB） | ✅（rebuild-frontend-offline.txt） |
| 全程断网（--network=none，0 路由） | ✅ |
| 密码不进入日志/诊断包/报告 | ✅（0600 权限、非 TTY 不打印） |
| **真实 VM 验收** | ⛔ **未完成 → 整体判定 PARTIAL**（宿主机无 qemu/libvirt 且仓库源不可达；容器仅可作预验收，按规范不能作最终 PASS 证据） |

## 总判定：**PARTIAL**
除“全新银河麒麟 V10 虚拟机最终验收”一项受基础设施限制未执行外，其余全部通过；
介质与流程已按验收合同就绪，可在取得 VM 条件后直接执行同一手册完成 VM 轮。
