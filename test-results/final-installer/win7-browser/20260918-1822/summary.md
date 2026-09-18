# Win7 客户端浏览器工具包 —— PARTIAL（入包与合规完成；运行时验证需客户 Win7 环境）

- Firefox ESR 115.41.0esr win64 zh-CN 已入正式介质：与 Mozilla 官方 releases/115.41.0esr/SHA256SUMS 一致（68cd0c29da4c75e37c3ba38cca9b7d030d995c6b2a5cae15e8a74c841d677b1e），未修改，MPL-2.0，可再分发。
- Chrome 109.0.5414.120：Google 官方渠道已下线（版本化 URL 404、Chrome for Testing 仅 113+）→ 按合同 §9 不打包，处置见 chrome.md/browser-package-source.md。
- 运行时 smoke（离线安装→登录→STEP1-4→上传下载）需真实 Win7 x64：本服务器无 Windows 虚拟化能力（无 qemu/libvirt/wine），未执行 → 如实标注，不虚假宣称 PASS。
