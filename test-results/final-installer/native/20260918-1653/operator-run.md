# MATERIAL_MATCHER 1.2.2 最终验收安装记录（Native / 非 Docker 方式）

- 操作角色：未参与项目开发的运维安装员；唯一参考资料 = `manual-copy-安装手册-非Docker方式.md`（md5 `7d98048e5c827e56cf52206f424daa36`，与介质内 `安装手册-非Docker方式.md` 逐字节一致）。
- 环境：容器 `mm-fn-a`（银河麒麟 V10，x86_64，完全断网，无图形/浏览器），介质目录 `/root/MATERIAL_MATCHER-最终离线交付介质-1.2.2-x86_64/02-非Docker方式`。
- 纪律：全程未打开任何介质脚本内容（install.sh / install_wizard.sh / mmctl / verify_offline_bundle.py 等仅按手册与替代表“运行”，其 `--help`/`status`/`version` 属程序屏幕输出）；未读取 MATERIAL_MATCHER 仓库。
- 屏幕全量输出：`wizard-full.log`（正式向导一次运行）；辅助：`precheck-dryrun1-安全退出.log`、`precheck-dryrun2-安全退出.log`、`restart-verify.log`。
- 日期：2026-09-18（主机时间 UTC+8；容器内 UTC）。

## 时间线（主机时刻）

| 时刻 | 动作 |
|---|---|
| 17:54:34 | 环境预检：/opt、/etc/material_matcher、systemd 单元均为空 → 干净首次安装环境 |
| 17:54–17:55 | 两次屏幕探查（dry-run，输入“x”/“⏎ y⏎”）→ 均按手册承诺**安全退出、零改动**（`用户已取消，未对系统做任何修改。`；前后核查无新文件/无服务/数据目录未建） |
| **17:55:32–17:55:40** | **正式一次性运行向导：`printf '\ny\n\nn\ny\n' \| ./启动本地安装.sh` → RC=0，耗时 8 秒** |
| 17:56 | 替代表验证：/api/health、/api/health/ready、GET / |
| 17:56:23–17:56:40 | 原厂工具 installer_smoke.py → **22/22 passed in 1s**（随后 `rm -rf tools/__pycache__` 已执行） |
| 17:57 | 登录会话采集 6 方案名称清单、同义词版本证据 |
| 17:58:09→17:58:28 | `docker restart mm-fn-a`，**19 秒**后服务 active、health/ready 通过（15~60 秒窗口内） |

总耗时（环境预检→重启验证完成）≈ **3 分 54 秒**；其中向导本体 8 秒。

## 向导逐屏作答（答案序列 `\n` `y` `\n` `n` `y`）

| 屏 | 手册条目 | 屏幕原文（摘要） | 作答 | 依据 |
|---|---|---|---|---|
| 欢迎 | 3.1 | “正在自动检查运行环境……” | 无输入 | 终端自动开始检查 |
| 环境检查 | 3.2 | 6 项全 ✅ + `ℹ️ 未检测到已安装版本：本次为首次安装` | 自动 | — |
| 安装位置 | 3.3 | `程序安装位置（直接回车使用默认值） [/opt/material_matcher]：` | ⏎（默认） | 手册：直接回车 |
| 数据位置 | 3.4 | `请输入 y = 自动选择；n = 手工指定（高级）；其它键 = 退出安装（不做任何修改）：` | `y` | 推荐自动 |
| 服务端口 | 3.5 | `服务监听端口（首次安装默认 18080，直接回车即可） [18080]：` | ⏎（默认 18080） | 端口空闲，未触发占用改选分支 |
| 管理员密码 | 3.6 | `y = 由您手工输入；n = 自动生成…；其它键 = 退出安装` | `n` | 输出被管道重定向（非交互），按手册密码只写 root-only 文件，正合替代表 `--password-file` |
| 确认安装 | 3.7 | 核对 产品/版本 1.2.2/commit 7d06a5f6…/架构/方式/程序目录/数据目录/端口 18080；`y = 开始安装；n = 取消安装` | `y` | 与 BUILD_INFO.txt 逐字一致 |
| 安装进度 | 3.8 | `[1%]…[100%]` 阶段文字 + 服务自启 symlink + `新增方案 6 个…同义词表新增 1 张` | 自动 | — |
| 安装成功 | 步骤4 | `【安装成功】…1.2.2`、地址 http://127.0.0.1:18080、密码文件与报告路径 | — | — |

## 最小验收（手册第 5 节 6 项）逐项证据

1. **登录成功** — `wizard-full.log` 无密码明文；`login HTTP 200`（POST /api/auth/login，`{"ok": true, … "must_change_password": true}`），与手册“首次登录须设置新密码”一致（未改密前 `/api/profiles` 返回 403 `PASSWORD_CHANGE_REQUIRED`，即手册所述首登改密闸口）。smoke：`PASS STEP0 admin 登录 / PASS STEP0 首次登录修改密码 / PASS STEP0 新密码重新登录`。
2. **“关于”版本与 BUILD_INFO.txt 一致** — BUILD_INFO.txt：`版本: 1.2.2`、`Git commit: 7d06a5f6870b74204f1fb8545db5c70c66a65ab4`、`应用 Python Runtime: 3.11.16`。`/api/health` → `{"status":"ok","version":"1.2.2"}`；`mmctl version` → `版本： 1.2.2 / commit： 7d06a5f6870b74204f1fb8545db5c70c66a65ab4 / Python： 3.11.16`。逐项一致。
3. **6 方案 + 同义词默认规则与版本**（替代表：登录会话 curl）— `/api/profiles` HTTP 200，`count = 6`，名称清单：
   - `A001 元器件`、`A002 标准紧固件`、`A003 金属材料`、`A005 非金属材料`、`A006 复合材料`、`A007 物资类其他(跨类目)`（与手册 6 方案一一对应；smoke `全部方案可正常打开 opened=6`）。
   - `/api/dictionaries` → `物料同义词表(名称/厂家) | latest_version = 5 | entry_count = 35`；`/api/dictionaries/<id>/versions` → v1(20条)/v2(25条)/v3(35条，created 2026-09-17，随介质导入=默认规则)、v4/v5（created 2026-09-18，smoke“批量删除→新不可变版本→恢复”模拟产物，`versions 3→5`）。
4. **上传两份 smoke Excel 并启动匹配**（浏览器手工步骤按替代表由原厂工具等效完成）— `PASS STEP1 上传待匹配数据 :: status=200 / 上传集团标准数据 :: status=200 / 建立标准数据目录 / 创建任务草稿 / 使用默认方案 A007 完成任务 / 启动匹配 :: task=4373dc79`。
5. **进度/结果/导出** — `PASS STEP2 匹配完成 :: status=COMPLETED 用时=1s / STEP3 打开结果明细 :: status=200 / STEP4 生成结果 200 / STEP4 下载结果 Excel :: bytes=20362`。
6. **重启自动恢复** — `docker restart mm-fn-a`（17:58:09）→ 17:58:28（+19s，处于 15~60 秒验证窗）：`服务状态：active（开机自启：enabled）`，`/api/health` → `{"status":"ok","version":"1.2.2"}`，`/api/health/ready` → `{"status":"ready","checks":{"admin_account":true,"database":true,"data_dir":true,"tmp_dir":true}}`。见 `restart-verify.log`。

## 必答三问

### (a) 是否有单次 >30 秒完全无输出？
**无。** 正式向导 8 秒内全程连续输出（进度条每阶段有文字行）；健康检查、smoke（22 项 1 秒）、重启验证均在秒级响应。备注：本次 8 秒完成快于手册下沿“不到 1 分钟～约 10 分钟”区间，属高速缓存/SSD 容器上的合理快端，无任何停顿或假死迹象。

### (b) 是否有替代表之外的命令？
替代表/手册授权之外的操作全部为**只读勘察或程序自带界面**，未修改系统：
`ls`、`cat README-安装前必读.txt / BUILD_INFO.txt / docs 两份手册`、`md5sum`（核对 manual-copy）、`grep 维护手册/故障处理`（文档非脚本）、`find -mmin`（排查工具残留）、`stat`、`mmctl --help / status / version`（维护工具屏幕输出，手册第 42/51 行授权）、`installer_smoke.py --help`、`rm -rf tools/__pycache__`（替代表要求的清理）。
另有 **2 次向导屏幕探查（dry-run）**：分别输入 `x` 与 `⏎ y⏎`，命中手册 3.19 行“输入其它键会安全退出安装，不做任何修改”——两次均显示 `!! 安装位置无效`（EOF 退出）与 `用户已取消，未对系统做任何修改。`，退出前后核查 `/opt`、`/etc/material_matcher`、`/var/lib/material_matcher`、systemd 单元均无新建 = **零改动**（日志已存档）。curl 曾试探 4 个假想的登录/改密端点路径，全部 401/404/422 只读响应，无副作用。

### (c) 手册与屏幕逐项一致性
一致项（✓）：欢迎自动进入检查；环境检查 ✅/❌ + ℹ️“首次安装”行；安装位置默认 `/opt/material_matcher`；数据位置 y=自动(推荐)/n=手工(高级)；端口默认 18080“被占用时提示改选”；密码 y=手工(≥10位含字母数字不回显)/n=自动 + 非交互管道时**不显示明文、只写** `/etc/material_matcher/secret/admin_password.env`（屏幕原话“本输出与安装日志不包含密码明文”，实测 wizard-full.log 无明文）；确认页核对版本/目录/端口后 y 开始；进度含校验介质/复制程序/安装模型/环境诊断/启动服务/等待就绪/导入默认业务数据各阶段；安装成功页给出地址、admin、6 方案+同义词预置说明、首登强制改密提示；技术日志 `/var/tmp/material_matcher_wizard-*.log` 与安装报告 `/var/log/material_matcher/install-reports/install-*.txt` 路径与手册一致；旧入口 `启动安装.sh` 在介质中确实存在；“介质根目录另有 README/BUILD_INFO”在本介质中位于 `02-非Docker方式/` 内（01 目录未随本容器交付，表述可接受）。

不一致/差异（均为非阻断性，如实列出）：
1. **A007 名称括号**：手册“物资类其他（跨类目）”（全角括号），系统 `/api/profiles` 返回“物资类其他(跨类目)”（半角）。实质一致。
2. **进度页“验证就绪”**：手册 3.8 将“启动服务、验证就绪”列为两件事，屏幕合并为单行 `[66%] 正在启动服务并等待就绪`。文字覆盖了两项功能，仅阶段命名合并。
3. **手册第 29 行“自动生成的密码在交互终端会显示一次”**：本容器无交互终端可用（断网+无图形，全部管道运行），该分支未能实测，仅能验证非交互分支（与手册一致）。属未覆盖而非矛盾。
4. **端口占用改选分支**：18080 空闲，未触发，手册该提示语未实测。属未覆盖而非矛盾。
5. 安装耗时 8 秒，位于手册“不到 1 分钟～约 10 分钟”标称区间下沿之外（偏快），无功能影响。
其余（6 方案清单、同义词默认规则与版本、各屏 y/n 文字语义、报告/日志路径、密码文件路径与权限 600 root）逐项核对**一致**。

## 其他观察（不计为缺陷）

- smoke 工具在“首次登录修改密码”后，将新 admin 口令写入 root-only 文件 `/var/tmp/mm-smoke-admin.pw`（600/root），并同步更新 `/etc/material_matcher/secret/admin_password.env` 的时间戳——交接时请系统管理员以此二文件为准；本记录全程未展示任何口令明文。
- 介质 `02-非Docker方式/` 根 README 与手册描述相互一致；`smoke/` 两份 xlsx 与手册第 34 行文件名一致。

## 结论

**PASS** —— 向导一次性运行成功（RC=0），最小验收 6 项全部取得证据；无 >30 秒无输出；无超范围改动；手册与屏幕一致性仅存 5 处非阻断差异（2 处未覆盖分支、3 处表述差异）。
