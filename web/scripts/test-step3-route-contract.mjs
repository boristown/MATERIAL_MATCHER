import fs from 'node:fs'
import path from 'node:path'
import process from 'node:process'

const root = process.cwd()
const read = file => fs.readFileSync(path.join(root, file), 'utf8')

const workspace = read('src/views/TaskWorkspaceBase.vue')
const review = read('src/views/ReviewView.vue')
const router = read('src/router.ts')

const enterStart = workspace.indexOf('async function enterStage2Or3')
const enterEnd = workspace.indexOf('/* ---------- 人工调整 ---------- */', enterStart)
if (enterStart < 0 || enterEnd < 0) throw new Error('TaskWorkspaceBase must keep enterStage2Or3')
const enter = workspace.slice(enterStart, enterEnd)

if (!workspace.includes("router.push({ path: '/review', query: { task: taskId } })")) {
  throw new Error('STEP2/legacy task flow must route pending review work to /review?task=<task_id>')
}
if (!enter.includes('await loadReviewSummary()')) throw new Error('STEP3 routing must decide from the server review summary')
if (!enter.includes('(reviewSummary.value.pending_review ?? 0) > 0')) throw new Error('STEP3 routing must check pending_review > 0')
if (!enter.includes('await openReviewForTask()')) throw new Error('Pending review tasks must enter ReviewView')
if (enter.includes('loadWorkbench()')) throw new Error('enterStage2Or3 must not hydrate the legacy TaskWorkspace STEP3')
if (workspace.includes('stage.value = 2')) throw new Error('TaskWorkspaceBase must not programmatically enter the legacy STEP3')
if (workspace.includes('@click="stage=2"')) throw new Error('TaskWorkspaceBase must not expose a button that re-enters the legacy STEP3')
if (!workspace.includes('@click="openReviewForTask">← 人工调整</el-button>')) {
  throw new Error('Legacy result back-navigation must also enter ReviewView')
}

if (!workspace.includes("else if (task.value.status === 'COMPLETED') { stopPolling(); await enterStage2Or3() }")) {
  throw new Error('Realtime COMPLETED flow must pass through unified STEP3 routing')
}
if (!workspace.includes("if (task.value.status === 'COMPLETED') { await enterStage2Or3() }")) {
  throw new Error('Historical completed-task restore must pass through unified STEP3 routing')
}

if (!router.includes("{ path: '/review', component: ReviewView, meta: { navStep: 3 } }")) {
  throw new Error('/review must keep navStep 3 so the left navigation highlights 第三步 · 人工调整')
}
if (!review.includes("const requestedTaskId = typeof route.query.task === 'string' ? route.query.task : ''")) {
  throw new Error('ReviewView must restore the task from /review?task=<task_id>')
}
if (!review.includes('await loadWorkbenchContext(nextTask.task_id)')) {
  throw new Error('ReviewView must hydrate the requested task after refresh/direct URL access')
}
if (!review.includes('Top 1～Top 5') || !review.includes('server-side')) {
  throw new Error('Unified STEP3 must keep the existing ReviewView TopN and server-side workbench')
}

console.log('STEP3 route unification contract checks passed')
