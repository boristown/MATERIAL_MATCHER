# MATERIAL_MATCHER 增量升级包 1.3.14/15/16/19 → 1.3.20
集成五项：#162 有界并发匹配+LSH召回（含可观测心跳/ETA）、#163 映射未匹配显示修复、#164 有效行数统计、#166 操作区对齐间距、#167 canonical 版本单源（左下角/登录页真实版本）。

- 用法（root，宿主机）：`tar -xzf MATERIAL_MATCHER-增量升级-1.3.16-to-1.3.20.zip && cd MATERIAL_MATCHER-增量升级-1.3.16-to-1.3.20 && ./upgrade.sh`
  自动识别 Docker/Native；Docker 可显式 `./upgrade.sh --docker 容器名`，Native 用 `./upgrade.sh --native`。
- 升级前**强制预检**：包体 SHA 校验 + 当前版本必须 ∈ {1.3.14,1.3.15,1.3.16,1.3.19}；不符即中止，不改动任何数据。
- 自动备份（升级前）：应用目录、前端 dist、数据库（sqlite 在线备份）、上传清单、/etc/material_matcher。备份位置 `/var/lib/material_matcher/backups/incremental-1.3.20-<时间戳>/`。
- 数据库**不做任何破坏性操作**；新增列由启动期前向迁移自动完成。方案/任务/同义词/上传文件全部保留。
- 回滚：`./rollback.sh`（按最近一次备份恢复代码与前端并重启）。
- 完成判据：`/api/health` 返回 `"version":"1.3.20"`；页面左下角显示 `小罡 AI · v1.3.20`。
- #162 说明：本版为工程实现+合成基准（CI 实测 40k×1M 冷跑 14.36 分钟，4vCPU/16G、合成32维向量）。**生产 BGE 模型 + 客户数据口径的正式验收尚未完成**（issue 保持 open），验收命令见包内 docs/验收清单.md 与仓库 docs/performance/issue-162.md。
