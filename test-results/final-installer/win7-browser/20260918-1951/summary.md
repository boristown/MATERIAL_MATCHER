# 1.2.4 介质收尾记录

- 客户工作单（Win7 现场验收 5~12 步 + Chrome 109 官方获取二选一/B 方案验真指引）已打入交付介质 客户端浏览器-Win7/客户工作单-Win7浏览器验收与Chrome获取指引.md。
- Chrome 109 合规核查（2026-09-18，本构建机直连）：dl.google.com 企业 MSI 8 种版本化路径全部 404；Google Chromium 官方 GCS 桶自本网络不可达 → 不打包不可验源二进制；指引客户经企业再分发渠道自取并 certutil 验真。
- Firefox ESR 115.41.0esr win64：官方归档获取，SHA256 68cd0c29… 与 Mozilla 官方 SHA256SUMS 一致。
- 1.2.4 双轨复验：Docker 全新无 Docker 环境首装 rc=0 + smoke 22/22（docker/20260918-1951/reconfirm-1.2.4.log）；Native 首装 rc=0 + smoke 22/22（native/20260918-1951/reconfirm-1.2.4.log）。
- 介质：MATERIAL_MATCHER-1.2.4-KylinV10-x86_64-双轨最终交付介质.tar.gz，1,238,302,542 B，SHA256 01bfb4e5da9a5cb7b2cf54e6b0acbadce07fa0e8981fcf78da82979bb6c11865（commit 0faf9118）。
