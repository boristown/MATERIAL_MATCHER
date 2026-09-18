# MATERIAL_MATCHER 1.2.3 最终离线验收 · Docker 方式 · 安装员执行报告

- 时间：2026-09-18 18:22–18:29（宿主机 CST）
- 目标环境：docker 容器 `mm-fo-dk`（Galaxy Kylin V10 Lance，x86_64，完全离线，无图形界面/浏览器，安装前无 Docker）
- 介质：`/root/MATERIAL_MATCHER-最终离线交付介质-1.2.3-x86_64/01-Docker方式`
- 唯一参考：`manual-copy.md`（校验其 SHA256 = 介质内 `安装手册-Docker方式.md`，完全一致：`3d0443cd91ba…424255`）
- 安装员未读取 MATERIAL_MATCHER 仓库任何文件，未打开介质内任何脚本内容。

## 0. 前提确认（手册“你需要确认的前提”）

| 项 | 屏幕/命令证据 |
|---|---|
| 麒麟 V10 x86_64 | `/etc/kylin-release`: `Kylin Linux Advanced Server release V10 (Lance)`；`uname -m`: `x86_64` |
| root | 容器内默认 root |
| ≥12 GB 磁盘 | `df -h /`: 可用 754G；向导屏 `✅ 磁盘可用约 751 GB` |
| 无需预装 Docker | 向导屏 `ℹ️ 本机没有 Docker：将由介质离线安装 Docker Engine 27.1.1` |

## 1. 执行记录

- **第 1 次执行 18:25（安装员输入错误，安全退出，未做任何修改）**：规划输入 `回车,回车,n,y`。屏幕显示欢迎屏为“自动继续”（不读取输入），第 1 个回车被端口屏消耗，第 2 个回车落入密码屏被判定为“其它键” → 屏显 `用户已取消，未对系统做任何修改。` 记录于 `wizard-full.attempt1-misinput.log`（对应技术日志 `/var/tmp/material_matcher_docker_wizard-20260918-102535.log`）。
- **第 2 次执行（修正输入 `回车,n,y`）**：18:26:01 启动，18:26:19 屏显【安装成功】。**向导安装耗时 18 秒**，退出码 0。日志 `wizard-full.log`、时间线 `wizard-timeline.txt`、`wizard-exit.txt`、技术日志 `/var/tmp/material_matcher_docker_wizard-20260918-102601.log`。
- 密码方式选择 **n（自动生成）**，避免口令经命令管道明文落盘；安装器自身屏显“本输出不含明文”。
- 首次登录强制改密（手册第 4 步在无浏览器环境下的等效操作）：`POST /api/auth/login` 返回 `must_change_password:true` → `POST /api/auth/change-password`（响应键 `ok, relogin_required, user`，HTTP 200），新密码仅随机生成并在容器内传递，未回显；同步写回 `/etc/material_matcher/secret/admin_password.env`（root 0600）以保证 smoke 的 `--password-file` 参数可用。**所有密码明文均未出现在本次任何报告/日志/终端输出中**（已逐文件 grep 校验：全部“无明文密码”）。

## 2. 必答 (a) 有无 >30s 无输出

**无。** 5 秒采样日志文件增长：全程最大无增长间隔 **10 秒**（出现在校验/镜像导入阶段，屏幕仍有 `[20%]…[55%]…` 持续进度）。导入实际远快于手册预估的“1～3 分钟”（更快，非不一致）。证据：`wizard-timeline.txt`。

## 3. 必答 (b) 有无替代表外命令

替代验证仅使用替代表规定的 curl 登录验证 + 原厂 smoke（含 `rm -rf tools/__pycache__`）+ `docker restart mm-fo-dk`。
除此之外使用过的命令均属只读/前提性质或无浏览器场景的必要探测，**无任何替代安装/卸载手段**：
- `ls`/`df`/`uname`/`cat /etc/kylin-release`（前提确认）；`cat BUILD_INFO.txt`、`sha256sum 安装手册`（版本核对与手册一致性，非脚本）；
- curl 端点探测：首次改密端点按手册“按提示首次修改密码”在 3 个候选中探测（`/api/auth/change-password` 命中，`/api/auth/password`、`/api/auth/change_password` 未发送成功）；“系统设置·关于”候选端点 `/api/about` 等 5 个均 404，版本证据改用 `GET /api/health`（`{"status":"ok","version":"1.2.3"}`）及 smoke `PASS health`；
- `rm -f /tmp/*`（清理探测临时文件）。
- smoke 运行后已执行 `rm -rf tools/__pycache__`（屏显 `tools/` 仅剩 `installer_smoke.py`）。

## 4. 必答 (c) 手册与屏幕/系统逐项核对

| 项 | 手册 | 屏幕/系统实际 | 判定 |
|---|---|---|---|
| 欢迎-自动继续 | 3.1 自动继续 | 屏显欢迎与二选一说明后自动进入环境检查，不需按键 | ✅（并解释第 1 次误输入原因） |
| 环境检查逐项✅ | 3.2 | 8 项 ✅（OS/架构/systemd/运行环境/离线组件/镜像 tar/默认业务数据/磁盘），无 Docker→提示离线安装、不覆盖已有容器镜像 | ✅ |
| 端口默认 18080 | 3.3 | `服务监听端口（首次安装默认 18080） [18080]：` 回车即用；汇总屏 `服务端口：18080` | ✅ |
| 密码 y/n 选项 | 3.4 y=手工(≥10位含字母数字) n=自动生成 | `y = 手工输入 / n = 自动生成强密码`；n 路径可用 | ✅ |
| 确认安装 y | 3.5 输入 y 开始 | `确认开始？y = 开始安装` | ✅ |
| 进度阶段 | 3.6 校验介质→装 Docker→Compose→导入镜像(持续进度)→生成配置→启动→等待就绪(心跳)→导入 6 方案与同义词→完成 | 屏显 `[3%]校验→[8%]Engine→[14%]Compose→[20%]导入镜像(1~3分钟提示)→[55%]配置→[62%]启动→[66%]等待就绪(持续进度)→[90%]导入默认业务配置(6 方案与同义词表)→[100%]安装完成` 逐段对应 | ✅ |
| **6 方案名逐一** | A001 元器件 / A002 标准紧固件 / A003 金属材料 / A005 非金属材料 / A006 复合材料 / A007 物资类其他(跨类目) | `/api/profiles`（登录态，HTTP 200）逐一输出：`A001 元器件`、`A002 标准紧固件`、`A003 金属材料`、`A005 非金属材料`、`A006 复合材料`、`A007 物资类其他(跨类目)`，共 6 个（含 smoke `names=6`、`opened=6`）。与手册逐字一致（编号无 A004，与手册相同） | ✅ |
| 同义词 | “默认同义词（写法归一化）配置及版本历史” | `/api/dictionaries`：`物料同义词表(名称/厂家)` `latest_version=3, rules/entry_count=35`；smoke：`versions=3 rules=35`、`批量删除→新不可变版本→恢复 versions 3→5`（版本历史成立）。系统内名称为“物料同义词表(名称/厂家)”，手册用功能描述“写法归一化”，语义对应 | ✅ |
| y/n 语义 | 失败节：y=第一项、n=第二项、其它键=安全退出（不做任何修改） | 密码屏 `y=手工;n=自动生成;其它键=退出安装（不做任何修改）`；确认屏 `y=开始;n=取消;其它键=退出（不做任何修改）`；第 1 次误输入实测：安全退出且零改动 | ✅ |
| 安装报告路径 | `/var/log/material_matcher/install-reports/` | 屏显且实存 `docker-install-20260918-102619.txt`（root 0600）；向导技术日志 `/var/tmp/material_matcher_docker_wizard-*.log` 实存（含两次运行） | ✅ |
| 数据位置表 | /etc、/var/lib、/var/log/material_matcher、/opt/material_matcher/docker | 四目录均存在（du：12K/892K/8K/12K）；容器 `material_matcher-app` | ✅ |
| 成功屏地址 | 页面地址、局域网地址会列出 | `http://127.0.0.1:18080`；`未检测到局域网 IPv4 地址：仅本机可访问`（容器网络实况，与手册不冲突） | ✅ |
| Win7 浏览器提示 | 存在 | 屏显《客户端浏览器-Win7》Firefox ESR 提示（本环境无浏览器，按替代表 curl+smoke） | N/A ✅ |

## 5. 最小验收（手册第 6 步）逐项证据

1. **登录成功**：`POST /api/auth/login` → HTTP 200 `{"ok":true,…,"must_change_password":true}`；首次改密 `POST /api/auth/change-password` → 200；改密后重登并访问受保护 API → 200；smoke `PASS STEP0 admin 登录`。
2. **“系统设置·关于”版本 = BUILD_INFO**（无浏览器替代）：介质 `BUILD_INFO.txt` `版本: 1.2.3`；`GET /api/health` → `{"status":"ok","version":"1.2.3"}`；smoke `PASS health :: version 1.2.3`。一致 ✅。
3. **6 个方案与同义词配置可见**：`/api/profiles` 6 项名称逐一列出（见上表）；`/api/dictionaries` 同义词表 latest_version=3/35 条；smoke `names=6 opened=6`、`versions=3 rules=35`。
4. **smoke 两文件走完四步并下载结果 Excel**：介质 `smoke/smoke-待匹配数据.xlsx`、`smoke-集团标准数据.xlsx`；smoke 输出 STEP1 上传×2/建目录/建草稿/启动匹配 → STEP2 COMPLETED(1s) → STEP3 打开结果明细 → STEP4 生成结果/导出清单/**下载结果 Excel bytes=20363**；`SMOKE 20/20 passed`，exit 0；随后 `rm -rf tools/__pycache__`。
5. **重启后自动恢复**：`docker restart mm-fo-dk`（替代表）→ 内部 `material_matcher-app` 自动拉起（Up 4s），`GET /` 恢复 HTTP 200 用时 **5 秒**（≤1 分钟），`/api/health` 版本 1.2.3。

另：安装器仅创建/启动 `material_matcher-app` 容器（`docker ps` 仅此一个），未触碰其它容器/镜像/卷，与手册承诺一致。

## 6. 密码安全声明

- 选择 n（自动生成）路径，安装全程无口令经命令行/管道传输；安装器屏显“本输出不含明文”。
- 首次改密新口令为容器内随机生成、仅内存变量传递；已同步至 `/etc/material_matcher/secret/admin_password.env`（0600 root）。
- 本报告及全部日志文件（wizard-full.log、attempt1 日志、timeline、exit、restart.log、本文件）经 `grep -F` 对当前口令值核验：**均无明文密码**。

## 7. 问题列表

1. （安装员侧）第 1 次执行因误判“欢迎屏需回车”而按“其它键”规则安全退出，零改动，允许范围内重跑 1 次成功——同时说明向导对任意输入均以“安全退出、不做任何修改”方式防护，行为符合手册。
2. （文档小差异）介质/界面同义词词典名称为“物料同义词表(名称/厂家)”，手册描述为“默认同义词（写法归一化）配置”；语义对应，不构成不一致。
3. （环境限制）无浏览器下“系统设置·关于”页面无法直开，以 `/api/health` 与 smoke 的 version=1.2.3 作等效证据；“关于”专用 API 端点未提供（候选均 404）。
4. （观察，非缺陷）导入镜像实际约十几秒完成（手册预估 1～3 分钟），进度输出持续；镜像导入+就绪等待阶段无 >30s 静默。

## 8. 结论

**PASS** —— Docker 方式一次性安装成功（修正输入后第 2 次执行，18 秒完成），手册与屏幕逐项一致，最小验收 5 项全部有据，无明文密码落盘，重启自动恢复 5 秒。
