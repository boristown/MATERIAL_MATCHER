第三方组件许可证与来源记录（Docker 方式介质）
====================================================

1) Docker Engine（静态二进制包）
   组件：docker-27.1.1.tgz（含 dockerd/docker/cli/containerd/runc/docker-init/docker-proxy/shim）
   来源：https://download.docker.com/linux/static/stable/x86_64/docker-27.1.1.tgz（Docker Inc. 官方分发）
   许可证：Apache License 2.0
   用途：随介质离线分发并在客户服务器安装，为 MATERIAL_MATCHER 提供容器运行时。
   完整许可证文本：随 docker tar 包分发；亦可参见 https://www.apache.org/licenses/LICENSE-2.0

2) Docker Compose v2 CLI 插件
   组件：docker-compose-linux-x86_64（v2.29.7）
   来源：https://github.com/docker/compose/releases/download/v2.29.7/docker-compose-linux-x86_64（官方 GitHub Releases）
   校验：官方发布附带的 docker-compose-linux-x86_64.sha256 已在构建机核对一致
   许可证：Apache License 2.0

3) 容器基础镜像 rootfs
   来源：银河麒麟 Linux Advanced Server V10 (Lance) 用户空间（与目标部署系统一致），
   以“docker export”方式打包进 material-matcher 应用镜像；镜像内仅添加本应用自有文件。
   麒麟系统组件许可证/版权：遵循 KylinOS 最终用户许可协议；客户须持有银河麒麟 V10 合法授权（本介质不重复分发操作系统安装媒体，仅分发应用容器镜像）。

4) 应用内第三方组件（Python wheel、ONNX 模型、前端依赖）
   详见源码 LICENSE 与 wheelhouse 内各包元数据；构建脚本记录全部包与版本。
