import fs from 'node:fs'
import path from 'node:path'
import process from 'node:process'

const root = process.cwd()
const read = file => fs.readFileSync(path.join(root, file), 'utf8')

const workspace = read('src/views/TaskWorkspaceBase.vue')
const upload = read('src/components/DualExcelUploadPanel.vue')

/* 新建/编辑方案必须支持通过两份 Excel 模板识别字段，不能退化成逐字段手工录入。 */
if (!workspace.includes("字段很多时无需逐个录入")) throw new Error('Profile editor must explain template-driven field recognition')
if (!workspace.includes(`:mode="isProfileEditorMode ? 'template' : 'data'"`)) throw new Error('Profile editor must put DualExcelUploadPanel into template mode')
if (workspace.includes('v-if="!isProfileEditorMode" class="panel step1-data-panel"')) throw new Error('Template upload panel must not be hidden in profile editor mode')

/* 上传模板识别出的全量字段必须进入方案字段选择器。 */
if (!workspace.includes('...srcHeaders.value')) throw new Error('Recognized source template headers must feed profile source field options')
if (!workspace.includes('...tgtHeaders.value')) throw new Error('Recognized target template headers must feed profile target field options')
if (!workspace.includes('baseAdvanced.template_schema')) throw new Error('Recognized template schema must be persisted in the profile document')
if (!workspace.includes('rememberedSourceFields') || !workspace.includes('rememberedTargetFields')) throw new Error('Saved template schema must be restored when the profile is edited again')

/* 两侧模板准备好后可自动生成映射，新方案无需逐条手工添加。 */
if (!workspace.includes('@click="autoMap">自动推荐映射</el-button>')) throw new Error('Profile editor must expose automatic mapping after template recognition')
if (!workspace.includes('if (source.value && target.value && !rules.value.length) autoMap()')) throw new Error('Fresh profile should auto-map once both template schemas are parsed')

/* 上传组件在模板模式使用业务可理解文案，同时保留数据上传模式。 */
if (!upload.includes("mode?: 'data' | 'template'")) throw new Error('DualExcelUploadPanel must support template mode')
for (const label of ['客户物料模板', '集团码模板', '只需保留真实表头即可']) {
  if (!upload.includes(label)) throw new Error(`Template upload copy missing: ${label}`)
}

console.log('profile template upload contract checks passed')
