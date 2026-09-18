# MATERIAL_MATCHER 交付前最终验收安装记录（mm-cr-a6）

- 执行人角色：未参与开发的运维安装员；唯一参考：`manual-copy-安装手册-final.md`
- 环境：docker 容器 `mm-cr-a6`，Kylin Linux Advanced Server V10 (Lance)，x86_64，完全断网，无图形桌面/浏览器
- 介质：`/root/物料集团码智能匹配平台安装包`（BUILD_INFO：版本 1.1.22，commit c4e974e72d39161a0f5678b3e4f4a23f9b4fa04f，目标 x86_64/银河麒麟 V10）
- 前置核对（手册“你需要准备”）：OS=麒麟 V10 ✅；root ✅；磁盘可用约 838 GB ≥ 6 GB ✅；介质已复制到容器本地磁盘 ✅；架构与介质标注一致 ✅
- 时间线（容器主机时钟）：探测 08:22 → 正式安装 08:23:13–08:23:19（6 秒）→ curl 验收 08:23:19–08:23:37 → smoke 验收 08:23:37–08:23:38（17/17 通过，用时 1s）→ `docker restart mm-cr-a6` 08:23:46，08:23:51 恢复（等待 5 秒，符合“15~60 秒内验证”窗口）
- 全程日志：`testA6-wizard-full.log`；敏感值（密码明文）未写入本报告与本日志（已核验：日志中密码明文出现次数 = 0）

## 执行过程

1. 按替代表以终端方式启动：`printf '...' | docker exec -i mm-cr-a6 bash -c 'cd "/root/物料集团码智能匹配平台安装包" && ./启动安装.sh' 2>&1 | tee 日志`
2. 正式运行前用空输入探测一次首个提示（向导按手册“其它键安全退出”，探测以 EOF 退出并提示“用户已取消，未对系统做任何修改”，无副作用），确认输入顺序后一次性给全答案：回车（默认位置）→ y（数据自动选择）→ 回车（默认端口 18080）→ n（自动生成密码）→ y（确认安装）。
3. 向导全程：欢迎→环境检查 6 项全 ✅ + ℹ️“首次安装”→安装位置→数据位置→端口→密码→确认→进度 1%–100%→【安装成功】页面。退出码 0。
4. 安装后核对：密码文件 `/etc/material_matcher/secret/admin_password.env` 权限 `-rw------- root` ✅；过程日志 `/var/tmp/material_matcher_wizard-20260918-002313.log` 存在（与手册默认路径模式一致）✅；安装报告 `/var/log/material_matcher/install-reports/install-20260918-002319.txt` ✅。

## 替代表执行情况（逐项标注）

| 手册要求 | 替代表 | 实际执行 | 结果 |
|---|---|---|---|
| 浏览器打开地址登录 | 无浏览器→curl health/ready/GET / | `curl http://127.0.0.1:18080/api/health` → `{"status":"ok","version":"1.1.22"}`；`/api/ready` 需登录（401，由 smoke 登录态验证为 `{"status":"ready", checks 全 true}`）；`GET /` → HTTP 200 前端页面 | ✅ |
| 图形双击 .desktop | 无图形→终端 ./启动安装.sh | 终端管道方式运行 `./启动安装.sh` | ✅ |
| 最小业务验收（上传/匹配/导出） | 原厂工具 `./bootstrap/python/bin/python3 tools/installer_smoke.py --base-url http://127.0.0.1:18080 --password-file /etc/material_matcher/secret/admin_password.env --smoke-dir smoke` | 按替代表原样执行 | SMOKE 17/17 passed ✅ |
| 重启服务器 | `docker restart mm-cr-a6` 后 15~60 秒验证 | restart 后每 5 秒探测，5 秒恢复 HTTP 200，`systemctl is-active` = active（自启 enabled，安装时见 symlink 到 multi-user.target） | ✅ |

## 必答三问

**(a) 有无 >30 秒无输出？**
无。全程带毫秒时间戳监测：最长静默间隔出现在“[3%] 校验安装介质完整性”阶段约 2.7 秒；其余间隔 <1 秒；smoke 与重启验收阶段每步均有输出。

**(b) 有无替代表之外命令？**
有，均为只读核对或探测，不属安装/验收核心动作，如实列出：
1. `docker ps`、介质目录 `ls`；
2. 读取介质文本《README-安装前必读.txt》《BUILD_INFO.txt》及 `/etc/os-release`、`df`、`uname -m`（手册“准备/核对”要求的只读核对）；
3. 一次 `printf '' | ./启动安装.sh` 空输入探测（向导安全退出、零修改，用于确认提示顺序，随后正式一次性作答）；
4. curl 多探测了 `/health /healthz /ready`（返回 SPA 页面 200，无碍）与对已下载的 index.html 做 `grep`（查版本号）；
5. 重启后 `systemctl is-active material_matcher`、密码文件 `ls -l`（只查权限不读内容）。

**(c) 手册与屏幕是否逐项一致？（含文件名/按钮/按键文字）**
逐项一致，无不一致。核对点：
- 文件名：`启动安装.sh`、`维护物料集团码智能匹配平台.desktop`（屏幕提示“维护工具.sh 或 mmctl”手册第 41 行亦称“维护工具”）— 一致；
- 向导顺序（欢迎→环境检查→安装位置→数据位置→服务端口→管理员密码→确认安装→安装进度→【安装成功】）与手册 3.1–3.8 — 一致；
- 按键文字：环境检查逐项 ✅ 并以 ℹ️ 行显示“本次为首次安装”；位置“直接回车使用默认值 [/opt/material_matcher]”；数据“输入 y 自动选择 / n 手工指定（高级）/ 其它键退出”；端口“默认 18080 直接回车”；密码“y 手工输入 / n 自动生成”；确认“终端输入 y” — 与手册逐字语义一致；
- 密码安全策略：非交互（管道）下密码不回显、仅写入 root-only `/etc/material_matcher/secret/admin_password.env`，屏幕明示“本输出与安装日志不包含密码明文” — 与手册第 26 行一致；
- 进度阶段文字（校验介质、复制程序、安装模型、环境诊断、启动服务、验证就绪等）— 与手册 3.8 一致；
- 日志路径 `/var/tmp/material_matcher_wizard-*.log` — 与手册第 40 行默认值一致；
- 首登强制改密提示 — 屏幕与手册第 29 行一致（smoke STEP0“首次登录修改密码”通过佐证）；
- 仅图形相关项（双击/按钮「继续」/鼠标点击）本环境不适用，按替代表以终端执行，不构成不一致。
- 屏幕额外提示“未检测到局域网 IPv4 地址：当前仅本机可访问”属容器网络环境的如实检测，非手册矛盾。

## 结论

**PASS**

手册“安装步骤 1-5 + 最小验收 1-5”逐项勾对表：

| 项 | 手册条目 | 执行情况 | 结果 |
|---|---|---|---|
| 安装步骤 1 | 复制介质到服务器本地磁盘 | 介质已在容器本地 `/root/物料集团码智能匹配平台安装包` | ✅ |
| 安装步骤 2 | 启动安装（无图形→`./启动安装.sh`） | 终端启动成功 | ✅（替代表） |
| 安装步骤 3 | 按向导提示操作（8 个子步） | 全 ✅ 通过；回车/y/回车/n/y 一次成功 | ✅ |
| 安装步骤 4 | 【安装成功】页面+浏览器登录+首登改密 | 页面出现；无浏览器→curl GET / 200；首登改密由 smoke STEP0 验证 | ✅（替代表） |
| 安装步骤 5 | 最小验收 1-5 | 见下行 5 项 | ✅ |
| 验收 5.1 | 登录成功 | smoke “STEP0 admin 登录 PASS” | ✅ |
| 验收 5.2 | 关于版本与 BUILD_INFO 一致 | `/api/health` version=1.1.22 与 BUILD_INFO 1.1.22（commit 亦与确认页一致） | ✅（curl 替代“关于”页） |
| 验收 5.3 | 上传 smoke 两个 xlsx 并启动匹配 | smoke STEP1 上传待匹配/集团标准/建目录/草稿/启动匹配全 PASS | ✅ |
| 验收 5.4 | 第二步进度、第三步结果、第四步导出 Excel | smoke STEP2 COMPLETED、STEP3 明细 PASS、STEP4 导出+下载 bytes=14871 | ✅ |
| 验收 5.5 | 重启后服务自动恢复 | docker restart 后 5 秒 HTTP 200，systemd active/enabled | ✅ |
