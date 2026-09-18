# MATERIAL_MATCHER 1.2.3 非Docker方式 · 最终验收安装操作员报告

- 角色：未参与项目开发的运维安装员（黑盒，仅依据 manual-copy.md 与屏幕提示）
- 环境：容器 mm-fo-nv（银河麒麟 V10，x86_64，完全断网，无图形/浏览器）
- 介质：/root/MATERIAL_MATCHER-最终离线交付介质-1.2.3-x86_64/02-非Docker方式
- 日期：2026-09-18（容器内时间为 UTC，与本机相差 +8h）
- 完整向导日志：wizard-full.log（同目录）

## 一、执行过程（一次成功，无安全退出重跑）

1. 通读手册后一次性规划输入序列：`安装位置[回车默认] → 数据位置[y] → 端口[回车默认18080] → 密码[n 自动生成] → 确认[y]`。
   选 n 自动生成密码，避免手工输入导致口令明文进入 wizard-full.log（手册第 6 步：重定向输出时密码不显示，仅写 root-only 文件 `/etc/material_matcher/secret/admin_password.env`，实测相符：600 root）。
2. 18:25:12 执行命令模板启动向导，18:25:21 打印【安装成功】，exit=0。
3. 无浏览器，按替代表验证：curl 登录 + 原厂 smoke + docker restart。
4. smoke 跑完按要求 `rm -rf tools/__pycache__`（已确认目录不存在）。

## 二、必答项

### (a) 有无 >30s 无输出
**无。** 后台每 3s 采样向导日志字节数/mtime：全部输出在 9s 内完成，相邻两次输出块最大间隔 ≤5s（写入时间点 1789727112→116→119→121）。向导全程各阶段（校验介质/复制程序/安装模型/环境诊断/启动服务/导入默认业务数据）均有文字与百分比进度。

### (b) 有无替代表外命令
仅以下为核对/运维所必需的只读或维护类操作，未读取任何仓库文件或介质内脚本内容：
- `docker ps`、介质目录 `ls`、`cat BUILD_INFO.txt`（手册明示的核对用清单文件）；
- `mmctl --help`（手册提及的维护工具，查帮助以寻找口令处置途径）；
- curl 探测登录端点路径（/api/login→/api/auth/login，属替代表"curl 验证"范围）；
- 读取 smoke 工具自身产生的 root-only 产物 `/var/tmp/mm-smoke-admin.pw`（见"问题/观察 1"）。
其余全部命令即命令模板、替代表所列 smoke/curl/docker restart 与 `rm -rf tools/__pycache__`。

### (c) 手册与屏幕逐项一致核对

| 手册条目 | 屏幕实际 | 一致 |
|---|---|---|
| 欢迎页：终端显示欢迎文字后自动环境检查 | 显示"== 欢迎 =="后自动进入环境检查 | ✅ |
| 环境检查 ✅/❌ + ℹ️ 首次安装检测 | 6 项全 ✅，ℹ️"未检测到已安装版本：本次为首次安装" | ✅ |
| 安装位置默认 `/opt/material_matcher` 直接回车 | 提示与默认值一致，回车接受 | ✅ |
| 数据位置 y=自动(推荐)/n=手工/其它键退出 | 提示文案一致，输入 y | ✅ |
| 服务端口默认 18080，直接回车 | 提示一致，回车通过 | ✅ |
| 密码 y 手工/n 自动；非交互终端不回显、只写 root-only 文件 | 选 n：屏幕未出现任何明文，文件 `/etc/material_matcher/secret/admin_password.env` 权限 600 root | ✅ |
| 确认安装页显示版本/目录/端口，输入 y | 显示 1.2.3 + commit 28b7492… + /opt/material_matcher + 18080，y 开始 | ✅ |
| 进度各阶段文字提示 | 1%~100% 含 校验介质/复制程序/安装模型/环境诊断/启动服务并等待就绪/导入默认业务配置 | ✅ |
| 安装报告路径 `/var/log/material_matcher/install-reports/`；向导日志 `/var/tmp/material_matcher_wizard-*.log` | 实际生成 install-20260918-102521.txt 与 material_matcher_wizard-20260918-102512.log | ✅ |
| 安装成功页提示浏览器地址、admin 登录、首登强制改密 | 页面提示一致；API 实测未改密前业务接口返回 PASSWORD_CHANGE_REQUIRED，与"首次登录设置新的登录密码"一致 | ✅ |
| 预置 6 个正式方案 | 逐一核对（见下表） | ✅ |
| 默认同义词配置（规则+版本） | "物料同义词表(名称/厂家)" entry_count=35，latest_version=5（初始 3，smoke 不可变版本测试后 5） | ✅ |
| 版本号与 BUILD_INFO.txt 一致 | 均为 1.2.3（"系统设置·关于"无图形界面，以 `/api/system/info` 的 version 字段等效核对） | ✅ |

**6 方案名逐一核对（登录后 `curl GET /api/profiles` 实际返回）：**

| # | 手册 | 实际 API | 一致 |
|---|---|---|---|
| 1 | A001 元器件 | A001 元器件 | ✅ |
| 2 | A002 标准紧固件 | A002 标准紧固件 | ✅ |
| 3 | A003 金属材料 | A003 金属材料 | ✅ |
| 4 | A005 非金属材料 | A005 非金属材料 | ✅ |
| 5 | A006 复合材料 | A006 复合材料 | ✅ |
| 6 | A007 物资类其他(跨类目) | A007 物资类其他(跨类目) | ✅ |

`/api/dictionaries versions`：物料同义词表(名称/厂家) latest_version=5，entry_count=35（含 sha256 版本指纹，不可变版本机制）。

## 三、最小验收证据行

```
[安装] 18:25:21 ============== 安装成功 ============== exit=0（向导全程 9s）
[服务] systemctl is-active material_matcher -> active；LISTEN 0.0.0.0:18080 (python3)
[登录] POST /api/auth/login http=200 {"ok":true,...,"must_change_password":true}
[方案] /api/profiles -> ["A001 元器件","A002 标准紧固件","A003 金属材料","A005 非金属材料","A006 复合材料","A007 物资类其他(跨类目)"]
[同义] /api/dictionaries -> {"name":"物料同义词表(名称/厂家)","latest_version":5,"entry_count":35}
[版本] /api/system/info -> "version":"1.2.3" ＝ BUILD_INFO.txt 1.2.3 / commit 28b74922617dbde5edc608fb3e4ee9a6e76fb181
[smoke] SMOKE 22/22 passed in 1s（STEP1 上传→STEP2 匹配 COMPLETED→STEP3 结果→STEP4 导出 Excel 20363 字节；方案全部可打开 opened=6）
[清理] rm -rf tools/__pycache__ -> No such file or directory
[重启] docker restart mm-fo-nv；18:42:11 重启 -> ~3s 后 /health 恢复；relogin http=200；profiles_after_reboot=6
[报告] /var/log/material_matcher/install-reports/install-20260918-102521.txt：模式=首次安装，服务状态：active
[无静默] 输出块 mtime 序列 1789727112/116/119/121，最大间隔 5s ≤30s
```

密码明文未写入本报告及任何宿主日志；口令获取一律通过 root-only 文件变量替换完成。

## 四、问题/观察（非阻断）

1. **smoke 首登改密后密码衔接**：原厂 smoke 会消费"首次登录必须改密"流程并把新口令写入其自身产物 `/var/tmp/mm-smoke-admin.pw`（600 root）；官方 `admin_password.env` 保持初值不再可登录。属工具设计行为，但手册未预告该文件，建议文档补一句。
2. 安装耗时 9s，优于手册"不到 1 分钟"下限表述，页面缓存充足环境下正常。
3. 成功页提示"未检测到局域网 IPv4 地址（容器）仅本机可访问"，与断网容器环境相符，非缺陷。
4. 无其它不一致、无向导输入错误、无重跑。

## 五、结论

**PASS**
