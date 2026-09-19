# MATERIAL_MATCHER · 人工断网离线部署验证手册（模拟麒麟 V10 实机体验）

更新：2026-09-19　介质：**1.2.8（短路径版：mm-x.y.z / d / n / win7）**　状态：**双轨一键预演通过，环境已就绪**

## 0. 一句话结论

已在本运维服务器上搭建一台**完全断网**（容器 `mm-customer`，银河麒麟 V10 Lance 用户空间 + systemd）的模拟客户机，介质（1.24 GB tar.gz）已放入 `/root/mm/（内有 mm-1.2.8-x86_64.tar.gz 与 sha.txt）`；通过 frp 公网隧道可直接 SSH 登录，人工执行与原厂验收完全相同的"一键"流程。原厂已用一次性容器按本手册全流程预演两遍，结果见第 6 节。

## 1. 介质位置

| 位置 | 路径 |
|---|---|
| 宿主机（打包件） | `/oracle/codex/work/MATERIAL/release-build/output/MATERIAL_MATCHER-1.2.5-KylinV10-x86_64-双轨最终交付介质.tar.gz` |
| 宿主机（解压版） | `/oracle/codex/work/MATERIAL/release-build/output/MATERIAL_MATCHER-最终离线交付介质-1.2.5-x86_64/` |
| **模拟机内（U盘替身）** | `root@mm-customer:/root/mm/（内有 mm-1.2.8-x86_64.tar.gz 与 sha.txt）`（tar.gz + 介质SHA256SUMS.txt，仅此两文件，未解包=干净客户态） |

大小 1,238,273,556 B（≈1.24 GB）；SHA256 `e16f97ae24585a28d910fc96bab74e1c34549d7ce14e91c2ba3e2e8abd256e16`；冻结 commit `e76b87f9`。

## 2. 连接模拟机

```bash
ssh -p 17470 root@39.104.206.210
```

root 密码由运维现场提供（一次性沙箱凭据，不入仓库）。隧道为独立 systemd 单元 `frpc-mm-customer.service`，当前映射两条：
- SSH：remotePort 17470 → 该机 22；
- Web：remotePort 18080 → 该机 18080（**装完后即可用 `http://mat2:18080` 或 `http://39.104.206.210:18080` 直接打开系统**，mat2 为你已解析到 frps 的 A 记录）。
与既有 frpc.service/xiaogang/material-matcher 隧道互不影响；验证结束 `systemctl stop frpc-mm-customer` 下线。

模拟机网络：docker internal 桥（无路由出口）；另挂有第二块数据盘 /data2（13G ext4 loop），用于体验数据盘选择屏。——**任何外网访问必然失败，这正是断网验证的一部分**。SSH 走宿主机 frpc 反向通道，不占用麒麟系统任何对外连接。

## 3. 人工安装流程（Docker 方式，客户已确认路线；预计全程 10~15 分钟）

```bash
# ① 校验并解包（10 秒）
cd /root/mm && sha256sum -c sha.txt && tar -xzf mm-1.2.8-x86_64.tar.gz
cd mm-1.2.8 && sha256sum -c all.sha256 | grep -v ': OK$' | wc -l      # 应为 0

# ② 一键安装（全部命令只有 6 个短名：run/stop/rst/bk/del/menu）
cd d && ./run.sh
```

向导每屏（与介质内 d/doc.md 一致）：
1. 欢迎/二选一说明 —— 自动继续；
2. 环境检查 —— 全 ✅ + ℹ️；
3. 数据盘选择 —— 前三名磁盘与剩余空间，推荐最大者：**输入 y 接受推荐**（n=改选编号）；
4. 服务端口 —— 直接回车（18080）；
5. 管理员密码 —— 输入 **n**（自动生成）；
6. 确认安装 —— 输入 **y**；
7. 进度：校验介质→离线装 Docker Engine→Compose→导入镜像→数据盘落位→启动→就绪（心跳）→导入 6 方案+同义词→报告→【安装成功】。

## 4. 装完后的最小验收（工作单第 5~12 步的服务端半区）

```bash
curl -s http://127.0.0.1:18080/api/health          # {"status":"ok","version":"1.2.5"}
curl -s http://127.0.0.1:18080/api/health/ready    # "ready"
# 6 方案与同义词：介质原厂工具一键取证
cd /root/MATERIAL_MATCHER-最终离线交付介质-1.2.5-x86_64/d
bootstrap/python/bin/python3 tools/installer_smoke.py --base-url http://127.0.0.1:18080 \
  --password-file /etc/material_matcher/secret/admin_password.env --smoke-dir smoke
# 期望最后一行：SMOKE 22/22 passed
docker restart mm-customer   # （在宿主机执行）模拟断电重启；15 秒后重复上面两条 curl 应自动恢复
```

浏览器半区（登录页/四步页面/上传下载）由你的电脑浏览器打开 `http://<服务器可达地址>:18080` 完成；Win7 老浏览器用介质内 Firefox ESR（《客户工作单》5~12 步）。

## 5. Native（非 Docker）备用轨（可选，另一台干净机执行）

`cd n && ./run.sh`（答案序列：y（数据盘）→ 回车（端口）→ n（密码自动生成）→ y（确认））。systemd 直装 + 自包含 Runtime，6 方案/同义词自动导入。预演 5 秒完成。

## 6. 原厂预演记录（2026-09-19 00:26–00:28 UTC，一次性容器、同版本介质）

| 步骤 | 结果 | 耗时 |
|---|---|---|
| 外层 tar sha256 -c | OK | ~1 min |
| 解包 2.7GB | 完整 | 21 s |
| all.sha256 全量 | **0 不匹配** | 5 s（热缓存） |
| Docker 轨向导（无 Docker 起） | rc=0，装至 1.2.5 | **18 s** |
| docker verify_offline/bundle + 重启自启 | 1.2.5 / enabled / ready | ~50 s |
| smoke（Docker 轨） | 22/22 | 1 s |
| Native 轨向导（另一台全新机） | rc=0 | 5 s；smoke 22/22 |
| 介质内验证器（docker/native 两个） | ok=true | 各 <10 s |

人工全程（含打字核对）< 15 分钟，满足 30 分钟目标。证据日志：`test-results/final-installer/{docker,native}/…/rehearsal-*`。

## 7. 若卡住的处置

- 任何屏幕与手册不符/找不到下一步：先按介质内《安装手册》"故障处理"节；仍异常→宿主机 `docker exec mm-customer bash -c 'tail -50 /var/tmp/material_matcher_docker_wizard-*.log'` 取证，并把现象报给原厂（不要手工改库/改配置）。
- 按到"其它键"会**安全退出且零改动**，直接重新运行 `./run.sh` 即可。

## 8. 生命周期脚本（1.2.7 起随介质两区提供）

| 脚本（d 或 n 目录内） | 作用 |
|---|---|
| `sudo ./rst.sh` | 重启本系统服务并探活（60 秒内确认 200） |
| `sudo ./stop.sh` | 停止服务并取消自启；数据/镜像/Docker 全保留 |
| `sudo ./bk.sh enable [HH:MM]` | 每日自动备份（默认 02:30），root-only，保留最近 14 份；`run`/`list`/`disable` |
| `sudo ./del.sh` | 仅卸载本系统（容器/镜像/compose 或 systemd 单元）；**不卸载 Docker 软件、保留数据** |
| `sudo ./del.sh --purge-data` | 同上并删除数据与配置（两次 yes 确认） |

预演记录（1.2.7，一次性容器）：安装→备份 enable+run（timer active）→停用（health 000）→重启（恢复 200）→卸载（Docker 27.1.1 仍在、本项目镜像清零、数据块保留）→重装（升级模式，health 1.2.7）。见 docker/20260919-lifecycle/。
