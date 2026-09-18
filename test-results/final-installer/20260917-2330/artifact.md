# 最终交付介质

| 字段 | 值 |
|---|---|
| 文件名 | MATERIAL_MATCHER-1.1.22-KylinV10-x86_64-offline.tar.gz |
| 大小 | 541,206,213 bytes（516 MiB） |
| SHA256 | ec722016e5f666e309ab8b82e5c60855559cf68c8d65d26b0c1cead995e78465 |
| 版本 | 1.1.22（pyproject.toml 唯一来源） |
| Git commit | c4e974e72d39161a0f5678b3e4f4a23f9b4fa04f（main，release manifest 内强制 40 位并经验证器校验） |
| 构建时间 | 2026-09-17 UTC 晚间（见 BUILD_INFO.txt） |
| 目标系统/架构 | 银河麒麟 V10 / x86_64（aarch64 不在本次交付范围，未制作、未声称） |
| 安装器 bootstrap Python | 3.11.16 自包含（裁剪 standalone，92MB，介质根 bootstrap/python） |
| 应用 Runtime | 3.11.16 自包含（release/runtime，pip 离线安装 wheelhouse 31 个 wheel，含 onnxruntime/tokenizers numpy 等 native x86_64 wheel，pip check 通过） |
| Embedding 模型 | BAAI/bge-base-zh-v1.5（model.onnx 389MB + tokenizer.json，随介质，无联网下载） |
| 前端 | Vue production dist 预构建（不含 .map）+ source/web 全源码 |
| Node 离线重建 | tools/node-offline：node v18.15.0 运行时 + node_modules.tar（248MB，装至 /opt/material_matcher/tools/node-offline） |
| 完整性链 | runtime-manifest → release-manifest → offline-manifest(16,571 文件逐 SHA256) → 介质根 SHA256SUMS → 外层 tar SHA256 |
| 介质根目录 | 安装/维护 .desktop、启动安装.sh、维护工具.sh、install_wizard.sh、install.sh、mmctl、docs 三手册、README-安装前必读.txt、BUILD_INFO.txt、SHA256SUMS、smoke/、bootstrap/、release/、models/、wheelhouse/、tools/ |
| 可追溯性 | 同版本号不同内容会被安装器拒绝（.bundle_manifest_sha256 机制，Test F/D 触发验证） |
