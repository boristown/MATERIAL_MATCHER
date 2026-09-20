import fs from 'node:fs'
import path from 'node:path'
import process from 'node:process'

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

if (!upload.includes("mode?: 'data' | 'template'")) throw new Error('DualExcelUploadPanel template mode missing')
for (const label of ['客户物料模板', '集团码模板', '客户物料编码字段', '用于唯一识别每条客户物料', '最终返回给客户的集团码所在列', '只需保留真实表头即可']) {
  if (!upload.includes(label)) throw new Error(`Template upload copy missing: ${label}`)
}
if (upload.includes('targetFiles?:') || upload.includes('combine-targets')) throw new Error('Normal dual upload must not implement composite multi-target merging')

console.log('profile template upload contract checks passed')
