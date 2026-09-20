import fs from 'node:fs'
import path from 'node:path'
import process from 'node:process'
import ts from 'typescript'

const root = process.cwd()
const read = file => fs.readFileSync(path.join(root, file), 'utf8')

const workspace = read('src/views/TaskWorkspaceBase.vue')
const upload = read('src/components/DualExcelUploadPanel.vue')

if (!workspace.includes('字段很多时无需逐个录入')) throw new Error('Normal profile editor must explain template-driven field recognition')
if (!workspace.includes(`:mode="isProfileEditorMode ? 'template' : 'data'"`)) throw new Error('Dual upload must enter template mode while editing a normal profile')
if (!workspace.includes("!isProfileEditorMode || !isCompositeProfile")) throw new Error('Normal profile editor must show template upload while composite profile editor uses its own panel')
if (!workspace.includes('...srcHeaders.value') || !workspace.includes('...tgtHeaders.value')) throw new Error('Recognized template headers must feed profile field selectors')
if (!workspace.includes('baseAdvanced.template_schema')) throw new Error('Recognized template schema must be persisted')
if (!workspace.includes('rememberedSourceFields') || !workspace.includes('rememberedTargetFields')) throw new Error('Saved template schema must be restored')
if (workspace.includes('<label v-if="!isCompositeProfile"><span>客户物料标识字段</span>')) throw new Error('Do not duplicate the customer identifier selector next to scheme metadata')
if (!workspace.includes('placeholder="选择客户模板字段"') || !workspace.includes('placeholder="选择集团码模板字段"')) throw new Error('Mapping selectors must prefer recognized template headers')
if (!workspace.includes('@click="autoMap">自动推荐映射</el-button>')) throw new Error('Profile editor must expose automatic mapping')
if (!workspace.includes('!isCompositeProfile.value && source.value && target.value && !rules.value.length')) throw new Error('Fresh normal profile must auto-map after both templates are ready')
const autoMapSource = read('src/utils/autoMap.ts')
for (const token of [
  'const usedSources = new Set<string>()',
  'const usedTargets = new Set<string>()',
  'usedSources.has(item.sourceColumn.header)',
  'usedTargets.has(item.targetColumn.header)',
  'AUTO_MAP_MIN_SCORE = 70',
  'AUTO_MAP_AMBIGUITY_MARGIN = 8',
  'best.score - runnerUp.score < AUTO_MAP_AMBIGUITY_MARGIN',
]) {
  if (!autoMapSource.includes(token)) throw new Error(`Automatic field recommendation must stay conservative and one-to-one: ${token}`)
}
for (const token of [
  'selectOneToOneAutoMapPairs(sourceCandidates, targetCandidates)',
  'makeRule([item.sourceColumn.header], [item.targetColumn.header]',
  '自动推荐仅生成一对一字段映射',
  '多字段组合映射可按需人工添加',
  "ElMessage.info('未发现足够明确的一对一字段映射，请人工连线确认')",
]) {
  if (!workspace.includes(token)) throw new Error(`STEP1 auto-map product contract missing: ${token}`)
}
const autoMapBody = workspace.slice(workspace.indexOf('function autoMap(): void {'), workspace.indexOf('function defaultRule(): Rule {'))
if (autoMapBody.includes('defaultRule()')) throw new Error('Automatic recommendation must not force a fallback mapping when confidence is low')
if (autoMapBody.includes('makeRule(item.sourceFields, item.targetFields')) throw new Error('Automatic recommendation must not create multi-field rules')

const transpiledAutoMap = ts.transpileModule(autoMapSource, {
  compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2020 },
}).outputText
const autoMapModule = await import(`data:text/javascript;base64,${Buffer.from(transpiledAutoMap).toString('base64')}`)
const selectPairs = autoMapModule.selectOneToOneAutoMapPairs

const fiveSources = Array.from({ length: 5 }, (_, index) => ({ header: `字段${index + 1}` }))
const fiveTargets = Array.from({ length: 5 }, (_, index) => ({ header: `字段${index + 1}` }))
const fivePairs = selectPairs(fiveSources, fiveTargets)
if (fivePairs.length !== 5) throw new Error(`5x5 exact fields should recommend exactly five one-to-one pairs, got ${fivePairs.length}`)
if (new Set(fivePairs.map(item => item.sourceColumn.header)).size !== fivePairs.length) throw new Error('Automatic recommendation reused a source field')
if (new Set(fivePairs.map(item => item.targetColumn.header)).size !== fivePairs.length) throw new Error('Automatic recommendation reused a target field')

const bestOnly = selectPairs(
  [{ header: '产品名称' }],
  [{ header: '产品名' }, { header: '产品名称' }],
)
if (bestOnly.length !== 1 || bestOnly[0].targetColumn.header !== '产品名称') throw new Error('A source field with multiple candidates must choose only its clear best target')

const targetCompetition = selectPairs(
  [{ header: '产品名称' }, { header: '清洗后产品名称' }],
  [{ header: '产品名称' }],
)
if (targetCompetition.length !== 1 || targetCompetition[0].targetColumn.header !== '产品名称') throw new Error('Multiple sources competing for one target must result in only one occupied target')

const ambiguous = selectPairs(
  [{ header: '分类描述' }],
  [{ header: '清洗后分类描述' }, { header: '标准化分类描述' }],
)
if (ambiguous.length !== 0) throw new Error('Ambiguous equal-strength targets must be left for manual mapping')

const noGuess = selectPairs(
  [{ header: '二层分类描述' }, { header: '三层分类描述' }, { header: '四层分类描述' }, { header: '五层分类描述' }],
  [{ header: '清洗后大类' }, { header: '清洗后中类' }, { header: '清洗后小类' }, { header: '清洗后细类' }],
)
if (noGuess.length !== 0) throw new Error('Low-confidence classification-like fields must not create a dense guessed line network')

if (!upload.includes("mode?: 'data' | 'template'")) throw new Error('DualExcelUploadPanel template mode missing')
for (const label of ['客户物料模板', '集团码模板', '客户物料编码字段', '用于唯一识别每条客户物料', '最终返回给客户的集团码所在列', '只需保留真实表头即可']) {
  if (!upload.includes(label)) throw new Error(`Template upload copy missing: ${label}`)
}
if (upload.includes('targetFiles?:') || upload.includes('combine-targets')) throw new Error('Normal dual upload must not implement composite multi-target merging')

console.log('profile template upload contract checks passed')


const canvas = read('src/components/FieldMappingCanvas.vue')
for (const token of [
  'connect: [sourceField: string, targetField: string]',
  'removeLine: [payload: RemoveLinePayload]',
  ':draggable="column.header !== sourceIdColumn"',
  '@dragstart="startSourceDrag(column.header, $event)"',
  '@drop="dropOnTarget(column.header, $event)"',
  'class="map-line-hit"',
  '@click.stop="requestRemoveLine(line)"',
  '点击删除：{{ line.sourceField }} → {{ line.targetField }}',
]) {
  if (!canvas.includes(token)) throw new Error(`Field mapping canvas drag/delete contract missing: ${token}`)
}
for (const token of [
  '@connect="onCanvasConnect"',
  '@remove-line="onCanvasRemoveLine"',
  'function connectFieldPair(sourceField: string, targetField: string)',
  'function onCanvasRemoveLine(payload:',
  'ElMessageBox.confirm',
  '多字段组合规则',
]) {
  if (!workspace.includes(token)) throw new Error(`Workspace field mapping interaction contract missing: ${token}`)
}

const removeHandler = workspace.slice(workspace.indexOf('async function onCanvasRemoveLine'), workspace.indexOf('function removeRule'))
if (!removeHandler.includes("rule.source.fields.length !== 1 || rule.target.fields.length !== 1")) throw new Error('Composite rule line clicks must detect multi-field rules')
if (!removeHandler.includes('多字段组合规则') || !removeHandler.includes('return')) throw new Error('Composite rule line clicks must stop before deletion and instruct the user')
if (!removeHandler.includes('ElMessageBox.confirm') || !removeHandler.includes('removeRule(payload.ruleId)')) throw new Error('One-to-one line deletion must require confirmation before removing the whole rule')
if (!canvas.includes('watch(() => props.rules, scheduleLineUpdate, { deep: true })') || !canvas.includes('for (const rule of props.rules)')) {
  throw new Error('Reloaded rules must remain the source of truth for restoring field lines')
}
