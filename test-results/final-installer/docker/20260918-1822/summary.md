# Docker 轨验收总结 —— PASS

- 版本 1.2.3；介质 `MATERIAL_MATCHER-1.2.3-KylinV10-x86_64-双轨最终交付介质.tar.gz`（1,238,273,754 字节 ≈ 1.24 GB，SHA256 `712ddf6fdb629f78…`）。
- 非原厂操作员仅凭介质内手册在**无 Docker 的全新麒麟环境**一次装成：引擎 27.1.1 → Compose v2.29.7 → 镜像导入 → ready → 6 方案+同义词自动预置 → smoke 22/22 → 环境重启 5 秒自动恢复（operator-run.md/wizard-full.log@20260918-1822）。
- 机械矩阵（20260918-1653；1.2.2→1.2.3 仅手册文字差异）：已有 Docker 复用、无关容器/images/volumes 零影响；端口冲突→18081 成功；损坏介质 rc=41 零改动（1.2.3 复验）；重复安装 no-op+seed skip+方案不重复；容器删除重建数据完整；坏镜像升级 rc=48 自动回滚；菜单备份/验证/恢复；诊断包无密码；docker.service 自启。
- 无手册外 workaround（操作员必答 (b)=无）。
