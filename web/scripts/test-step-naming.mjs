import fs from 'node:fs'
import path from 'node:path'
import process from 'node:process'

const root = process.cwd()
const read = file => fs.readFileSync(path.join(root, file), 'utf8')

const app = read('src/App.vue')
const profiles = read('src/views/ProfilesView.vue')
const tasks = read('src/views/TasksView.vue')
const review = read('src/views/ReviewView.vue')
const results = read('src/views/ResultsView.vue')
const workspace = read('src/views/TaskWorkspaceBase.vue')

const STEP_TITLES = ['第一步 · 数据上传', '第二步 · 进度监控', '第三步 · 人工调整', '第四步 · 输出结果']

/* 1) left navigation keeps the four boss-approved business stage names, unchanged order */
for (const title of STEP_TITLES) {
  if (!app.includes(title)) throw new Error(`Left navigation missing stage title: ${title}`)
}
if (app.includes('数据准备') || app.includes('结果中心')) throw new Error('Left navigation stage names must not be renamed')

/* 2) every step page carries its exact primary business heading */
if (!profiles.includes('<h2>第一步 · 数据上传</h2>')) throw new Error('/profiles must show “第一步 · 数据上传” as the primary heading')
if (!tasks.includes('<h2>第二步 · 进度监控</h2>')) throw new Error('/tasks must show “第二步 · 进度监控” as the primary heading')
if (!review.includes('<h2>第三步 · 人工调整</h2>')) throw new Error('/review must keep “第三步 · 人工调整”')
if (!results.includes('<h2>第四步 · 输出结果</h2>')) throw new Error('/results must keep “第四步 · 输出结果”')
if (!workspace.includes('第一步 · 数据上传')) throw new Error('STEP1 workspace must show the first-step stage title')

/* 3) 方案配置 stays a sub-feature of step one, never a rival stage name */
if (!profiles.includes('匹配方案配置')) throw new Error('/profiles must show “匹配方案配置” as the sub-feature title')
if (profiles.includes('<h2>匹配方案</h2>') || profiles.includes('<h2>匹配方案配置</h2>')) throw new Error('“匹配方案配置” must not replace the first-step stage heading')
if (!profiles.includes('方案发布后')) throw new Error('/profiles should explain scheme publishing in business language')

/* 4) no English STEP n in ordinary business UI */
for (const [name, source] of Object.entries({ 'ProfilesView': profiles, 'TasksView': tasks, 'ReviewView': review, 'ResultsView': results })) {
  const match = source.match(/STEP\s*[1-4]/)
  if (match) throw new Error(`${name} must not show English step labels: ${match[0]}`)
}
if (tasks.includes('STEP 2 · 匹配计算')) throw new Error('“STEP 2 · 匹配计算” must be replaced by “第二步 · 进度监控”')

/* 5) buttons speak business language */
if (!profiles.includes('选择此方案并上传数据')) throw new Error('Scheme card must offer “选择此方案并上传数据”')
if (profiles.includes('用此方案建任务') || profiles.includes('建任务')) throw new Error('Ordinary users must not see “建任务”')
if (!tasks.includes('返回第一步 · 数据上传')) throw new Error('STEP2 empty state must offer “返回第一步 · 数据上传”')
if (tasks.includes('前往 STEP 1') || tasks.includes('配置并启动')) throw new Error('STEP2 must not route via “前往 STEP 1 配置并启动”')
if (!workspace.includes('开始匹配 →')) throw new Error('STEP1 workspace start button must read “开始匹配”')
if (workspace.includes('保存并开始任务') || workspace.includes('新建匹配任务') || workspace.includes('用方案创建匹配任务')) throw new Error('Workspace headings/buttons must not expose task-building language')

/* 6) choosing a scheme still enters the dual Excel upload flow */
if (!profiles.includes("path: '/tasks/new', query: { profile: row.profile_id }")) throw new Error('“选择此方案并上传数据” must open the step-1 upload workspace with the chosen scheme')
if (!workspace.includes('DualExcelUploadPanel')) throw new Error('STEP1 workspace must keep the dual Excel upload panel')
if (!workspace.includes('已应用匹配方案')) throw new Error('Scheme-selected upload mode must still summarise the applied scheme')

/* 7) STEP2-4 keep consuming the business scheme_name, with a neutral fallback only */
for (const [name, source] of Object.entries({ 'TasksView': tasks, 'ReviewView': review, 'ResultsView': results })) {
  if (!source.includes('scheme_name')) throw new Error(`${name} must consume the backend scheme_name`)
}
if (!tasks.includes("'未命名方案'") || !review.includes("'未命名方案'") || !results.includes("'未命名方案'")) throw new Error('Legacy runs without a scheme source fall back to 未命名方案 only')
if (/\{\{[^}]*task\.name[^}]*\}\}/.test(workspace)) throw new Error('TaskWorkspaceBase header must prefer the business scheme name over task.name')

console.log('four-step business naming contract checks passed')
