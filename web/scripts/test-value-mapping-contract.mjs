import fs from 'node:fs'
import path from 'node:path'
import process from 'node:process'

const root = process.cwd()
const workspace = fs.readFileSync(path.join(root, 'src/views/TaskWorkspaceBase.vue'), 'utf8')

for (const token of [
  'value_mapping: Record<string, string>',
  'value_mapping_source_values: string[]',
  'value_mapping_target_values: string[]',
  'enum_candidate?: boolean',
  'ruleSourceEnumValues',
  'ruleTargetEnumValues',
  'ruleSourceValueOptions',
  'ruleTargetValueOptions',
  'ruleValueMappingVisible',
  '自动识别只提供候选值，必须手工确认对应关系',
  '可手工新增，例如 10、11',
  '可手工新增，例如 国产、进口',
  '手工选择或输入目标值',
  '未配置值：',
  'source_columns: cloneDocument(sourceColumns.value)',
  'target_columns: cloneDocument(targetColumns.value)',
]) {
  if (!workspace.includes(token)) throw new Error(`value mapping contract missing: ${token}`)
}

if (workspace.includes('rule.value_mapping[sourceValue] = ruleTargetEnumValues(rule)[0]')) {
  throw new Error('value mapping must never auto-select a target value')
}
if (!workspace.includes('rule.value_mapping[source] = target')) {
  throw new Error('manual mapping setter missing')
}
if (!workspace.includes('delete rule.value_mapping[source]')) {
  throw new Error('mapping must be clearable')
}
if (!workspace.includes('return isProfileEditorMode.value')) {
  throw new Error('existing profiles must expose manual value mapping even without column-profile metadata')
}
if (!workspace.includes('allow-create')) {
  throw new Error('manual source/target values must be creatable')
}
if (!workspace.includes('Object.keys(rule.value_mapping ?? {})') || !workspace.includes('Object.values(rule.value_mapping ?? {})')) {
  throw new Error('saved mappings must remain editable when original enum candidates are unavailable')
}

console.log('value mapping contract checks passed')
