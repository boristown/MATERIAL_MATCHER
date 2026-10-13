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
  'vetoed = bool(rule.veto_threshold is not None and best_score < float(rule.veto_threshold) / 100.0)',
  'score=0.0 if vetoed else _clamp01(float(best_score))',
  'if result.vetoed:',
  'vetoed = True',
  'if vetoed:\n        raw = 0.0',
  'and not vetoed',
]) {
  if (!scorer.includes(token)) throw new Error(`scorer 一票否决契约缺失: ${token}`)
}

console.log('veto + combine contract checks passed')
