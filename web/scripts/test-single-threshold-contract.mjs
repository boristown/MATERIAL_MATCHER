import fs from 'node:fs'
import path from 'node:path'
import process from 'node:process'

const root = process.cwd()
const read = relative => fs.readFileSync(path.join(root, relative), 'utf8')

const workspace = read('src/views/TaskWorkspaceBase.vue')
const review = read('src/views/ReviewView.vue')
const results = read('src/views/ResultsView.vue')
const system = read('src/views/SystemView.vue')
const reviewApi = read('src/services/reviewWorkbenchApi.ts')

for (const token of ['reviewThreshold', 'thrReview', '人工确认下限', '人工匹配下限', '人工处理下限', '复核 ≥']) {
  if (workspace.includes(token)) throw new Error(`Workspace still exposes removed manual threshold: ${token}`)
}

for (const [surface, source] of [
  ['STEP3', review],
  ['STEP4', results],
  ['设置页', system],
]) {
  for (const token of ['人工确认下限', '人工匹配下限', '人工处理下限']) {
    if (source.includes(token)) throw new Error(`${surface} still exposes removed manual threshold: ${token}`)
  }
}

if (!workspace.includes('自动匹配阈值')) throw new Error('Scheme/task configuration must retain automatic-match threshold')
if (!review.includes('自动匹配阈值')) throw new Error('STEP3 must retain automatic-match threshold')
if (reviewApi.includes('review_threshold') || reviewApi.includes('single_threshold')) {
  throw new Error('STEP3 API adapter must submit automatic-match threshold only')
}

console.log('Automatic-threshold-only product contract checks passed')
