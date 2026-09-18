import fs from 'node:fs'
import path from 'node:path'
import process from 'node:process'

const root = process.cwd()
const view = fs.readFileSync(path.join(root, 'src/views/ReviewView.vue'), 'utf8')
const css = [
  fs.readFileSync(path.join(root, 'src/styles/pages/review.css'), 'utf8'),
  fs.readFileSync(path.join(root, 'src/styles/pages/review-large-scale.css'), 'utf8'),
].join('\n')

const requiredView = [
  '历史计算记录',
  '当前查看',
  '>方案名称</th>',
  '>任务开始时间</th>',
  '>自动计算耗时</th>',
  '>数据量</th>',
  '>自动匹配</th>',
  '>待人工</th>',
  '>未匹配</th>',
  '>状态</th>',
  '>操作</th>',
  '第 {{ row.sequence }} 次',
  'historyStatusLabel',
  'formatListTime',
  'formatDate',
  'api.get(\'/tasks/review-history\')',
  'is-active',
  '当前查看',
  'selectTask(row.task_id)',
  '查看全部计算记录',
  'HISTORY_PREVIEW_LIMIT',
  'route.query.task',
  'router.replace({ path: \'/review\', query: { task',
  'expandedRows.value = {}',
  'clearSelection()',
  'candidateMap.value = {}',
  '待人工处理',
  '已全部处理',
  '生成结果',
  '无法确认序号',
]
for (const token of requiredView) {
  if (!view.includes(token)) throw new Error(`STEP3 history contract missing: ${token}`)
}

const requiredCss = [
  '.review-history-table',
  '.review-current-card',
  '.review-history-active-tag',
  'inset 3px 0 0 #2563eb',
  'overflow-x: auto',
  'text-overflow: ellipsis',
]
for (const token of requiredCss) {
  if (!css.includes(token)) throw new Error(`STEP3 history CSS contract missing: ${token}`)
}

if (view.includes('review-task-switcher')) throw new Error('STEP3 must not keep the history task dropdown')
if (view.includes('切换方案')) throw new Error('STEP3 history switching must happen in the history list, not the dropdown')
if (view.includes('loadReviewSummary')) throw new Error('STEP3 must not fetch workbench summaries per history task (N+1)')
if (view.includes('task.name') || view.includes('scope.row.name') || view.includes('row.name')) throw new Error('STEP3 history must show scheme_name, never the internal task name')
if (view.includes('条待人工`')) throw new Error('STEP3 history rows must not be identified by the pending-review count alone')
for (const enumText of ['>RUNNING<', '>COMPLETED<', '>REVIEW<', '>MATCHED<', 'INTERNAL_ERROR']) {
  if (view.includes(enumText)) throw new Error(`STEP3 history status must use business wording, found raw enum: ${enumText}`)
}

console.log('STEP3 history list contract checks passed')
