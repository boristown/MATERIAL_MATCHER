import fs from 'node:fs'
import path from 'node:path'
import process from 'node:process'

const root = process.cwd()
const view = fs.readFileSync(path.join(root, 'src/views/ReviewView.vue'), 'utf8')
const api = fs.readFileSync(path.join(root, 'src/services/reviewWorkbenchApi.ts'), 'utf8')
const css = fs.readFileSync(path.join(root, 'src/styles/pages/review.css'), 'utf8')

const requiredView = [
  "const PAGE_SIZE_OPTIONS = [50, 100, 200]",
  "{ key: 'all', label: '全部', backend: 'ALL' }",
  "backend: 'MATCHED'",
  "backend: 'REVIEW'",
  "backend: 'CONFIRMED'",
  "backend: 'UNMATCHED'",
  '选择当前筛选出的全部',
  '确认第一候选',
  '标记均不匹配',
  '取消人工匹配',
  '恢复原结果',
  '下载人工匹配 Excel',
  '上传人工匹配结果',
  '自动匹配阈值',
  '人工处理下限',
  '第一候选分数分布',
  '第一 / 第二候选分差分布',
  'Top 1～Top 5',
  '一致',
  '部分一致',
  '不一致',
  '无数据',
]

const requiredApi = [
  'include_candidates: includeCandidates',
  "mode: 'explicit'",
  "mode: 'filter'",
  "'confirm_top1'",
  "'mark_unmatched'",
  "'cancel_manual_match'",
  "'restore_original'",
  'success_threshold: successThreshold',
  'review_threshold: reviewThreshold',
  'manual-review.xlsx',
  'manual-review/import',
  '/calibration',
  '/workbench/batch',
]

const requiredCss = [
  'position: sticky',
  '.review-bulk-bar',
  '.review-data-table thead th',
  '.is-exact',
  '.is-partial',
  '.is-different',
  '.is-empty',
]

for (const token of requiredView) {
  if (!view.includes(token)) throw new Error(`ReviewView contract missing: ${token}`)
}
for (const token of requiredApi) {
  if (!api.includes(token)) throw new Error(`Review API contract missing: ${token}`)
}
for (const token of requiredCss) {
  if (!css.includes(token)) throw new Error(`Review CSS contract missing: ${token}`)
}

if (view.includes('hydrateCandidates')) throw new Error('ReviewView must not eager-load candidates for every row')

for (const banned of ['关键字段', '为什么系统犹豫', '风险', '扣分项']) {
  if (view.includes(banned)) throw new Error(`Banned STEP3 wording found: ${banned}`)
}

console.log('STEP3 large-scale review contract checks passed')
