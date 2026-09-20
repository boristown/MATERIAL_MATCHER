# 1.2.9 介质三场景验证记录（增量合入 main e0a4d4d：Composite/双模板/固定值/源过滤）

日期：2026-09-20（UTC+8）。介质：mm-1.2.9-x86_64.tar.gz（1,238,461,311 B，
SHA256 5eb263ba9d0baff0adb9282ad029e6ba571493cfd0dffee9fd19b6fd41ebffc1，构建源码 main `e0a4d4d…`）。

## 1. Docker 轨全新安装（洁净室 mm/kylin-v10-snapshot0，mm-airgap 网络）

见 `docker-fresh-cleanroom.log`：rc=0。
- 成功页修复实测（#82/#89b）：`· 局域网访问：http://172.30.88.51:18080` 正常显示；`· 默认业务数据：新增方案 6 个，跳过已有 0 个；同义词表新增 1 张` 完整显示（结果文件交接 `/var/lib/material_matcher/install/last_result.json`）
- #89a 实测：`/var/log/material_matcher`、`/var/lib/material_matcher` 均 symlink 至选定磁盘；安装报告落在数据盘 `install-reports/docker-install-20260920-073050.txt`（目录迁移后重建修复，报告不再丢失）
- data-root 设入选定盘；`/api/health` → `{"status":"ok","version":"1.2.9"}`
- SMOKE **22/22 passed**（6 方案、词表链、批删 API、A007 STEP1→4 + Excel 下载）

## 2. Native 轨全新安装（洁净室，无 Docker）

见 `native-fresh-cleanroom.log`：rc=0；`局域网访问地址：http://172.30.88.53:18080`、种子摘要完整；结果 JSON `git_commit=e0a4d4d5361c0e73cc8524794752dcec759c49c9`；health 1.2.9；SMOKE **22/22 passed**。

## 3. 客户机增量升级（真实已安装环境 1.2.8→1.2.9，Docker 轨）

见 `customer-upgrade-1.2.8-to-1.2.9.log`（mm-customer，此前人肉安装的真实主机）。

升级前基线：db md5 `3783554441…`、inode `3525775129`、profiles=6/dicts=1、admin hash `6d224127`、无 child 列、镜像 1.2.8。

向导行为（正是"一个包重跑自动升级"路径）：
- 自动检测 →「检测到已安装的 Docker 方式系统（端口 18080）：本次为升级，业务数据保留」
- 端口保留 18080；「升级安装保留现有 admin 账号与密码，不会重置任何登录信息」；确认 y → rc=0

升级后验证：
- health 1.2.9；容器 Up；`docker.service` enabled 不变
- **数据保护**：profiles=6/dicts=1 不变；admin hash `6d224127` 不变（密码未重置）；**db inode 不变**（原地迁移，未重建文件）
- **前向迁移生效（非破坏式）**：`match_candidates.child_profile_id/child_profile_version/child_profile_name/target_file_id/target_file_name` 出现；`task_draft_targets` 表创建；无任何人工 SQL
- **回滚点**：镜像保留 1.2.8 与 previous；compose 卷/数据未动
- 公网隧道 http://39.104.206.210:18080/（mat2）→ 200

## 4. 生产上线（mat.bjlzc.cn 本机 18160，见 ops/deploy-evidence/2026-09-20-upgrade-1.2.9-composite.md）

- 同一 release 制品（release-129）经 install.sh 升级：rc=0，端口 18160 保留、password_source=existing、种子幂等（0 新增 / 6 跳过 + 1 词表跳过）
- 迁移与数据计数逐项核对通过（tasks=26/files=72/items=4048 不变；child 列/新表到位；previous→1.1.24 回滚点）
- 公网 https://mat.bjlzc.cn/ 200，新前端 dist index-CfG58va9.js

## 测试门禁（合入前）

pytest 235 passed（含 #92/#94/#95/#96/#97 全部新业务测试）；evaluate_matching_quality / diagnose_matching_scores / compileall / npm build（vue-tsc+vite+契约测试）/ bash -n / check_repo_files 全绿。

## 已知非阻塞

- Win7 浏览器实测仍在客户侧（介质含 Firefox ESR 官方包；Chrome 已获客户豁免）
- 物理重启等价测试为容器内 docker restart
