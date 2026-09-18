import fs from 'node:fs'
import path from 'node:path'
import process from 'node:process'

const root = process.cwd()
const read = relative => fs.readFileSync(path.join(root, relative), 'utf8')
const step2 = read('src/views/TasksView.vue')
const detail = read('src/views/TaskWorkspaceBase.vue')
const step3 = read('src/views/ReviewView.vue')
const step4 = read('src/views/ResultsView.vue')
const formatter = read('src/taskTime.ts')

for (const [name, source] of [
  ['STEP2', step2],
  ['task detail', detail],
  ['STEP3', step3],
  ['STEP4', step4],
]) {
  if (!source.includes('任务开始时间')) throw new Error(`${name} must show 任务开始时间`)
  if (!source.includes('自动计算耗时') && !source.includes('自动计算已用时')) {
    throw new Error(`${name} must show automatic compute duration`)
  }
}

if (detail.includes('elapsedSeconds(')) {
  throw new Error('task detail must not derive compute duration from browser wall clock')
}
if (detail.includes('Date.now() -') || step3.includes('Date.now() -') || step4.includes('Date.now() -')) {
  throw new Error('business compute duration must come from the backend, not Date.now()')
}
if (!step2.includes('compute_duration_ms') || !step3.includes('compute_duration_ms') || !step4.includes('compute_duration_ms')) {
  throw new Error('STEP2/STEP3/STEP4 must consume the shared backend compute_duration_ms contract')
}
if (!formatter.includes("暂无准确记录")) throw new Error('missing historical compute timing must be explicit')
if (!formatter.includes('小时') || !formatter.includes('分') || !formatter.includes('秒')) {
  throw new Error('duration formatter must preserve hour/minute/second detail')
}

console.log('task time semantics contract checks passed')
