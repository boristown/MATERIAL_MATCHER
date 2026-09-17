# 运维 Agent：origin_data.zip 种子驱动端到端验收提示词

> 用途：在 PR #34 完成后，由运维/部署 Agent 在真实测试环境执行完整业务验收，并把可复核证据提交到 GitHub。不得只跑单元测试，也不得只看自动匹配率。

```text
你负责 MATERIAL_MATCHER 的一次完整端到端验收测试。

仓库：
https://github.com/boristown/MATERIAL_MATCHER

被测分支：
test/realistic-material-fixture-1000

被测 PR：
#34

目标：
验证基于仓库根目录 origin_data.zip 原始公开种子生成的 1000 行测试集，能完整走通“数据上传 → 自动匹配 → 人工调整 → 最终结果”，并对 ground_truth.csv 做逐条核对。

特别要求：
1. 不允许修改 ground_truth.csv 来迎合系统结果；
2. 不允许删除失败样本；
3. 不允许为了让结果好看而无依据降低阈值；
4. 不允许只报告总体匹配率，必须区分自动正确、自动误匹配、人工正确、人工错误、正确未匹配、漏匹配；
5. 对 ground_truth.csv 中“预期是否可匹配=N”的条目，必须实际检查候选。若没有正确候选，要在人工工作台明确选择“均不匹配/不通过/标记未匹配”，不能随便选一个最接近的集团码；
6. 必须保留上述人工选择“不通过”的过程和结果证据；
7. 测试结束后将文本/CSV/JSON证据提交 GitHub，并创建独立测试结果 PR，不要直接修改 main，不要合并。

第一阶段：准备代码与生成数据

A. 从 PR #34 的最新 head 开始测试，记录 commit SHA。
B. 确认仓库根目录存在 origin_data.zip。
C. 运行：

python scripts/generate_realistic_test_data.py

D. 确认生成：
- tests/fixtures/realistic_materials/generated/source_materials_1000.xlsx
- tests/fixtures/realistic_materials/generated/target_group_codes_from_origin.xlsx
- tests/fixtures/realistic_materials/generated/ground_truth.csv
- tests/fixtures/realistic_materials/generated/manifest.json

E. 检查 manifest.json：
- source_rows = 1000
- expected_matched = 900
- expected_unmatched = 100
- Z001 = 700
- Z006 = 300
- high_confidence_seed_pairs_by_type 中 Z001、Z006 都必须 > 0
- seed_zip_sha256 必须存在
- seed_files_scanned 必须来自 origin_data.zip

如果这里失败，立即停止业务验收，把失败日志提交 GitHub，不要自己换一套数据继续测试。

第二阶段：部署和创建真实业务任务

A. 使用当前被测分支启动实际后端和前端。
B. 通过正常业务 UI 登录，不直接改数据库制造结果。
C. 在“第一步 · 数据上传”中：
- 左侧上传 source_materials_1000.xlsx
- 右侧上传 target_group_codes_from_origin.xlsx
D. 检查系统识别的行数、字段、sheet、表头是否正确。
E. 按现有 Z001/Z006 业务映射完成字段映射和匹配配置。
F. 记录实际使用的：
- 自动匹配阈值
- 人工确认下限
- matcher
- 字段权重
- 任务 ID
- 创建账号/启动账号
- 创建时间/启动时间

不得为了追求 90% 自动匹配率而修改规则。900/100 是业务真值，不是自动判定目标。

第三阶段：自动匹配结果核对

等任务计算完成后，将系统所有 1000 条结果导出或通过 API 提取成一份 row_results.csv，至少包含：
- 源表行号
- 物料编码
- 系统状态
- Top1 集团码
- Top1 分数
- Top2 集团码/分数（如有）
- Top5 集团码列表
- 最终集团码
- 匹配方式（自动/人工/未匹配）

使用 ground_truth.csv 按物料编码关联，计算：
- 900 条 Y 中 Top1 正确数/准确率
- 900 条 Y 中 Top5 包含正确集团码数/召回率
- 自动匹配条数
- 自动匹配中正确条数
- 自动误匹配条数
- REVIEW/待人工条数
- 系统未匹配条数
- 900 条 Y 中正确集团码完全未进入 Top5 的数量
- 100 条 N 中被系统自动错误匹配的数量

第四阶段：人工调整，必须真实执行“均不匹配/不通过”

这是本次测试的强制验收项。

A. 对所有进入人工工作台的记录逐条或按安全批量方式处理。
B. 对 ground_truth=Y：
- 如果正确集团码在 Top5，人工选择正确候选；
- 如果正确集团码不在 Top5，不得选择错误候选，记录为“正确目标未召回”。
C. 对 ground_truth=N：
- 检查 Top5；
- 由于真值定义为目录中没有正确对应项，必须选择“均不匹配/不通过/标记未匹配”；
- 禁止为了完成任务而选择一个相似候选。
D. 至少对 10 条 N 样本做详细过程记录；如果 100 条 N 都进入人工工作台，则全部 100 条都应正确处理。

对每个“人工选择不通过”的证据至少记录：
- 物料编码
- 源表行号
- 物料名称/型号/规格
- Top1～Top5 集团码和分数
- 为什么候选不成立（型号、牌号、规格、封装、标准等实际差异）
- 实际点击/调用的操作：均不匹配/标记未匹配
- 操作账号
- 操作时间
- 操作后状态

不要只写“人工判断不匹配”，必须能看出候选是什么、为何拒绝、最终系统状态是什么。

第五阶段：最终结果

所有人工操作完成后生成 STEP4 最终结果。

检查：
- 源数据总数 1000
- 自动匹配数
- 人工匹配数
- 未匹配数
- 待处理数应为 0（若不是 0，说明测试未完成）
- 创建/启动账号与时间正确
- 最终结果生成时间存在
- 最终结果能追溯源表行号和目标表行号

再次将最终结果与 ground_truth.csv 做逐条比较，输出 final_evaluation.csv。

最终至少统计：
- 最终正确匹配数（Y 且最终集团码等于真值）
- 最终错误匹配数
- Y 被错误标记未匹配数
- N 被错误分配集团码数
- N 正确保持未匹配数
- 最终整体业务正确率
- Z001 正确率
- Z006 正确率
- 各场景 exact_seed / space_punctuation / standard_format / missing_secondary / combined / unmatched_variant 的结果

第六阶段：上传 GitHub 测试证据

从 PR #34 最新 head 创建独立分支，例如：
ops/pr34-origin-seed-e2e-YYYYMMDD-HHMM

不要提交生成出来的 xlsx/png 等被仓库策略禁止的二进制文件。

在以下目录提交文本证据：

test-results/origin-seed-e2e/<时间戳>/

至少包含：
- summary.md
- environment.json
- manifest.json（本次生成结果复制为文本）
- row_results.csv
- final_evaluation.csv
- manual_rejections.csv
- operation_log.csv

summary.md 必须写清：
- 被测 commit SHA
- 环境和版本
- 任务 ID
- 阈值和配置摘要
- 自动阶段指标
- 人工阶段指标
- 最终阶段指标
- 所有发现的问题
- 是否存在自动误匹配
- 是否存在 N 样本被错误匹配
- 是否存在 Y 真值未进入 Top5
- 你认为测试“通过/不通过”的依据

manual_rejections.csv 必须至少包含：
material_code,source_row,material_name,model,spec,top1_code,top1_score,top2_code,top2_score,top3_code,top3_score,top4_code,top4_score,top5_code,top5_score,reject_reason,operator,operated_at,final_status

operation_log.csv 使用系统真实审计/操作日志，不要人工伪造时间和账号。

提交后创建 Pull Request，base 指向：
test/realistic-material-fixture-1000

PR 标题建议：
test: PR34 origin seed 1000-row end-to-end acceptance evidence

不要合并该测试 PR。

最后把测试结果 PR URL、被测 commit SHA、任务 ID 和你得到的核心指标发回给我。之后由上游评审 Agent 独立读取 GitHub 证据，判定本次验收最终“通过”或“不通过”。
```
