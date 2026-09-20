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
  'valueMappingConfiguredCount',
  'valueMappingHasDetectedCandidates',
  'label="值映射"',
  'popper-class="value-mapping-popover"',
  '配置候选',
  '已配 {{ valueMappingConfiguredCount(scope.row) }} 项',
  '添加映射',
  '仅在编码或枚举值不一致时配置；系统不会自动建立对应关系。',
  '可手工新增，例如 10、11',
  '可手工新增，例如 国产、进口',
  '手工选择或输入目标值',
  '未配置值：',
  'source_columns: cloneDocument(sourceColumns.value)',
  'target_columns: cloneDocument(targetColumns.value)',
]) {
  if (!workspace.includes(token)) throw new Error(`value mapping contract missing: ${token}`)
}

if (!workspace.includes('<el-popover') || !workspace.includes('label="值映射" width="112"')) {
  throw new Error('value mapping must live in a dedicated lightweight column')
}
const targetStart = workspace.indexOf('<el-table-column label="目标侧"')
const valueMappingStart = workspace.indexOf('<el-table-column label="值映射"')
if (targetStart < 0 || valueMappingStart < 0 || valueMappingStart <= targetStart) {
  throw new Error('value mapping column must follow the target field column')
}
const targetColumnSource = workspace.slice(targetStart, valueMappingStart)
if (targetColumnSource.includes('value-mapping-popover-content') || targetColumnSource.includes('value-candidate-editor')) {
  throw new Error('value mapping editor must not be nested inside the target field cell')
}
if (workspace.includes('expandedValueMappings') || workspace.includes('isValueMappingExpanded') || workspace.includes('toggleValueMapping')) {
  throw new Error('inline expanding value mapping UI must not return')
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
