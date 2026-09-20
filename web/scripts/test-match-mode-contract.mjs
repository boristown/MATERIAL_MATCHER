import fs from 'node:fs'

const workspace = fs.readFileSync(new URL('../src/views/TaskWorkspaceBase.vue', import.meta.url), 'utf8')
const adapter = fs.readFileSync(new URL('../src/matchMode.ts', import.meta.url), 'utf8')

const marker = '<el-table-column label="匹配方式"'
const start = workspace.indexOf(marker)
if (start < 0) throw new Error('field match-mode selector missing')
const end = workspace.indexOf('</el-table-column>', start)
if (end < 0) throw new Error('field match-mode selector is malformed')
const selector = workspace.slice(start, end)

if (!selector.includes('label="精确匹配" value="exact"')) throw new Error('exact business mode missing')
if (!selector.includes('label="智能匹配" value="semantic"')) throw new Error('semantic business mode missing')
for (const forbidden of ['完全一致', '模糊相似', '综合(字符+语义)', '语义相似(bge)', 'value="fuzzy"', 'value="hybrid"', 'value="contains"']) {
  if (selector.includes(forbidden)) throw new Error(`field matcher UI leaks legacy/algorithm option: ${forbidden}`)
}

if (!workspace.includes("adaptRulesFromApi(cloneDocument(value.rules))")) throw new Error('API -> business matcher adapter is not used')
if (!workspace.includes('adaptRulesToApi(rules.value)')) throw new Error('business matcher -> API adapter is not used')
if (!workspace.includes('setBusinessMatchMode(rule, value)')) throw new Error('explicit matcher changes must update API matcher state')

for (const expected of [
  "if (hint === 'material_name') return { matcher: 'semantic', weight: 40 }",
  "if (hint === 'model') return { matcher: 'semantic', weight: 25 }",
  "if (hint === 'specification') return { matcher: 'semantic', weight: 15 }",
  "if (hint === 'manufacturer') return { matcher: 'semantic', weight: 10 }",
]) {
  if (!workspace.includes(expected)) throw new Error(`new auto mapping must keep intelligent matching defaults: ${expected}`)
}
if (!workspace.includes("if (hint === 'material_group' || hint === 'unit') return { matcher: 'exact', weight: 10 }")) {
  throw new Error('material group and unit auto mappings must keep exact matching defaults')
}

if (!adapter.includes("=== 'exact' ? 'exact' : 'semantic'")) throw new Error('legacy matchers must collapse to the intelligent business mode')
if (!adapter.includes('originalApiMatcher') || !adapter.includes('delete out.__apiMatcher')) {
  throw new Error('legacy API matcher preservation is missing')
}
if (!adapter.includes('rule.__apiMatcher = businessMode')) throw new Error('explicit user changes must persist exact/semantic only')

console.log('field match-mode simplification contract checks passed')
