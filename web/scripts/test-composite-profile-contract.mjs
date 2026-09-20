import fs from 'node:fs'

const workspace = fs.readFileSync(new URL('../src/views/TaskWorkspaceBase.vue', import.meta.url), 'utf8')
const helper = fs.readFileSync(new URL('../src/compositeProfile.ts', import.meta.url), 'utf8')
const editor = fs.readFileSync(new URL('../src/components/CompositeProfilePanel.vue', import.meta.url), 'utf8')
const uploader = fs.readFileSync(new URL('../src/components/CompositeTaskUploadPanel.vue', import.meta.url), 'utf8')

function expect(value, message) {
  if (!value) throw new Error(message)
}

expect(workspace.includes("profileKind.value === 'composite'"), 'workspace must distinguish composite profile type')
expect(workspace.includes('<CompositeProfilePanel'), 'composite profile editor panel must be wired')
expect(workspace.includes('<CompositeTaskUploadPanel'), 'composite multi-target task upload must be wired')
expect(workspace.includes("rules: isCompositeProfile.value ? []"), 'composite profile must not persist duplicated field rules')
expect(workspace.includes('composite_run'), 'runtime child-to-catalog mapping must be persisted')
expect(editor.includes('冻结当前发布版本'), 'child selection must explain version freeze')
expect(editor.includes('不会合并文件结构'), 'composite UX must not describe physical file merge')
expect(uploader.includes('字段结构无需一致'), 'multiple target files must allow heterogeneous headers')
expect(uploader.includes('targetCompatibility'), 'target file recommendation must be based on header/schema coverage')
expect(uploader.includes('手工覆盖'), 'automatic target recommendation must allow manual override')
expect(uploader.includes('本次任务只有一个源文件'), 'composite task must keep one source file')
expect(helper.includes('recommendCompositeAssignments'), 'adapter must expose automatic child-target assignment')
expect(helper.includes('resolveCompositeRun'), 'adapter must resolve each child assignment to its own catalog version')
expect(!workspace.includes('fixed_value'), 'fixed-value UI stays owned by the dedicated dependency PR to avoid duplicate implementation')
expect(!workspace.includes('如 Z001'), 'example values must not be hard-coded into the product UI')
expect(!workspace.includes('物料类型只匹配 Z001'), 'example field/value names must remain generic')

console.log('A007 composite frontend contract: OK')
