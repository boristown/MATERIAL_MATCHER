# 1.3.9 介质增量（使用手册 + Win7 VSCode）

- mm-1.3.9：tar 1,332,414,133 B，SHA `5c863ca849ba98182ee781aef5a447c7e52d1b381e35b4606ad21f0b0c90264a`，镜像 1.3.9
- 新增：d/use.md 与 n/use.md（使用手册：登录/五菜单/双模板建方案/值映射/A007 组合/STEP1-4/数据位置/export_profile 后台配置/现场改代码指引）；win7/vscodeusersetup-1.82.3.exe（VS Code 最后支持 Win7 的官方版本，微软 update API 直链 commit fdb98833，SHA `811dc918…` 入 win7/SHA256SUMS.txt 与 lic.txt）；README 指引同步；verify 清单与测试同步
- Firefox ESR 在位复核：win7/firefox.exe `68cd0c29da4c…`（与 Mozilla 官方 SHA256SUMS 一致）
- 部署：线上 install.sh rc=0（1.3.8→1.3.9，端口/密码/种子保留）；客户机 /root/d 一键升级 rc=0，health 1.3.9，admin hash `6d224127`/6 方案/1 词表不变，mat2 200
- 门禁：pytest 262 passed（含新资产断言）、前端构建链绿、bash -n、verify 双段通过（安装器内置校验）
- 运维：本轮起构建 TMPDIR 固定 .scratch；介质构建泄漏目录用后即删
