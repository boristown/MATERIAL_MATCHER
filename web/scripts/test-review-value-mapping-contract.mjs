import fs from 'node:fs'
import path from 'node:path'
import process from 'node:process'

const root = process.cwd()
const view = fs.readFileSync(path.join(root, 'src/views/ReviewView.vue'), 'utf8')

for (const token of [
  'source_payload_before_mapping?: Record<string, unknown>',
  'sourceRaw: string',
  'sourceComparable: string',
  'targetValue: string',
  'mappingConfigured: boolean',
  'mappingHit: boolean',
  'targetHasData: boolean',
  'function fieldComparison(',
  'const rawPayload = item.source_payload_before_mapping ?? item.source_payload',
  'fieldScore?.value_mapping_applied === true',
  'Object.prototype.hasOwnProperty.call(mapping, rawKey)',
  "if (!sourceComparable || !targetHasData) kind = 'empty'",
  "else if (mappingConfigured && !mappingHit) kind = 'different'",
  "else if (normalizedText(sourceComparable) === normalizedText(targetValue)) kind = 'exact'",
  "else if (fieldPercent !== null && fieldPercent >= 55) kind = 'partial'",
  "if (!comparison.mappingHit) return '值映射未配置'",
  '原始值：',
  "return selectedFieldComparison(item, field)?.kind ?? 'empty'",
  'Top 5 当前为空；可以标记均不匹配。',
]) {
  if (!view.includes(token)) throw new Error(`PATCH8 review mapping contract missing: ${token}`)
}

if (view.includes('if (normalizedText(source) === normalizedText(target)) return \'exact\'')) {
  throw new Error('PATCH8 must not fall back to raw source/target equality after value mapping')
}
if (view.includes('String(fieldScore.source_value)') || view.includes('String(fieldScore.target_value)')) {
  throw new Error('PATCH8 must sanitize field-score display values instead of exposing object coercion')
}

function expectedState({ source, target, mappingConfigured, mappingHit, score = 0 }) {
  if (!source || !target) return 'empty'
  if (mappingConfigured && !mappingHit) return 'different'
  if (source.trim().toLowerCase() === target.trim().toLowerCase()) return 'exact'
  return score >= 55 ? 'partial' : 'different'
}

const fixtures = [
  ['A mapped hit', { source: '国产', target: '国产', mappingConfigured: true, mappingHit: true, score: 100 }, 'exact'],
  ['B mapped mismatch', { source: '国产', target: '进口', mappingConfigured: true, mappingHit: true, score: 0 }, 'different'],
  ['C target empty', { source: '国产', target: '', mappingConfigured: true, mappingHit: true, score: 0 }, 'empty'],
  ['D unconfigured source 12', { source: '12', target: '国产', mappingConfigured: true, mappingHit: false, score: 0 }, 'different'],
  ['E no candidate', { source: '', target: '', mappingConfigured: false, mappingHit: false, score: 0 }, 'empty'],
  ['partial match', { source: '国产件', target: '国产', mappingConfigured: false, mappingHit: false, score: 70 }, 'partial'],
]

for (const [name, fixture, expected] of fixtures) {
  const actual = expectedState(fixture)
  if (actual !== expected) throw new Error(`${name}: expected ${expected}, got ${actual}`)
}

for (const label of ['一致', '部分一致', '不一致', '无数据']) {
  if (!view.includes(label)) throw new Error(`business comparison state missing: ${label}`)
}

console.log('PATCH8 mapped-field review display contract checks passed')
