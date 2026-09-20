import fs from 'node:fs'
import path from 'node:path'
import process from 'node:process'

const root = process.cwd()
const workspace = fs.readFileSync(path.join(root, 'src/views/TaskWorkspaceBase.vue'), 'utf8')

for (const token of [
  'value_mapping: Record<string, string>',
  'enum_candidate?: boolean',
  'ruleSourceEnumValues',
  'ruleTargetEnumValues',
  'ruleValueMappingEligible',
  '手工确认，不自动转换',
  '选择目标 Excel 已有值',
  'source_columns: cloneDocument(sourceColumns.value)',
  'target_columns: cloneDocument(targetColumns.value)',
]) {
  if (!workspace.includes(token)) throw new Error(`value mapping contract missing: ${token}`)
}

if (workspace.includes('rule.value_mapping[sourceValue] = ruleTargetEnumValues(rule)[0]')) {
  throw new Error('value mapping must never auto-select a target value')
}
if (!workspace.includes('if (targetValue) rule.value_mapping[sourceValue] = targetValue')) {
  throw new Error('manual mapping setter missing')
}
if (!workspace.includes('else delete rule.value_mapping[sourceValue]')) {
  throw new Error('mapping must be clearable')
}
const enumGuards = workspace.match(/column\?\.enum_candidate === true \? enumValues\(column\) : \[\]/g) ?? []
if (enumGuards.length < 2) {
  throw new Error('value mapping UI must require enum profiling metadata on both source and target fields')
}

console.log('value mapping contract checks passed')
