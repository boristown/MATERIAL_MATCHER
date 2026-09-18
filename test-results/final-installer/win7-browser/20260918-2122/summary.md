# Win7 浏览器交付终局记录（1.2.5）

- 客户决议（2026-09-18）：**豁免 Chrome 109，Win7 终端统一使用 Firefox ESR 115.41.0esr**（介质内，官方归档 + Mozilla 官方 SHA256SUMS 校验一致：68cd0c29…）。
- 决议已固化：介质内 README-浏览器选择.txt、LICENSES-AND-SOURCES.txt、《客户工作单》第二节（A 项已勾选，B 方案留档备查）。
- Chrome 109 官方渠道核查证据（全部下线/不可达）已存档于前轮证据目录（win7-browser/20260918-1822/chrome.md）。
- 1.2.5 终版介质：MATERIAL_MATCHER-1.2.5-KylinV10-x86_64-双轨最终交付介质.tar.gz，1,238,273,556 字节（≈1.24 GB），SHA256 e16f97ae24585a28d910fc96bab74e1c34549d7ce14e91c2ba3e2e8abd256e16，commit e76b87f9。
- 双轨终版复验：Docker 全新无 Docker 环境首装 rc=0 + smoke 22/22；Native 首装 rc=0 + smoke 22/22（见 docker/native 20260918-2122/reconfirm 日志）。
- 剩余唯一客户现场动作：按《客户工作单》5~12 步在任一 Win7 电脑上用 Firefox 跑一遍页面级验收（原厂已以接口等效完成同一清单）。
