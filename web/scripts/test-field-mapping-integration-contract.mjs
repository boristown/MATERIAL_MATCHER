import fs from 'node:fs'

const workspace = fs.readFileSync(new URL('../src/views/TaskWorkspaceBase.vue', import.meta.url), 'utf8')
const modeAdapter = fs.readFileSync(new URL('../src/matchMode.ts', import.meta.url), 'utf8')
const pkg = JSON.parse(fs.readFileSync(new URL('../package.json', import.meta.url), 'utf8'))

function requireText(text, token, message) {
  if (!text.includes(token)) throw new Error(message + ': missing ' + token)
}

requireText(workspace, '精确匹配', 'STEP1 must expose exact business mode')
requireText(workspace, '智能匹配', 'STEP1 must expose intelligent business mode')
requireText(workspace, '值转换（可选）', 'enum value mapping editor must exist')
requireText(workspace, '自动识别只提供候选值，必须手工确认对应关系', 'automatic enum detection must not auto-pair values')
requireText(workspace, 'value_mapping_source_values', 'manual source enum values must remain editable')
requireText(workspace, 'value_mapping_target_values', 'manual target enum values must remain editable')
requireText(workspace, 'enum_candidate', 'column profile enum metadata must be consumed')
requireText(modeAdapter, '__apiMatcher', 'legacy matcher preservation adapter must exist')
requireText(modeAdapter, 'contains/fuzzy/hybrid/numeric', 'legacy backend matchers must remain compatible')

const template = workspace.slice(workspace.indexOf('<template>'))
for (const forbidden of ['人工确认下限', '模糊相似', '综合(字符+语义)', '语义相似(bge)', '字段映射与权重', 'label="权重"', 'label="包含"']) {
  if (template.includes(forbidden)) throw new Error('business UI leaked removed algorithm term: ' + forbidden)
}

for (const script of ['test:value-mapping-contract', 'test:match-mode-contract', 'test:single-threshold-contract', 'test:field-mapping-integration-contract']) {
  if (!pkg.scripts.build.includes('npm run ' + script)) throw new Error('build does not execute ' + script)
}

console.log('field mapping integration contract: OK')
