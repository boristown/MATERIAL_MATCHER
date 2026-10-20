import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const read = path => readFileSync(fileURLToPath(new URL(path, import.meta.url)), 'utf8')

const workspace = read('../src/views/TaskWorkspaceBase.vue')
for (const token of [
  'veto_threshold?: number | null',
  'function setRuleCombine(rule: Rule, mode: string)',
  'function setRuleSeparator(rule: Rule, value: string)',
  'function toggleRuleVeto(rule: Rule, enabled: boolean)',
  'rule.veto_threshold = enabled ? 60 : null',
  '拼接比对',
  '取最高分',
  '取首个非空',
  '一票否决',
  'setRuleCombine(scope.row, String($event))',
  'toggleRuleVeto(scope.row, Boolean($event))',
]) {
  if (!workspace.includes(token)) throw new Error(`规则卡拼接/否决契约缺失: ${token}`)
}

const models = read('../../src/material_matcher/domain/models.py')
if (!models.includes('veto_threshold: float | None = Field(default=None, ge=0, le=100)')) {
  throw new Error('后端 RuleConfig.veto_threshold 契约缺失')
}

const scorer = read('../../src/material_matcher/matching/scorer.py')
for (const token of [
  'semantic_matcher = bool(',
  'and not semantic_matcher',
  'score=0.0 if vetoed else _clamp01(float(best_score))',
  'if result.vetoed:',
  'vetoed = True',
  'if vetoed:\n        raw = 0.0',
  'and not vetoed',
  'score_before_veto=_clamp01(float(best_score)) if vetoed else None',
]) {
  if (!scorer.includes(token)) throw new Error(`scorer 一票否决契约缺失: ${token}`)
}

// 语义规则禁否决（现场 96% 归零根因防护）+ 导出否决对照页 + 前端联动
const modelsForVeto = read('../../src/material_matcher/domain/models.py')
if (!modelsForVeto.includes('def assert_veto_rules_supported')) throw new Error('保存期语义+否决校验契约缺失')
const exporter = read('../../src/material_matcher/services/result_export_service.py')
for (const token of ['veto_compare', '否决对照（保留否决前/后结果；不改变正式结果）', '否决前相似度', 'score_before_veto']) {
  if (!exporter.includes(token)) throw new Error(`否决对照导出契约缺失: ${token}`)
}
if (!workspace.includes('智能匹配（语义）不支持一票否决')) throw new Error('前端语义+否决联动契约缺失')

console.log('veto + combine contract checks passed')
