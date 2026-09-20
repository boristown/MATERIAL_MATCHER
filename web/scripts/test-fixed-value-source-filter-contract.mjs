import fs from 'node:fs'
import path from 'node:path'
import process from 'node:process'

const root = process.cwd()
const read = file => fs.readFileSync(path.join(root, file), 'utf8')
const workspace = read('src/views/TaskWorkspaceBase.vue')

for (const label of ['字段', '固定值', '例如：Z001']) {
  if (!workspace.includes(label)) throw new Error(`Fixed-value mapping UI missing: ${label}`)
}
if (!workspace.includes('side.fields = []')) throw new Error('Switching to fixed-value mode must clear selected fields')
if (!workspace.includes('side.fixed_value = null')) throw new Error('Switching back to field mode must clear fixed_value')
if (!workspace.includes("v-if=\"sideMode(scope.row.source) === 'fixed'\"")) throw new Error('Source fixed-value mode must render an input')
if (!workspace.includes("v-if=\"sideMode(scope.row.target) === 'fixed'\"")) throw new Error('Target fixed-value mode must render an input')
if (!workspace.includes('sideReady(rule.source) && sideReady(rule.target)')) throw new Error('Config validity must accept fixed-value sides')

if (!workspace.includes('固定值参与字段匹配规则')) throw new Error('UI must distinguish fixed values from source row filtering')
if (!workspace.includes("const filterMatch = ref<'exact' | 'contains'>('exact')")) throw new Error('source_filter match-mode state missing')
if (!workspace.includes("filterMatch.value = flt?.match === 'contains' ? 'contains' : 'exact'")) throw new Error('source_filter match mode must restore from profiles')
if (!workspace.includes('match: filterMatch.value')) throw new Error('source_filter match mode must persist')
if (!workspace.includes('value="exact"') || !workspace.includes('value="contains"')) throw new Error('source_filter must expose exact and contains')
if (!workspace.includes('value="include"') || !workspace.includes('value="exclude"')) throw new Error('source_filter must expose include and exclude')

console.log('fixed value + source filter contract checks passed')
