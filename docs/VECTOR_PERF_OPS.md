# 向量化性能与避免重算 · 现场操作指引（1.3.24 起）

## 原理一句话
向量缓存键从「方案签名+文本」升级为「模型+文本」：**改规则不再触发全量重算**；
只有检索文本真正变化的行才需要计算，且支持多进程填满 CPU。

## 明日部署标准动作（顺序重要）

1. 升级 1.3.24 增量包（`./upgrade.sh`，自动备份/健康校验）。
2. **改方案之前**，对现网每个"将调整字段逻辑"的方案先做一次缓存迁移（只读+登记，几分钟内完成，不跑模型）：
   ```bash
   /opt/material_matcher/current/runtime/bin/python3 -m material_matcher.cli embedding-rekey \
     --profile <方案ID> [--version <调整前的版本号>] [--dry-run]
   ```
   输出 `migrated` = 迁移登记的文本数；`legacy_vectors_missing` 大 → 说明该方案索引较旧，迁移收益有限。
3. 配置多进程向量化（128 核机器）：在 `/etc/material_matcher/server.env` 追加后重启服务：
   ```bash
   MATERIAL_MATCHER_EMBEDDING_WORKERS=4
   # 不再需要手工设 INTRA_THREADS（自动 = CPU核数/workers）
   ```
4. 然后在界面调整方案：型号规格+封装 **拼接比对**（规则卡"多字段组合"列选"拼接比对"，
   可加分隔符；两列都选 型号规格/封装 多字段）。
5. 跑任务观察：
   - 封装为空的行 → 文本未变 → **缓存直接命中，零计算**；
   - 封装有值的行 → 新文本 → 多进程计算（预期 100 万行全量 ≈ 25-35 分钟，部分增量按比例缩短）。
   - STEP2 看板与页面操作应保持流畅（GIL 修复）。

## 更优方案（如果可行，优先用）
**召回文本不动，拼接只放计分规则**（字符级 精确/模糊 匹配型号+封装）：
向量索引 100% 复用，**重算 = 0 分钟**。型号/封装是字母数字串，字符匹配本来就比向量更准。
只有当"封装差异需要语义召回"时才需要重建索引。

## 参数速查
| 变量 | 默认 | 说明 |
|---|---|---|
| MATERIAL_MATCHER_EMBEDDING_WORKERS | 1 | >1 时多进程分片 embedding（每进程独立 ORT 会话，intra 自动=核数/workers） |
| MATERIAL_MATCHER_EMBEDDING_INTRA_THREADS | 0 | 设了则每进程用它；一般留空由 workers 自动推导 |
| MATERIAL_MATCHER_EMBEDDING_MAX_LENGTH | 256 | 先跑 `material-matcher benchmark embedding` 看 token P99 再决定是否降到 96/128 |
| MATERIAL_MATCHER_EMBEDDING_BATCH_SIZE | 128 | 128 核机器可试 256 |

## 回滚
- 缓存新键与旧键**双写共存**：回滚到 1.3.23 及以前版本，旧键仍命中，不会退化成重算。
- WORKERS 出问题：server.env 删掉该行重启即回单进程。
