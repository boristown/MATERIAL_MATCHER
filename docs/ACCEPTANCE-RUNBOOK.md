# MATERIAL_MATCHER · 人工断网离线部署验证手册（模拟麒麟 V10 实机体验）

更新：2026-09-19　介质：**1.2.5 双轨最终交付介质（终版）**　状态：**双轨一键预演通过，环境已就绪**

## 0. 一句话结论

已在本运维服务器上搭建一台**完全断网**（容器 `mm-customer`，银河麒麟 V10 Lance 用户空间 + systemd）的模拟客户机，介质（1.24 GB tar.gz）已放入 `/root/客户交付介质/`；通过 frp 公网隧道可直接 SSH 登录，人工执行与原厂验收完全相同的"一键"流程。原厂已用一次性容器按本手册全流程预演两遍，结果见第 6 节。

## 1. 介质位置

| 位置 | 路径 |
|---|---|
| 宿主机（打包件） | `/oracle/codex/work/MATERIAL/release-build/output/MATERIAL_MATCHER-1.2.5-KylinV10-x86_64-双轨最终交付介质.tar.gz` |
| 宿主机（解压版） | `/oracle/codex/work/MATERIAL/release-build/output/MATERIAL_MATCHER-最终离线交付介质-1.2.5-x86_64/` |
| **模拟机内（U盘替身）** | `root@mm-customer:/root/客户交付介质/`（tar.gz + 介质SHA256SUMS.txt，仅此两文件，未解包=干净客户态） |

大小 1,238,273,556 B（≈1.24 GB）；SHA256 `e16f97ae24585a28d910fc96bab74e1c34549d7ce14e91c2ba3e2e8abd256e16`；冻结 commit `e76b87f9`。

## 2. 连接模拟机

```bash
ssh -p 17470 root@39.104.206.210
```

root 密码由运维现场提供（一次性沙箱凭据，不入仓库）。隧道为独立 systemd 单元 `frpc-mm-customer.service`（只映射该机 22 端口，remotePort 17470），与既有 frpc.service/xiaogang/material-matcher 隧道互不影响；验证结束可 `systemctl stop frpc-mm-customer` 下线。

模拟机网络：docker 内部网络（internal，无路由出口）——**任何外网访问必然失败，这正是断网验证的一部分**。SSH 走宿主机 frpc 反向通道，不占用麒麟系统任何对外连接。

## 3. 人工安装流程（Docker 方式，客户已确认路线；预计全程 10~15 分钟）

登录后逐步执行（与真实客户完全一致）：

```bash
# ① 校验介质（约 1 分钟，1.24GB）
cd /root/客户交付介质 && sha256sum -c 介质SHA256SUMS.txt          # 期望输出 : OK

# ② 解包（约 20~60 秒）
cd /root && tar -xzf 客户交付介质/MATERIAL_MATCHER-1.2.5-KylinV10-x86_64-双轨最终交付介质.tar.gz
cd "MATERIAL_MATCHER-最终离线交付介质-1.2.5-x86_64"

# ③ 全量完整性校验（三级链之顶层，逐文件，热缓存约 5 秒；冷盘约 2~5 分钟，正常）
sha256sum -c SHA256SUMS-整个交付介质.txt | grep -v ': OK$' ; echo "不匹配行数应为 0"

# ④ 一键安装（Docker 方式）——全程中文问答，无需任何 docker 知识
cd 01-Docker方式 && ./启动Docker安装.sh
```

向导每屏（与介质内《安装手册-Docker方式.md》一致）：
1. 欢迎/二选一说明 —— 自动继续；
2. 环境检查 —— 6 项 ✅ + ℹ️（本机没有 Docker：将由介质离线安装引擎 27.1.1）；
3. 服务端口 —— **直接回车**（18080）；
4. 管理员密码 —— 输入 **n**（自动生成；交互终端会显示一次）；
5. 确认安装 —— 输入 **y**；
6. 进度：校验介质→离线装 Docker Engine→Compose→导入镜像（1~3 分钟，持续提示）→持久目录→启动→就绪（每 15 秒心跳）→**自动导入 6 个正式方案+同义词**→安装报告 → 【安装成功】。

关于"docker 里还能不能再装 docker"的疑问：可以。安装器在麒麟系统内安装的是**官方静态版 Docker Engine**（`01-Docker方式/docker/engine/docker-27.1.1.tgz`）+ systemd 单元；已在本模拟环境多轮实测（含首次全新安装与"已存在则复用"两条路径，复用路径不会动你已有的任何容器/镜像，也不做 prune）。若你想先人工安装 Docker 再跑向导：向导第 4 步会检测到已有 Docker 并提示"直接复用"，同样通过。

## 4. 装完后的最小验收（工作单第 5~12 步的服务端半区）

```bash
curl -s http://127.0.0.1:18080/api/health          # {"status":"ok","version":"1.2.5"}
curl -s http://127.0.0.1:18080/api/health/ready    # "ready"
# 6 方案与同义词：介质原厂工具一键取证
cd /root/MATERIAL_MATCHER-最终离线交付介质-1.2.5-x86_64/01-Docker方式
bootstrap/python/bin/python3 tools/installer_smoke.py --base-url http://127.0.0.1:18080 \
  --password-file /etc/material_matcher/secret/admin_password.env --smoke-dir smoke
# 期望最后一行：SMOKE 22/22 passed
docker restart mm-customer   # （在宿主机执行）模拟断电重启；15 秒后重复上面两条 curl 应自动恢复
```

浏览器半区（登录页/四步页面/上传下载）由你的电脑浏览器打开 `http://<服务器可达地址>:18080` 完成；Win7 老浏览器用介质内 Firefox ESR（《客户工作单》5~12 步）。

## 5. Native（非 Docker）备用轨（可选，另一台干净机执行）

`cd 02-非Docker方式 && ./启动本地安装.sh`（答案同上：回车 / y / 回车 / n / y）。systemd 直装 + 自包含 Runtime，6 方案/同义词自动导入。预演 5 秒完成。

## 6. 原厂预演记录（2026-09-19 00:26–00:28 UTC，一次性容器、同版本介质）

| 步骤 | 结果 | 耗时 |
|---|---|---|
| 外层 tar sha256 -c | OK | ~1 min |
| 解包 2.7GB | 完整 | 21 s |
| SHA256SUMS-整个交付介质.txt 全量 | **0 不匹配** | 5 s（热缓存） |
| Docker 轨向导（无 Docker 起） | rc=0，装至 1.2.5 | **18 s** |
| docker verify_offline/bundle + 重启自启 | 1.2.5 / enabled / ready | ~50 s |
| smoke（Docker 轨） | 22/22 | 1 s |
| Native 轨向导（另一台全新机） | rc=0 | 5 s；smoke 22/22 |
| 介质内验证器（docker/native 两个） | ok=true | 各 <10 s |

人工全程（含打字核对）< 15 分钟，满足 30 分钟目标。证据日志：`test-results/final-installer/{docker,native}/…/rehearsal-*`。

## 7. 若卡住的处置

- 任何屏幕与手册不符/找不到下一步：先按介质内《安装手册》"故障处理"节；仍异常→宿主机 `docker exec mm-customer bash -c 'tail -50 /var/tmp/material_matcher_docker_wizard-*.log'` 取证，并把现象报给原厂（不要手工改库/改配置）。
- 按到"其它键"会**安全退出且零改动**，直接重新运行 `./启动Docker安装.sh` 即可。
