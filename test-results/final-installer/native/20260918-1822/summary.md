# Native（非 Docker）轨验收总结 —— PASS

- 同一最终介质 1.2.3 的 02-非Docker方式（独立完整，不含 Docker 依赖）。
- 非原厂操作员一次跑通：`./启动本地安装.sh` 9 秒装完 → ready → 6 方案+同义词自动预置 → smoke 22/22 → 重启 ~3 秒自恢复（20260918-1822/operator-run.md，一次成功）。
- 机械矩阵（20260918-1653/20260918-1822）：无系统 Python 首装（bootstrap）；重复安装 no-op；损坏介质 rc=41 零改动；坏构建升级 rc=48 自动回滚（current/model 复原）；菜单备份/验证/恢复；诊断包无密码；systemd enabled。
- 真实升级链：1.1.15（旧空壳+任务数据）→ 1.2.x：端口 29206/密码保持、DB inode 不变、seed 自动补齐；客户修改（A002 v4 threshold 91）经再次安装不被覆盖。
