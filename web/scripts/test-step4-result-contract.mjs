import fs from 'node:fs'
import path from 'node:path'
import process from 'node:process'

const root = process.cwd()
const read = relative => fs.readFileSync(path.join(root, relative), 'utf8')
const results = read('src/views/ResultsView.vue')
const css = read('src/styles/pages/results.css')
const router = read('src/router.ts')
const rateSource = read('src/resultRates.ts')

for (const token of [
  '任务资料',
  '本次使用的原始文件',
  '本次匹配结果',
  '自动匹配率',
  '人工匹配率',
  '未匹配率',
  '待处理率',
  '匹配结果构成',
  '输出资料',
  '最终 Excel 已生成',
  '下载结果 Excel',
  '任务开始时间',
  '自动计算耗时',
  '/input-assets',
  '/exports',
]) {
  if (!results.includes(token)) throw new Error(`STEP4 business result contract missing: ${token}`)
}

for (const forbidden of ['准确率验收', 'AI 准确率', '成功准确率', '人工确认']) {
  if (results.includes(forbidden)) throw new Error(`STEP4 must not expose mixed/incorrect business wording: ${forbidden}`)
}

if (!results.includes('formatBusinessRate(latestSummary.automatic_matched, latestTotalRows)')) {
  throw new Error('automatic match rate must use the shared formatter')
}
if (!results.includes('formatBusinessRate(latestSummary.confirmed, latestTotalRows)')) {
  throw new Error('manual match rate must use the shared formatter')
}
if (!results.includes('formatBusinessRate(latestSummary.unmatched, latestTotalRows)')) {
  throw new Error('unmatched rate must use the shared formatter')
}
if (!results.includes('formatBusinessRate(latestSummary.pending_review, latestTotalRows)')) {
  throw new Error('pending rate must use the shared formatter')
}

const executableRateSource = rateSource
  .replace(/export\s+/g, '')
  .replace(/:\s*number\s*\|\s*null/g, '')
  .replace(/:\s*number/g, '')
  .replace(/:\s*string/g, '')
const rateApi = Function(`${executableRateSource}; return { businessRatePercent, formatBusinessRate, businessRateWidth }`)()

const cases = [
  [930, 1000, '93.0%'],
  [20, 1000, '2.0%'],
  [50, 1000, '5.0%'],
  [0, 1000, '0%'],
]
for (const [count, total, expected] of cases) {
  const actual = rateApi.formatBusinessRate(count, total)
  if (actual !== expected) throw new Error(`rate formatter mismatch: ${count}/${total} => ${actual}, expected ${expected}`)
}
if (rateApi.formatBusinessRate(1, 0) !== '—') throw new Error('total=0 must render —')
if (rateApi.formatBusinessRate(0, 0).includes('NaN') || rateApi.formatBusinessRate(0, 0).includes('Infinity')) {
  throw new Error('total=0 must never render NaN/Infinity')
}
if (rateApi.formatBusinessRate(2, 1000) !== '0.2%') throw new Error('small rates must remain readable in legend')
if (rateApi.businessRateWidth(0, 1000) !== '0.0000%') throw new Error('0% composition segment must collapse safely')
if (rateApi.businessRateWidth(2, 1000) !== '0.2000%') throw new Error('composition width must match the business rate')

if (!css.includes('.result-composition-bar') || !css.includes('overflow: hidden')) {
  throw new Error('composition bar needs a bounded, overflow-safe container')
}
if (!/\.result-composition-legend\s*{[^}]*flex-wrap:\s*wrap/.test(css)) {
  throw new Error('composition legend must wrap on narrow screens')
}
if (!/@media \(max-width: 640px\)[\s\S]*?\.result-composition-legend > span\s*{[^}]*flex:\s*1 1 100%/.test(css)) {
  throw new Error('STEP4 composition legend needs phone layout protection')
}

if (!router.includes("path: '/tasks/:taskId/evaluation'") || !router.includes('TaskEvaluationView')) {
  throw new Error('ground-truth evaluation route must remain available outside the ordinary STEP4 result page')
}

console.log('STEP4 business result metrics + evaluation separation contract ok')
