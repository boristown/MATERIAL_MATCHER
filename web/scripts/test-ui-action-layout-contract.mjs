import fs from 'node:fs'
import path from 'node:path'
import process from 'node:process'

const root = process.cwd()
const read = relative => fs.readFileSync(path.join(root, relative), 'utf8')

const styles = read('src/styles.css')
const review = read('src/styles/pages/review.css')
const results = read('src/styles/pages/results.css')
const system = read('src/styles/pages/system.css')
const canvas = read('src/components/FieldMappingCanvas.vue')
const workspace = read('src/views/TaskWorkspace.vue')

function expect(condition, message) {
  if (!condition) throw new Error(message)
}

expect(/\.toolbar\s*\{[^}]*align-items:\s*flex-start[^}]*gap:\s*16px/.test(styles), 'shared toolbar must use the top-aligned header contract')
expect(/\.section-head\s*\{[^}]*gap:\s*16px/.test(styles), 'section headers need a stable sibling gutter')
expect(/\.actions\s*\{[^}]*justify-content:\s*flex-start[^}]*gap:\s*10px/.test(styles), 'generic actions must stay near their content instead of defaulting to the far edge')
expect(styles.includes('.actions .el-button, .toolbar-actions .el-button, .quick .el-button { margin-left: 0; }'), 'primary action groups must reset Element Plus button margin')
expect(styles.includes('.actions .el-button + .el-button, .toolbar-actions .el-button + .el-button, .quick .el-button + .el-button { margin-left: 0; }'), 'button sibling margin reset must remain explicit')
expect(/\.toolbar-actions\s*\{[^}]*flex-wrap:\s*wrap[^}]*gap:\s*10px/.test(styles), 'toolbar actions must wrap using gap only')
expect(/\.workspace-toolbar\s*\{[^}]*justify-content:\s*flex-start[^}]*gap:\s*24px/.test(styles), 'workspace header must not stretch title and controls to opposite edges')
expect(/@media \(max-width: 760px\)[\s\S]*?\.toolbar-actions\s*\{[^}]*justify-content:\s*flex-start[^}]*width:\s*100%/.test(styles), 'mobile toolbar actions must start flush without extra left offset')

for (const selector of [
  '.review-page .review-toolbar-actions .el-button',
  '.review-page .review-empty-actions .el-button',
  '.review-page .review-threshold-actions .el-button',
  '.review-page .review-field-actions .el-button',
  '.review-page .review-record-actions > div:last-child .el-button',
]) {
  expect(review.includes(selector), `review action margin reset missing: ${selector}`)
}
expect(/\.review-page \.review-empty-actions\s*\{[^}]*gap:\s*10px/.test(review), 'review empty actions must use flex gap instead of sibling margin')
expect(!review.includes('.review-empty-actions .el-button + .el-button { margin-left: 10px; }'), 'review must not reintroduce gap + sibling margin')
expect(/@media \(max-width: 820px\)[\s\S]*?\.review-page \.review-threshold-actions\s*\{[^}]*justify-content:\s*flex-start/.test(review), 'mobile review actions must not be pushed to the right edge')

expect(/\.mapping-view-tools\s*\{[\s\S]*?padding:\s*0 6px;/.test(canvas), 'mapping tools need the same horizontal gutter as the canvas')
expect(workspace.includes('.threshold-row :deep(.el-button), .section-title-row :deep(.el-button) { margin-left: 0; }'), 'TaskWorkspace flex action groups must reset Element Plus margin')
expect(/\.results-toolbar\s*\{[^}]*align-items:\s*flex-start/.test(results), 'STEP4 header must use the shared top baseline')
expect(/\.system-toolbar\s*\{[^}]*align-items:\s*flex-start/.test(system), 'System header must use the shared top baseline')

console.log('UI action/header layout contract checks passed')
