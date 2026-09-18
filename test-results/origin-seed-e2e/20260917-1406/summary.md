# PR#34 origin 种子 1000 行 · mat.bjlzc.cn 生产端到端验收(自动阶段)

- 日期:2026-09-17(UTC+8) 执行:ECC 运维 Agent · 操作账号:**admin**(生产库留痕 created_by/started_by=admin)
- 被测版本:main @ `649fb4a`(v1.1.4,与 /opt/material_matcher/current 部署一致,工作区干净)
- 数据:仓库 `tests/fixtures/realistic_materials/generated/`(origin_data.zip 种子,SHA256 见 environment.json;本地重跑生成器 4 个产物与已提交文件**逐字节一致**)
- 任务:`bd8823b4df48487ca1e79bd4cc51678e` · 草稿 `d64045aea7b948cba42d5c43d6bfecfa` · 验收 run `04fa9d8c37974f89b14872a5ffa77837`
- 链路:admin 登录 → STEP1 双上传(源 1000 / 目标 67)→ 自动集团码目录 → 规则(Z001/Z006 校准配置,#35/#36 默认 88/72/Top10,**未为指标改动任何阈值规则**)→ dry-run → 启动 → 19s 完成 → 业务验收 evaluation → 全量导出。
- **本轮按用户要求停止在人工核对步**:REVIEW 队列未动,operation_log 中人工操作数为 0(真实值,不伪造)。

## 自动阶段指标(1000 行,真值 Y=900 / N=100)

| 指标 | 数值 |
| --- | --- |
| 自动匹配数(匹配率) | 139(13.9%) |
| 自动匹配精确率 | **139/139 = 100%** |
| 自动误匹配 | 0;N 样本被自动错配 0 |
| Y 样本 Top1 准确率(候选排序正确率) | **900/900 = 100%** |
| Y 样本 Top5 召回 | 900/900 = 100%(正确目标未进 Top5:0) |
| 待人工核对 REVIEW | 516(其中 Y 508、N 8) |
| 自动判定未匹配 UNMATCHED | 345(其中 N 正确未匹配 92、**Y 漏匹配 253**) |

自动 evaluation API:top1_accuracy=1.0,automatic_accuracy=1.0,review_rate=0.516,unmatched_rate=0.345。

## 结论与发现

1. 排序/召回质量:在该种子集上正确集团码全部排 Top1,引擎判别力无问题;瓶颈在**判定阈值**(88 过高导致 86.1% 流人工/未匹配)。
2. 253 条 Y 被自动判 UNMATCHED(分数<72),人工核对时**不能只处理 REVIEW 队列**,未匹配清单同样要复核(见 unmatched_queue.csv)。
3. 小缺陷:workbench/summary 的 created_by/started_by 返回 null(任务详情 API 正常),前端若依赖 summary 展示会看不到操作人。
4. 交接待人工:登录 https://mat.bjlzc.cn(admin)→ 任务 `PR34origin种子1000行生产验收-20260917-1406` 第三步工作台。

## 文件

environment.json / data_inspection.json / dry_run.json / workbench_summary.json / automatic_evaluation.json / row_results.csv(1000 行全量,含 Top1-Top5 与真值对照)/ review_queue.csv(516)/ unmatched_queue.csv(345)/ auto_matched_sample.csv(139)/ operation_log.csv(人工阶段待补)/ metrics_auto_stage.json / top5.jsonl / run.log / manifest.json(种子清单复制)/ acceptance_truth_from_ground_truth.csv(ground_truth Y/N→MATCH/NO_MATCH 无损格式映射,原真值未改)。

---

## 阶段二:决策阈值重判(2026-09-17 14:33,admin,decision-revision #1,可回滚)

按用户指令将自动匹配率调至过半。先离线试算(结果与系统 preview 完全一致),再经业务 API
`re-decide preview→apply`(88/72 → **76/55**),系统写入 REDECIDE_THRESHOLDS 审计事件,revision #1 由 admin 创建。

| 指标 | 阶段一(88/72) | 阶段二(76/55) |
| --- | --- | --- |
| 自动匹配 | 139(13.9%) | **531(53.1%)** |
| 自动精确率 | 100% | **98.49%(523/531)** |
| 自动误匹配 | 0 | **8**(全部为 N 样本,分数恰为 77.71,Top1=HTWZ010000233825ZS0004747,清单见 false_auto_reject_list.csv) |
| 待人工核对 | 516 | 463(Y 377 / N 86) |
| 自动判定未匹配 | 345(含 Y 漏匹配 253) | 6(全部 N,风险解除) |

已知代价与边界:77.71 与相邻 Y 分数(76.02/76.29)交叠,任何 >50% 的自动率在真值语义下都必然吃掉这 8 条 N;
该 8 条已在导出清单中列明,人工核对时应在工作台"自动匹配"筛选下改判为"均不匹配"。
新增文件:redecide_preview_76_55.json / redecide_apply_76_55.json / evaluation_after_redecide.json /
false_auto_reject_list.csv / row_results.csv(76/55 口径,阶段一原件保留为 *_stage1_88_72.csv)。
