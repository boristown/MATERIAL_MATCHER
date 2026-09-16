<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { api } from '../api'
import '../styles/pages/results.css'

type DecisionSnapshot = {
  success_threshold?: number | null
  review_threshold?: number | null
  review_enabled?: boolean | null
}

type TaskRow = {
  id: string
  name: string
  stage: string
  progress: number
  status: string
  created_at: string
  finished_at?: string | null
  result_file_id?: string | null
  processed_rows: number
  total_rows: number
  config_snapshot?: { decision?: DecisionSnapshot | null } | null
}

type ResultSummary = {
  pending_review: number
  confirmed: number
  unmatched: number
  automatic_matched: number
  [key: string]: unknown
}

type PreviewRow = Record<string, unknown> & {
  source_id?: string | null
  source_row_id?: string | number | null
  current_status?: string | null
  top1_group_code?: string | null
  top1_score?: number | null
  final_group_code?: string | null
  updated_at?: string | null
}

type FileRecord = {
  file_id: string
  role: string
  original_name: string
  size_bytes?: number
  created_at?: string
}

type ExportInfo = {
  file_id?: string | null
  download_url: string
}

type ExportBundle = Record<string, unknown> & {
  final_result?: ExportInfo | null
}

const router = useRouter()
const tasks = ref<TaskRow[]>([])
const resultFiles = ref<Record<string, FileRecord>>({})
const latestSummary = ref<ResultSummary>({ pending_review: 0, confirmed: 0, unmatched: 0, automatic_matched: 0 })
const latestRows = ref<PreviewRow[]>([])
const latestExports = ref<ExportBundle>({})
const loading = ref(true)
const downloadingTaskId = ref('')
const downloadingExportKey = ref('')

const stageLabels: Record<string, string> = { CALCULATE: '比对计算', REVIEW: '人工处理', RESULT: '生成结果' }
const RUNNING_STATUSES = ['RUNNING', 'PREPARING', 'RECOVERING', 'PENDING']

function resultCompletedAt(task: TaskRow): string {
  const file = task.result_file_id ? resultFiles.value[task.result_file_id] : undefined
  return String(file?.created_at || task.finished_at || task.created_at || '')
}

const generatedResults = computed(() => tasks.value
  .filter(task => Boolean(task.result_file_id))
  .slice()
  .sort((a, b) => resultCompletedAt(b).localeCompare(resultCompletedAt(a))))

const latestResult = computed(() => generatedResults.value[0] ?? null)

const pendingTask = computed(() => tasks.value
  .filter(task => !task.result_file_id && task.status !== 'FAILED')
  .slice()
  .sort((a, b) => b.created_at.localeCompare(a.created_at))[0] ?? null)

const waitingState = computed(() => {
  const task = pendingTask.value
  if (!task) return null
  if (RUNNING_STATUSES.includes(task.status)) {
    return {
      title: '正在等待 STEP2 计算完成',
      description: `任务「${task.name}」仍在计算中，结果文件尚未生成，当前不可下载。`,
      action: '查看计算进度',
      path: `/tasks/${task.id}`,
      showProgress: true,
    }
  }
  if (task.status === 'COMPLETED' && task.stage === 'REVIEW') {
    return {
      title: '正在等待 STEP3 人工处理完成',
      description: `任务「${task.name}」已完成计算，但仍处于人工处理阶段，完成确认后才能生成最终结果。`,
      action: '进入人工处理',
      path: `/tasks/${task.id}`,
      showProgress: false,
    }
  }
  if (task.status === 'COMPLETED' && task.stage === 'RESULT') {
    return {
      title: '前序步骤已完成，结果文件尚未生成',
      description: `任务「${task.name}」已经可以生成最终结果，请进入任务完成结果生成。`,
      action: '进入任务生成结果',
      path: `/tasks/${task.id}`,
      showProgress: false,
    }
  }
  return {
    title: '任务尚未形成可下载结果',
    description: `任务「${task.name}」当前状态为“${statusLabel(task.status)}”，请进入任务查看详情。`,
    action: '查看任务',
    path: `/tasks/${task.id}`,
    showProgress: false,
  }
})

function statusTagType(status: string): 'success' | 'danger' | 'warning' | 'primary' | 'info' {
  if (status === 'COMPLETED') return 'success'
  if (status === 'FAILED') return 'danger'
  if (RUNNING_STATUSES.includes(status)) return 'primary'
  return 'warning'
}

function statusLabel(status: string): string {
  return ({ RUNNING: '运行中', PREPARING: '准备中', RECOVERING: '恢复中', PENDING: '排队中', COMPLETED: '已完成', FAILED: '失败' } as Record<string, string>)[status] ?? status
}

function resultStatusLabel(row: PreviewRow): string {
  return ({ MATCHED: '自动匹配', CONFIRMED: '人工确认', REVIEW: '待确认', UNMATCHED: '未匹配' } as Record<string, string>)[String(row.current_status ?? '')] ?? String(row.current_status ?? '—')
}

function resultStatusType(row: PreviewRow): 'success' | 'warning' | 'info' | 'primary' {
  if (row.current_status === 'MATCHED') return 'success'
  if (row.current_status === 'CONFIRMED') return 'primary'
  if (row.current_status === 'REVIEW') return 'warning'
  return 'info'
}

function formatTime(value?: string | null): string {
  if (!value) return '—'
  return String(value).slice(0, 19).replace('T', ' ')
}

function numberValue(value: unknown): number | null {
  if (value === null || value === undefined || value === '') return null
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

function formatScore(value: unknown): string {
  const parsed = numberValue(value)
  return parsed === null ? '—' : parsed.toFixed(1)
}

function formatCount(value: unknown): string {
  const parsed = numberValue(value)
  return parsed === null ? '0' : Math.round(parsed).toLocaleString()
}

function firstValue(record: Record<string, unknown>, keys: string[]): unknown {
  for (const key of keys) {
    const value = record[key]
    if (value !== null && value !== undefined && value !== '') return value
  }
  return null
}

function firstNumber(record: Record<string, unknown>, keys: string[]): number | null {
  return numberValue(firstValue(record, keys))
}

function sourceRowNumber(row: PreviewRow): string {
  const value = firstValue(row, ['source_excel_row', 'source_row_number', 'source_row_no', 'source_row'])
  return value === null ? '—' : String(value)
}

function targetRowNumber(row: PreviewRow): string {
  const value = firstValue(row, ['target_excel_row', 'target_row_number', 'target_row_no', 'target_row'])
  return value === null ? '—' : String(value)
}

function customerMaterialCode(row: PreviewRow): string {
  const value = firstValue(row, ['customer_material_code', 'source_material_code', 'material_code', 'source_id'])
  return value === null ? '—' : String(value)
}

function finalGroupCode(row: PreviewRow): string {
  const value = firstValue(row, ['final_group_code', 'group_code'])
  if (value !== null) return String(value)
  if (row.current_status === 'MATCHED' || row.current_status === 'CONFIRMED') {
    return row.top1_group_code ? String(row.top1_group_code) : '—'
  }
  return '—'
}

function totalRows(task: TaskRow | null): number {
  const direct = Number(task?.total_rows ?? 0)
  if (direct > 0) return direct
  const summary = latestSummary.value
  return Number(summary.automatic_matched || 0) + Number(summary.confirmed || 0) + Number(summary.unmatched || 0) + Number(summary.pending_review || 0)
}

const latestTotalRows = computed(() => totalRows(latestResult.value))

const automaticThreshold = computed(() => {
  const summaryValue = firstNumber(latestSummary.value, ['success_threshold', 'automatic_threshold', 'current_success_threshold', 'current_automatic_threshold'])
  if (summaryValue !== null) return summaryValue
  return numberValue(latestResult.value?.config_snapshot?.decision?.success_threshold)
})

const reviewThreshold = computed(() => {
  const summaryValue = firstNumber(latestSummary.value, ['review_threshold', 'manual_threshold', 'current_review_threshold', 'current_manual_threshold'])
  if (summaryValue !== null) return summaryValue
  return numberValue(latestResult.value?.config_snapshot?.decision?.review_threshold)
})

const previewRows = computed(() => {
  const rows = latestRows.value.slice()
  rows.sort((left, right) => {
    const a = numberValue(firstValue(left, ['source_excel_row', 'source_row_number', 'source_row_no', 'source_row']))
    const b = numberValue(firstValue(right, ['source_excel_row', 'source_row_number', 'source_row_no', 'source_row']))
    if (a === null || b === null) return 0
    return a - b
  })
  return rows.slice(0, 8)
})

const allUnmatched = computed(() => {
  const total = latestTotalRows.value
  if (total <= 0) return false
  return Number(latestSummary.value.unmatched || 0) === total
    && Number(latestSummary.value.automatic_matched || 0) === 0
    && Number(latestSummary.value.confirmed || 0) === 0
    && Number(latestSummary.value.pending_review || 0) === 0
})

const scoreStats = computed(() => {
  let highest = firstNumber(latestSummary.value, ['max_top1_score', 'highest_top1_score', 'max_first_score', 'highest_first_score'])
  let average = firstNumber(latestSummary.value, ['avg_top1_score', 'average_top1_score', 'avg_first_score', 'average_first_score'])
  const total = latestTotalRows.value
  if ((highest === null || average === null) && total > 0 && latestRows.value.length >= total) {
    const scores = latestRows.value.map(row => numberValue(row.top1_score)).filter((value): value is number => value !== null)
    if (scores.length) {
      if (highest === null) highest = Math.max(...scores)
      if (average === null) average = scores.reduce((sum, value) => sum + value, 0) / scores.length
    }
  }
  return { highest, average }
})

const previewNarrative = computed(() => {
  const row = previewRows.value.find(item => finalGroupCode(item) !== '—')
  if (!row) return '本次预览中尚无已形成集团码的记录，可通过下表查看每条源数据的状态和第一候选分。'
  const sourceRow = sourceRowNumber(row)
  const targetRow = targetRowNumber(row)
  const material = customerMaterialCode(row)
  const groupCode = finalGroupCode(row)
  if (sourceRow !== '—' && targetRow !== '—') {
    return `源 Excel 第 ${sourceRow} 行的物料「${material}」，匹配到了集团码表第 ${targetRow} 行，对应集团码 ${groupCode}。`
  }
  if (sourceRow !== '—') {
    return `源 Excel 第 ${sourceRow} 行的物料「${material}」，对应集团码 ${groupCode}。`
  }
  return `客户物料「${material}」对应集团码 ${groupCode}。`
})

function asExportInfo(value: unknown): ExportInfo | null {
  if (!value || typeof value !== 'object') return null
  const candidate = value as Record<string, unknown>
  const url = candidate.download_url
  if (!url) return null
  return { file_id: candidate.file_id ? String(candidate.file_id) : null, download_url: String(url) }
}

function resolveExport(keys: string[]): ExportInfo | null {
  for (const key of keys) {
    const resolved = asExportInfo(latestExports.value[key])
    if (resolved) return resolved
  }
  return null
}

const finalExport = computed(() => resolveExport(['final_result', 'final', 'result']))
const topnExport = computed(() => resolveExport(['topn_candidates', 'top_n_candidates', 'candidate_export', 'candidates']))
const reviewExport = computed(() => resolveExport(['review_records', 'manual_records', 'review_log', 'manual_review']))
const unmatchedExport = computed(() => resolveExport(['unmatched_list', 'unmatched_records', 'unmatched_export', 'unmatched']))

function openTask(task: TaskRow): void {
  router.push(`/tasks/${task.id}`)
}

function evaluate(task: TaskRow): void {
  router.push(`/tasks/${task.id}/evaluation`)
}

async function loadLatestDetails(task: TaskRow): Promise<void> {
  const [summaryResponse, previewResponse, exportResponse] = await Promise.all([
    api.get(`/tasks/${task.id}/workbench/summary`),
    api.get(`/tasks/${task.id}/live-results`, { params: { limit: 200 } }),
    api.get(`/tasks/${task.id}/exports`),
  ])
  latestSummary.value = summaryResponse.data ?? latestSummary.value
  latestRows.value = previewResponse.data?.rows ?? []
  latestExports.value = exportResponse.data ?? {}
}

async function load(): Promise<void> {
  loading.value = true
  try {
    const [tasksResponse, filesResponse] = await Promise.all([api.get('/tasks'), api.get('/files')])
    const files = (filesResponse.data ?? []) as FileRecord[]
    resultFiles.value = Object.fromEntries(files.filter(file => file.role === 'result').map(file => [file.file_id, file]))
    tasks.value = ((tasksResponse.data ?? []) as any[]).map(task => ({
      id: String(task.task_id),
      name: String(task.name ?? '未命名任务'),
      stage: String(task.stage ?? ''),
      progress: Number(task.progress ?? 0),
      status: String(task.status ?? ''),
      created_at: String(task.created_at ?? ''),
      finished_at: task.finished_at ? String(task.finished_at) : null,
      result_file_id: task.result_file_id ? String(task.result_file_id) : null,
      processed_rows: Number(task.processed_rows ?? 0),
      total_rows: Number(task.total_rows ?? 0),
      config_snapshot: task.config_snapshot && typeof task.config_snapshot === 'object' ? task.config_snapshot : null,
    }))
    latestSummary.value = { pending_review: 0, confirmed: 0, unmatched: 0, automatic_matched: 0 }
    latestRows.value = []
    latestExports.value = {}
    if (latestResult.value) await loadLatestDetails(latestResult.value)
  } catch {
    await router.push('/login')
  } finally {
    loading.value = false
  }
}

async function downloadExport(exportInfo: ExportInfo | null, key: string, unavailableMessage: string): Promise<void> {
  if (!exportInfo?.download_url) {
    ElMessage.info(unavailableMessage)
    return
  }
  downloadingExportKey.value = key
  try {
    window.location.href = String(exportInfo.download_url)
  } finally {
    window.setTimeout(() => {
      if (downloadingExportKey.value === key) downloadingExportKey.value = ''
    }, 800)
  }
}

async function download(task: TaskRow): Promise<void> {
  downloadingTaskId.value = task.id
  try {
    const response = (await api.get(`/tasks/${task.id}/exports`)).data
    const exportInfo = asExportInfo(response?.final_result)
    if (!exportInfo?.download_url) {
      ElMessage.warning('该任务尚未生成可下载的最终结果')
      await load()
      return
    }
    window.location.href = String(exportInfo.download_url)
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    downloadingTaskId.value = ''
  }
}

onMounted(load)
</script>

<template>
  <div class="results-page">
    <div class="toolbar results-toolbar">
      <div>
        <h2>STEP 4 · 输出结果</h2>
        <p>用业务口径查看匹配结果、处理状态和可下载清单。</p>
      </div>
      <el-button @click="load">刷新结果</el-button>
    </div>

    <section class="result-workbench" v-loading="loading" :class="{ 'needs-attention': allUnmatched }">
      <template v-if="latestResult">
        <div class="result-workbench-accent"></div>
        <div class="result-workbench-body">
          <div class="result-workbench-head">
            <div class="result-title-block">
              <div class="result-eyebrow" :class="{ warning: allUnmatched }">
                <span class="result-ready-dot" :class="{ warning: allUnmatched }"></span>
                {{ allUnmatched ? '结果已生成 · 需要关注匹配质量' : '最近一次已生成结果' }}
              </div>
              <h3>{{ latestResult.name }}</h3>
              <div class="result-meta-line">
                <span>生成完成：{{ formatTime(resultCompletedAt(latestResult)) }}</span>
              </div>
            </div>
            <el-button type="primary" plain @click="openTask(latestResult)">查看任务详情</el-button>
          </div>

          <div class="result-metrics">
            <div class="result-metric primary"><span>源数据总数</span><b>{{ formatCount(latestTotalRows) }}</b><small>源 Excel 参与匹配的记录</small></div>
            <div class="result-metric"><span>自动匹配数</span><b>{{ formatCount(latestSummary.automatic_matched) }}</b><small>达到自动匹配阈值</small></div>
            <div class="result-metric"><span>人工确认数</span><b>{{ formatCount(latestSummary.confirmed) }}</b><small>经 STEP3 人工确认</small></div>
            <div class="result-metric"><span>未匹配数</span><b>{{ formatCount(latestSummary.unmatched) }}</b><small>最终未形成集团码</small></div>
            <div class="result-metric"><span>待确认数</span><b>{{ formatCount(latestSummary.pending_review) }}</b><small>仍需人工判断</small></div>
            <div class="result-metric threshold"><span>自动匹配阈值</span><b>{{ formatScore(automaticThreshold) }}</b><small>达到该分值可自动匹配</small></div>
            <div class="result-metric threshold"><span>人工确认下限</span><b>{{ formatScore(reviewThreshold) }}</b><small>低于该分值通常不进入待确认</small></div>
          </div>

          <div v-if="allUnmatched" class="result-quality-alert">
            <div class="result-quality-alert-copy">
              <span class="result-quality-kicker">需要关注</span>
              <h4>本次任务已完成，但没有记录达到自动匹配阈值。</h4>
              <p>建议先进入 STEP3 查看候选分布和关键字段冲突，再决定是否调整判定阈值；不要仅为了提高匹配率直接放宽阈值。</p>
            </div>
            <div class="result-quality-stats">
              <div><span>当前阈值</span><b>{{ formatScore(automaticThreshold) }}</b></div>
              <div><span>最高候选分</span><b>{{ formatScore(scoreStats.highest) }}</b></div>
              <div><span>平均第一候选分</span><b>{{ formatScore(scoreStats.average) }}</b></div>
              <div class="recommendation"><span>是否建议进入 STEP3</span><b>建议复核</b></div>
            </div>
            <div class="result-quality-actions">
              <el-button type="warning" plain @click="openTask(latestResult)">进入任务检查 STEP3 判定</el-button>
            </div>
          </div>

          <div v-else-if="(latestSummary.pending_review ?? 0) > 0" class="result-note warning">
            当前还有 {{ latestSummary.pending_review }} 条待确认记录。建议先完成 STEP3 人工处理，再将本次结果作为最终业务结果使用。
          </div>

          <div class="result-preview">
            <div class="result-preview-head">
              <div>
                <b>最近一次生成结果预览</b>
                <span>展示 {{ previewRows.length }} 条业务结果</span>
              </div>
              <el-button link type="primary" @click="openTask(latestResult)">查看完整任务 →</el-button>
            </div>
            <div class="result-preview-explain">{{ previewNarrative }}</div>
            <el-table v-if="previewRows.length" :data="previewRows" size="small" class="result-preview-table">
              <el-table-column label="源表行号" width="108"><template #default="scope">{{ sourceRowNumber(scope.row) }}</template></el-table-column>
              <el-table-column label="客户物料编码" min-width="170" show-overflow-tooltip><template #default="scope"><b class="source-material-code">{{ customerMaterialCode(scope.row) }}</b></template></el-table-column>
              <el-table-column label="状态" width="108"><template #default="scope"><el-tag size="small" :type="resultStatusType(scope.row)">{{ resultStatusLabel(scope.row) }}</el-tag></template></el-table-column>
              <el-table-column label="目标表行号" width="116"><template #default="scope">{{ targetRowNumber(scope.row) }}</template></el-table-column>
              <el-table-column label="集团码" min-width="150"><template #default="scope"><b class="result-code">{{ finalGroupCode(scope.row) }}</b></template></el-table-column>
              <el-table-column label="第一候选分" width="116"><template #default="scope">{{ formatScore(scope.row.top1_score) }}</template></el-table-column>
            </el-table>
            <div v-else class="result-preview-empty">该结果暂无可预览记录，可直接下载最终匹配结果 Excel。</div>
          </div>

          <div class="result-downloads">
            <div class="result-downloads-head">
              <div><b>下载结果</b><span>按业务用途选择需要的清单</span></div>
            </div>
            <div class="result-download-primary">
              <el-button type="primary" size="large" :loading="downloadingExportKey === 'final'" :disabled="!finalExport" @click="downloadExport(finalExport, 'final', '该任务尚未生成可下载的最终匹配结果')">
                下载最终匹配结果 Excel
              </el-button>
              <span>用于业务交付和后续导入，包含本次最终判定结果。</span>
            </div>
            <div class="result-download-secondary">
              <el-tooltip :disabled="Boolean(topnExport)" content="当前后端尚未提供独立 TopN 候选下载" placement="top">
                <span><el-button :loading="downloadingExportKey === 'topn'" :disabled="!topnExport" @click="downloadExport(topnExport, 'topn', '当前尚未提供独立 TopN 候选下载')">下载 TopN 候选</el-button></span>
              </el-tooltip>
              <el-tooltip :disabled="Boolean(reviewExport)" content="当前后端尚未提供独立人工处理记录下载" placement="top">
                <span><el-button :loading="downloadingExportKey === 'review'" :disabled="!reviewExport" @click="downloadExport(reviewExport, 'review', '当前尚未提供独立人工处理记录下载')">下载人工处理记录</el-button></span>
              </el-tooltip>
              <el-tooltip :disabled="Boolean(unmatchedExport)" content="当前后端尚未提供独立未匹配清单下载" placement="top">
                <span><el-button :loading="downloadingExportKey === 'unmatched'" :disabled="!unmatchedExport" @click="downloadExport(unmatchedExport, 'unmatched', '当前尚未提供独立未匹配清单下载')">下载未匹配清单</el-button></span>
              </el-tooltip>
            </div>
          </div>
        </div>
      </template>

      <template v-else-if="!loading && waitingState && pendingTask">
        <div class="result-state-panel waiting">
          <div class="result-state-icon">…</div>
          <div class="result-state-content">
            <span class="result-state-kicker">结果尚不可下载</span>
            <h3>{{ waitingState.title }}</h3>
            <p>{{ waitingState.description }}</p>
            <div class="result-state-meta">
              <span>任务：{{ pendingTask.name }}</span>
              <span>阶段：{{ stageLabels[pendingTask.stage] ?? pendingTask.stage }}</span>
              <span>状态：{{ statusLabel(pendingTask.status) }}</span>
            </div>
            <el-progress v-if="waitingState.showProgress" :percentage="Math.round(pendingTask.progress)" :stroke-width="10" class="result-wait-progress"/>
            <div class="result-state-actions">
              <el-button type="primary" @click="router.push(waitingState.path)">{{ waitingState.action }}</el-button>
              <el-button @click="router.push('/tasks')">前往 STEP2</el-button>
            </div>
          </div>
        </div>
      </template>

      <template v-else-if="!loading">
        <div class="result-state-panel empty">
          <div class="result-state-icon">□</div>
          <div class="result-state-content">
            <span class="result-state-kicker">暂无输出结果</span>
            <h3>尚无任何已经生成完成的结果</h3>
            <p>当前没有可下载结果，也没有正在推进中的任务。请先创建任务并完成 STEP2 计算与必要的 STEP3 人工处理。</p>
            <div class="result-state-actions">
              <el-button type="primary" @click="router.push('/tasks/new')">新建匹配任务</el-button>
              <el-button @click="router.push('/tasks')">前往 STEP2</el-button>
            </div>
          </div>
        </div>
      </template>
    </section>

    <div class="panel results-history">
      <div class="section-head results-history-head">
        <div><h3>历史结果</h3><p>已生成过最终 Excel 的任务，可再次查看或下载。</p></div>
        <span class="results-history-count">{{ generatedResults.length }} 个结果</span>
      </div>
      <el-table :data="generatedResults" size="default" empty-text="暂无历史结果">
        <el-table-column label="任务" min-width="230"><template #default="scope"><a class="row-link" @click="openTask(scope.row)">{{ scope.row.name }}</a></template></el-table-column>
        <el-table-column label="完成时间" width="180"><template #default="scope">{{ formatTime(resultCompletedAt(scope.row)) }}</template></el-table-column>
        <el-table-column label="源数据总数" width="120"><template #default="scope">{{ scope.row.total_rows ? formatCount(scope.row.total_rows) : '—' }}</template></el-table-column>
        <el-table-column label="状态" width="105"><template #default="scope"><el-tag size="small" :type="statusTagType(scope.row.status)">{{ statusLabel(scope.row.status) }}</el-tag></template></el-table-column>
        <el-table-column label="操作" min-width="250"><template #default="scope">
          <el-button link type="primary" @click="openTask(scope.row)">查看</el-button>
          <el-button link type="primary" :loading="downloadingTaskId===scope.row.id" @click="download(scope.row)">下载最终结果</el-button>
          <el-button link type="success" @click="evaluate(scope.row)">准确率验收</el-button>
        </template></el-table-column>
      </el-table>
    </div>
  </div>
</template>
