import fs from 'node:fs'
import path from 'node:path'
import process from 'node:process'

const root = process.cwd()
const read = file => fs.readFileSync(path.join(root, file), 'utf8')

const workspace = read('src/views/TaskWorkspaceBase.vue')

/* 字段映射两侧都必须支持“字段 / 固定值”两种互斥来源。 */
for (const label of ['字段', '固定值', '例如：Z001']) {
  if (!workspace.includes(label)) throw new Error(`Fixed-value mapping UI missing: ${label}`)
}
if (!workspace.includes('side.fields = []')) throw new Error('Switching to fixed-value mode must clear field selections')
if (!workspace.includes('side.fixed_value = null')) throw new Error('Switching back to field mode must clear fixed_value')
if (!workspace.includes("v-if=\"sideMode(scope.row.source) === 'fixed'\"")) throw new Error('Source fixed-value mode must render an input instead of a field selector')
if (!workspace.includes("v-if=\"sideMode(scope.row.target) === 'fixed'\"")) throw new Error('Target fixed-value mode must render an input instead of a field selector')
if (!workspace.includes('rule.source.fields') || !workspace.includes('rule.target.fields')) throw new Error('Compatibility checks must continue to use real field lists, not fixed values as pseudo-columns')
if (!workspace.includes('sideReady(rule.source) && sideReady(rule.target)')) throw new Error('Config validity must accept a ready fixed-value side without requiring a field name')

/* 固定值与源数据过滤器必须在业务语义上分离。 */
if (!workspace.includes('固定值参与字段匹配规则；下方“源数据过滤”决定本方案实际处理哪些源数据行')) {
  throw new Error('UI must explain the difference between fixed values and source filtering')
}

/* source_filter 的 include/exclude 与 exact/contains 都必须可保存和恢复。 */
if (!workspace.includes("const filterMatch = ref<'exact' | 'contains'>('exact')")) throw new Error('source_filter match mode state missing')
if (!workspace.includes("filterMatch.value = flt?.match === 'contains' ? 'contains' : 'exact'")) throw new Error('source_filter match mode must be restored from a saved profile')
if (!workspace.includes('match: filterMatch.value')) throw new Error('source_filter match mode must be persisted instead of hard-coded to exact')
if (!workspace.includes('value="exact"') || !workspace.includes('value="contains"')) throw new Error('source_filter UI must expose exact and contains')
if (!workspace.includes('value="include"') || !workspace.includes('value="exclude"')) throw new Error('source_filter UI must expose include and exclude')
if (!workspace.includes('默认值，例如：Z001')) throw new Error('source_filter should expose a business-friendly default/example value')

console.log('fixed value + source filter contract checks passed')
