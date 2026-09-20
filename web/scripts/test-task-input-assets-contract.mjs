import { readFileSync } from 'node:fs'
import { resolve } from 'node:path'

const results = readFileSync(resolve('src/views/ResultsView.vue'), 'utf8')
const workspace = readFileSync(resolve('src/views/TaskWorkspaceBase.vue'), 'utf8')

const requiredResults = [
  '/input-assets',
  '本次使用的原始文件',
  '待匹配源数据',
  '集团码标准数据',
  '下载原始文件',
  '本次匹配结果',
  '输出资料',
  'latestInputAssets.targets',
  'profile_name',
  'compositeTargetLabel',
]
for (const token of requiredResults) {
  if (!results.includes(token)) throw new Error(`ResultsView missing task-input traceability token: ${token}`)
}

const requiredWorkspace = [
  '/input-assets',
  '任务资料',
  '任务开始时间',
  '本次使用的原始文件',
  '下载原始文件',
  '输出资料',
  'taskInputAssets.targets',
  'taskInputTargetLabel',
]
for (const token of requiredWorkspace) {
  if (!workspace.includes(token)) throw new Error(`TaskWorkspaceBase missing task-input traceability token: ${token}`)
}

for (const forbidden of ['stored_path', 'absolute filesystem path']) {
  if (results.includes(forbidden)) throw new Error(`ResultsView must not expose internal storage metadata: ${forbidden}`)
  if (workspace.includes(forbidden)) throw new Error(`TaskWorkspaceBase must not expose internal storage metadata: ${forbidden}`)
}

console.log('task input asset STEP4 contract ok')
