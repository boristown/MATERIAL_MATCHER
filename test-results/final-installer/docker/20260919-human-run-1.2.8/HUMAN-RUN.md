# 人工断网离线部署记录 · 第 2 轮（短路径版）· Docker 方式 · 介质 1.2.8

- 时间：2026-09-19 16:37–16:38（容器内 08:38 安装报告）
- 环境：mm-customer 全新空白（no-docker / 0 残留 / internal 网络无出口）+ 第二盘 /data2
- 接入：frp SSH（17470）→ 麒麟机；介质 /root/mm/mm-1.2.8-x86_64.tar.gz（SHA 7aea0d7a…，OK）
- 操作人：项目负责人，全程人工，未用任何手册外命令

## 执行序列与结果
1. `sha256sum -c sha.txt` → OK
2. 解包 10 秒 → `sha256sum -c all.sha256 | grep -cv ': OK$'` → **0**（全量逐文件）
3. `cd d && ./run.sh` → 向导：环境检查 8✅ → **新增数据盘屏生效**（列出前二名并推荐 /var/lib/docker 676G，人工 y 接受）→ 端口回车 → 密码 n（一次性显示，已脱敏）→ 确认 y
4. 进度屏连续（无 >30s 静默），镜像导入在缓存环境数秒完成
5. 安装报告 docker-install-20260919-083809.txt：版本 1.2.8 / commit fd3cd175 / 引擎 27.1.1 / Compose 2297 / data-root=/var/lib/docker/docker-data / 数据盘落位确认

## 装后取证（只读，见 post-install-verification.log）
- frp 公网口 `http://39.104.206.210:18080/` → **200**（= mat2 域名路径）
- 容器 Up、docker.service enabled、health 1.2.8、ready
- **6 个方案逐一在列**、同义词 3 版本、admin must_change=1（首登改密策略正常）
- /var/lib/material_matcher → /var/lib/docker/material_matcher_data/lib（软链落盘推荐盘）

## 结论：**PASS**（短路径版人工一键成功，全程 <2 分钟命令时间；数据盘选择屏按设计工作）

## 新发现（非阻断，已立 issue 跟踪）
1. 提示文案 `/var/log/material_matcher 已有既有数据，保持原位` 在全新安装上也出现——因安装流程在落盘迁移前预建了 LOG/install-reports 目录，导致日志目录不迁移到所选盘（数据目录正常迁移）；真实双盘机器上会造成日志留在小系统盘。→ 修复：迁移判定把"本次安装自建目录"视为可迁移。
2. 成功页"未检测到局域网 IPv4"与尾屏实际地址并存（issue #82 同源显示问题）；"默认业务数据：已导入"未按详情计数显示——同属显示级。
