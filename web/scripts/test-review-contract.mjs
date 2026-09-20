import fs from 'node:fs'
import path from 'node:path'
import process from 'node:process'

const root = process.cwd()
const view = fs.readFileSync(path.join(root, 'src/views/ReviewView.vue'), 'utf8')
const api = fs.readFileSync(path.join(root, 'src/services/reviewWorkbenchApi.ts'), 'utf8')
const css = [
  fs.readFileSync(path.join(root, 'src/styles/pages/review.css'), 'utf8'),
  fs.readFileSync(path.join(root, 'src/styles/pages/review-large-scale.css'), 'utf8'),
].join('\n')

const requiredView = [
  'const PAGE_SIZE_OPTIONS = [50, 100, 200]',
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
  '清除选择',
  '下载人工匹配 Excel',
  '上传人工匹配结果',
  '自动匹配阈值',
  '预计自动匹配',
  '预计需要人工处理',
  'Top1 分数分布',
  'Top1 / Top2 分差分布',
  'Top 1～Top 5',
  'candidateDisplayFields(candidate)',
  'result.length >= 2',
  'setComparisonPanelRef',
  'revealComparisonPanel',
  'await revealComparisonPanel(item.source_row_id)',
  'const nextSelected: Record<string, string> = {}',
  'if (selected === NONE_SELECTION) return null',
  'critical_conflict: Boolean(candidate?.critical_conflict)',
  '关键字段不一致',
  '值映射未配置',
  '方案中标记为关键字段的内容与候选不一致，因此该候选不会自动通过，需要人工确认；总相似度仍保留用于候选排序。',
  "{ target_id: selected, comment: '' }",
  '一致',
  '部分一致',
  '不一致',
  '无数据',
  'server-side',
  'ensureCandidates(item)',
  'fetchCandidates(activeTaskId.value, item.source_row_id)',
]

const requiredApi = [
  'includeCandidates = 0',
  'include_candidates: includeCandidates',
  'buildWorkbenchParams(filter, page, pageSize)',
  'fetchCandidates',
  "mode: 'explicit'",
  "mode: 'filter'",
  "'confirm_top1'",
  "'mark_unmatched'",
  "'cancel_manual_match'",
  "'restore_original'",
  'CONFIRM_TOP1',
  'MARK_UNMATCHED',
  'CANCEL_MATCH',
  'RESTORE_ALGORITHM',
  'expected_version',
  'success_threshold: successThreshold',
  'reDecideSingleThreshold',
  'manual-review.xlsx',
  'manual-review/import',
  '/calibration',
  '/workbench/bulk',
]

const requiredCss = [
  'position: sticky',
  '.review-bulk-bar',
  '.review-data-table thead th',
  '.review-candidate-meta',
  '.review-candidate-alert.is-critical',
  '.review-candidate-alert.is-mapping',
  '.review-expanded-card { position: sticky',
  'max-height: 58vh',
  '.is-exact',
  '.is-partial',
  '.is-different',
  '.is-empty',
  '.review-action-col',
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
if (api.includes('buildWorkbenchParams(filter, page, pageSize, 5)')) throw new Error('Workbench list must not preload Top5 candidates; use fetchCandidates lazily')
if (!/function onFilterChanged\(\): void \{[\s\S]*?page\.value = 1[\s\S]*?loadItems\(false\)/.test(view)) throw new Error('Status/search filter changes must reset server-side paging to page 1')
if (!/function onPageSizeChange\(next: number\): void \{[\s\S]*?page\.value = 1[\s\S]*?loadItems\(false\)/.test(view)) throw new Error('Page-size changes must reset server-side paging to page 1')
if (view.includes('PAGE_SIZE_OPTIONS = [10') || view.includes('PAGE_SIZE_OPTIONS = [20')) throw new Error('STEP3 page size must be 50 / 100 / 200')
if (view.includes('previewReDecision')) throw new Error('STEP3 UI must use the single-threshold adapter, not expose the legacy dual-threshold call')
if (api.includes('review_threshold') || api.includes('single_threshold')) throw new Error('STEP3 API adapter must send automatic threshold only')
if (view.includes("candidate.target_payload['") || view.includes('candidate.target_payload["')) throw new Error('Candidate cards must choose display fields generically instead of hard-coding one material schema')
if (view.includes('Z001') || view.includes('Z006')) throw new Error('STEP3 candidate display must not hard-code material categories')
if (!view.includes(":class=\"{ 'is-selected': selectedByRow[item.source_row_id] === candidate.target_group_code }\"")) throw new Error('Top1~Top5 cards must reflect the row selection immediately')
if (!view.includes("@click=\"setSelectedValue(item, candidate.target_group_code)\"")) throw new Error('Top1~Top5 cards must be selectable inline')
if (!view.includes("if (item.current_status === 'UNMATCHED') return NONE_SELECTION")) throw new Error('UNMATCHED rows must restore the no-match selection after refresh')
if (!view.includes("if (item.final_group_code) return String(item.final_group_code)")) throw new Error('Confirmed rows must restore the persisted manual target after refresh')
if (!view.includes("if (item.current_status === 'MATCHED' && item.top1_group_code) return String(item.top1_group_code)")) throw new Error('Automatic matches must restore Top1 after refresh')

for (const banned of ['人工处理下限', '人工确认下限', '人工匹配下限', '双阈值', '无冲突', '为什么系统犹豫', '风险分类', '扣分项', '原始数据摘要', '<el-drawer', '候选对比']) {
  if (view.includes(banned)) throw new Error(`Banned STEP3 wording found: ${banned}`)
}

console.log('STEP3 single-threshold + large-scale review contract checks passed')
