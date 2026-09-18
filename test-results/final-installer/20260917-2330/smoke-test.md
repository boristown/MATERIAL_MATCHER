# 最小业务 smoke（安装出系统真的能用）

工具：介质内 tools/installer_smoke.py（仅标准库，可用介质 bootstrap Python 运行，随介质交付）。

最终轮（1.1.22）结果（mm-cr-a6 / b6 / e6 一致）：SMOKE 17/17，含：
- health / health/ready（admin_account/database/data_dir/tmp_dir 全 true）；
- admin 登录 + 首登强制改密 + 新密码重登（真实首用户体验路径）；
- 前端页面可达（GET / 200）；
- STEP1 上传《smoke-待匹配数据.xlsx》《smoke-集团标准数据.xlsx》、建集团标准目录、建草稿、启动匹配；
- STEP2 匹配 COMPLETED（8 行数据 1 秒内完成，进度可见）；
- STEP3 workbench 结果明细可见；
- STEP4 finalize→导出清单→下载结果 Excel（14,873 字节，真实 xlsx）。

注：本 smoke 验证软件可用性，不替代 1000 行级正式准确率验收（docs/ACCURACY_AND_DELIVERY_BASELINE.md 另有基线）。
