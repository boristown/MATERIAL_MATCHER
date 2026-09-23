# 升级后验收清单（现场逐项打勾）
1. 版本链一致：`cat /opt/.../material_matcher/VERSION`=1.3.20；`/api/health` version=1.3.20；页面左下角 v1.3.20；登录页 v1.3.20（Docker：`docker exec 容器 cat /opt/material_matcher/current/app/material_matcher/VERSION`）
2. 数据保真：历史任务可开、6 方案在列（阈值=50 的版本仍在）、同义词在、上传文件数不变（对比备份 uploads.list）
3. #164：上传一份"真实1000行但维度虚标"的 Excel → 页面显示 ~1000
4. #163：带映射方案跑单：10vs国产=一致；10vs进口=不一致；目标空=无数据；12=未配置不猜；无候选行页面不异常
5. #166：1366/1440/1920 三宽度下按钮不贴边、间距一致（肉眼）
6. STEP1→STEP4 全链 smoke + 结果 Excel 下载
7. rollback 演练（建议）：./rollback.sh 回到旧版 → 确认功能 → ./upgrade.sh 再次升级
8. #162 现场基准（正式验收，另排时间）：
   `python scripts/benchmark_issue_162.py --preset formal --provider onnx_local --model-id BAAI/bge-base-zh-v1.5 --dimensions 768 --precision int8 --warm-runs 2 --output issue-162-formal-production-model.json`
   需 1 冷 2 热全部 ≤60min、期间 /api/health 与 /api/health/ready 正常、STEP2 心跳/ETA 持续更新，并附金标质量对比。
