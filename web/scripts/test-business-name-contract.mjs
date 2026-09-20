import fs from 'node:fs'
import path from 'node:path'
import process from 'node:process'

const root = process.cwd()
const repo = path.join(root, '..')
const read = (...parts) => fs.readFileSync(path.join(root, ...parts), 'utf8')

const taskWorkspace = read('src/views/TaskWorkspaceBase.vue')
const tasksView = read('src/views/TasksView.vue')
const reviewView = read('src/views/ReviewView.vue')
const resultsView = read('src/views/ResultsView.vue')

const businessFiles = [
  ['TaskWorkspaceBase.vue', taskWorkspace],
  ['TasksView.vue', tasksView],
  ['ReviewView.vue', reviewView],
  ['ResultsView.vue', resultsView],
]
for (const [file, text] of businessFiles) {
  if (text.includes('任务名称')) throw new Error(`${file} must not surface the 任务名称 concept`)
}
if (/<label>任务名称<\/label>/.test(taskWorkspace) || taskWorkspace.includes('class="task-name-row"')) {
  throw new Error('STEP1 must not render a task-name input row')
}
for (const token of ['scheme_name', '未命名方案']) {
  if (!reviewView.includes(token) || !resultsView.includes(token)) throw new Error(`STEP3/STEP4 must resolve scheme_name with ${token} fallback`)
}
if (!tasksView.includes('run_number') || !tasksView.includes('次计算')) {
  throw new Error('STEP2 history must show 方案名称 + 第 N 次计算')
}
for (const text of [reviewView, resultsView]) {
  if (/task\.name|row\.name|String\(task\.name/.test(text)) throw new Error('business views must not consume task.name')
}
if (!taskWorkspace.includes("api.post('/task-drafts', {})")) throw new Error('draft creation must not send a business name')

const readRepo = (...parts) => fs.readFileSync(path.join(repo, ...parts), 'utf8')
const resultExport = readRepo('src/material_matcher/services/result_export_service.py')
const exportProfile = readRepo('src/material_matcher/services/export_profile.py')
const manualReview = readRepo('src/material_matcher/services/manual_review_service.py')
for (const [file, text] of [['result_export_service.py', resultExport], ['export_profile.py', exportProfile], ['manual_review_service.py', manualReview]]) {
  if (text.includes('任务名称')) throw new Error(`${file} must not surface the 任务名称 concept`)
}
if (!exportProfile.includes('"scheme_name": "方案名称"')) throw new Error('default export profile summary row must stay 方案名称')
if (!exportProfile.includes('"filename_prefix": "物料集团码匹配结果"')) throw new Error('default result export filename must stay business-styled')
if (!resultExport.includes('safe_business_filename')) throw new Error('result export filename must be sanitised')
if (!manualReview.includes('resolve_task_scheme_name')) throw new Error('manual review guide must resolve the frozen scheme name')

console.log('business-name (task name removal) contract checks passed')
