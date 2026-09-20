<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { api } from '../api'
import { formatDurationMs } from '../taskTime'
import { businessRateWidth, formatBusinessRate } from '../resultRates'
import '../styles/pages/results.css'

type TaskRow = Record<string, unknown> & {
  id: string
  scheme_name: string
  stage: string
  progress: number
  status: string
  created_at: string
  started_at?: string | null
  finished_at?: string | null
  compute_duration_ms?: number | null
  result_file_id?: string | null
  processed_rows: number
  total_rows: number
}

type ResultSummary = Record<string, unknown> & {
  pending_review: number
  confirmed: number
  unmatched: number
  automatic_matched: number
}

type PreviewRow = Record<string, unknown> & {
  source_id?: string | null
  source_row_id?: string | number | null
  source_row_number?: string | number | null
  current_status?: string | null
  top1_group_code?: string | null
  top1_score?: number | null
  final_group_code?: string | null
  target_row_number?: string | number | null
  similarity?: number | null
  match_method?: string | null
  last_operator?: string | null
  last_operation_time?: string | null
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

type InputAssetInfo = {
  kind: 'source' | 'target'
  label: string
  original_name?: string | null
  uploaded_at?: string | null
  size_bytes?: number | null
  available: boolean
  download_url?: string | null
  message?: string | null
  profile_id?: string | null
  profile_name?: string | null
  profile_version?: number | null
  catalog_version_id?: string | null
}

type InputAssetBundle = {
  composite?: boolean
  source?: InputAssetInfo | null
  target?: InputAssetInfo | null
  targets?: InputAssetInfo[]
}

const router = useRouter()
const tasks = ref<TaskRow[]>([])
const resultFiles = ref<Record<string, FileRecord>>({})
const latestSummary = ref<ResultSummary>({ pending_review: 0, confirmed: 0, unmatched: 0, automatic_matched: 0 })
const latestRows = ref<PreviewRow[]>([])
const latestExports = ref<ExportBundle>({})
const latestInputAssets = ref<InputAssetBundle>({})
const loading = ref(true)
const downloadingTaskId = ref('')
const downloadingExportKey = ref('')
const downloadingInputRole = ref('')

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
      title: '正在等待第二步计算完成',
      description: `方案「${task.scheme_name}」仍在计算中，结果文件尚未生成，当前不可下载。`,
      action: '查看计算进度',
      path: `/tasks/${task.id}`,
      showProgress: true,
    }
  }
  if (task.status === 'COMPLETED' && task.stage === 'REVIEW') {
    return {
      title: '正在等待第三步人工处理完成',
      description: `方案「${task.scheme_name}」已完成计算，但仍有记录需要人工处理，完成后才能形成正式结果。`,
      action: '进入人工处理',
      path: `/tasks/${task.id}`,
      showProgress: false,
    }
  }
  if (task.status === 'COMPLETED' && task.stage === 'RESULT') {
    return {
      title: '前序步骤已完成，结果文件尚未生成',
      description: `方案「${task.scheme_name}」已经可以生成最终结果，请进入匹配详情完成结果生成。`,
      action: '进入匹配详情',
      path: `/tasks/${task.id}`,
      showProgress: false,
    }
  }
  return {
    title: '本次匹配尚未形成可下载结果',
    description: `方案「${task.scheme_name}」当前状态为“${statusLabel(task.status)}”，请进入匹配详情查看。`,
    action: '查看匹配详情',
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
  return ({ MATCHED: '自动匹配', CONFIRMED: '人工匹配', REVIEW: '待处理', UNMATCHED: '未匹配' } as Record<string, string>)[String(row.current_status ?? '')] ?? String(row.current_status ?? '—')
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

function firstValue(record: Record<string, unknown> | null | undefined, keys: string[]): unknown {
  if (!record) return null
  for (const key of keys) {
    const value = record[key]
    if (value !== null && value !== undefined && value !== '') return value
  }
  return null
}

function displayValue(value: unknown): string {
  return value === null || value === undefined || value === '' ? '—' : String(value)
}

function sourceRowNumber(row: PreviewRow): string {
  return displayValue(firstValue(row, ['source_excel_row', 'source_row_number', 'source_row_no', 'source_row']))
}

function targetRowNumber(row: PreviewRow): string {
  return displayValue(firstValue(row, ['target_excel_row', 'target_row_number', 'target_row_no', 'target_row']))
}

function sourceMaterialCode(row: PreviewRow): string {
  return displayValue(firstValue(row, ['source_material_code', 'customer_material_code', 'material_code', 'source_id']))
}

function finalGroupCode(row: PreviewRow): string {
  const value = firstValue(row, ['final_group_code', 'group_code'])
  if (value !== null) return String(value)
  if (row.current_status === 'MATCHED' || row.current_status === 'CONFIRMED') {
    return row.top1_group_code ? String(row.top1_group_code) : '—'
  }
  return '—'
}

function similarity(row: PreviewRow): string {
  return formatScore(firstValue(row, ['similarity', 'final_score', 'selected_score', 'top1_score']))
}

function matchMethod(row: PreviewRow): string {
  const direct = firstValue(row, ['match_method', 'matching_method', 'decision_method'])
  if (direct !== null) return String(direct)
  if (row.current_status === 'MATCHED') return '自动匹配'
  if (row.current_status === 'CONFIRMED') return '人工匹配'
  if (row.current_status === 'REVIEW') return '待人工处理'
  return '未匹配'
}

function operationAccount(row: PreviewRow): string {
  return displayValue(firstValue(row, ['last_operator', 'operation_account', 'operator', 'updated_by']))
}

function operationTime(row: PreviewRow): string {
  const value = firstValue(row, ['last_operation_time', 'operation_time', 'reviewed_at', 'updated_at'])
  return formatTime(value === null ? null : String(value))
}

function totalRows(task: TaskRow | null): number {
  const direct = Number(task?.total_rows ?? 0)
  if (direct > 0) return direct
  const summary = latestSummary.value
  return Number(summary.automatic_matched || 0) + Number(summary.confirmed || 0) + Number(summary.unmatched || 0) + Number(summary.pending_review || 0)
}

const latestTotalRows = computed(() => totalRows(latestResult.value))

const previewRows = computed(() => {
  const rows = latestRows.value.slice()
  rows.sort((left, right) => {
    const a = numberValue(firstValue(left, ['source_excel_row', 'source_row_number', 'source_row_no', 'source_row']))
    const b = numberValue(firstValue(right, ['source_excel_row', 'source_row_number', 'source_row_no', 'source_row']))
    if (a === null || b === null) return 0
    return a - b
  })
  return rows.slice(0, 10)
})

const allUnmatched = computed(() => {
  const total = latestTotalRows.value
  if (total <= 0) return false
  return Number(latestSummary.value.unmatched || 0) === total
    && Number(latestSummary.value.automatic_matched || 0) === 0
    && Number(latestSummary.value.confirmed || 0) === 0
    && Number(latestSummary.value.pending_review || 0) === 0
})

const startedAccount = computed(() => displayValue(firstValue(latestSummary.value, ['started_by', 'starter', 'started_user', 'started_username'])
  ?? firstValue(latestResult.value, ['started_by', 'starter', 'started_user', 'started_username'])))

const previewNarrative = computed(() => {
  const row = previewRows.value.find(item => finalGroupCode(item) !== '—')
  if (!row) return '本次预览中尚无已形成集团码的记录，可通过下表查看每条源数据的当前处理状态。'
  const sourceRow = sourceRowNumber(row)
  const targetRow = targetRowNumber(row)
  const material = sourceMaterialCode(row)
  const groupCode = finalGroupCode(row)
  if (sourceRow !== '—' && targetRow !== '—') {
    return `源 Excel 第 ${sourceRow} 行的物料「${material}」，匹配到了集团码表第 ${targetRow} 行，对应集团码 ${groupCode}。`
  }
  if (sourceRow !== '—') {
    return `源 Excel 第 ${sourceRow} 行的物料「${material}」，对应集团码 ${groupCode}。`
  }
  return `源物料「${material}」对应集团码 ${groupCode}。`
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

function openTask(task: TaskRow): void {
  router.push(`/tasks/${task.id}`)
}

async function loadLatestDetails(task: TaskRow): Promise<void> {
  const [summaryResponse, previewResponse, exportResponse, inputAssetsResponse] = await Promise.all([
    api.get(`/tasks/${task.id}/workbench/summary`),
    api.get(`/tasks/${task.id}/live-results`, { params: { limit: 200 } }),
    api.get(`/tasks/${task.id}/exports`),
    api.get(`/tasks/${task.id}/input-assets`),
  ])
  latestSummary.value = summaryResponse.data ?? latestSummary.value
  latestRows.value = summaryResponse.data?.preview_rows ?? previewResponse.data?.rows ?? []
  latestExports.value = exportResponse.data ?? {}
  latestInputAssets.value = inputAssetsResponse.data ?? {}
}

async function load(): Promise<void> {
  loading.value = true
  try {
    const [tasksResponse, filesResponse] = await Promise.all([api.get('/tasks'), api.get('/files')])
    const files = (filesResponse.data ?? []) as FileRecord[]
    resultFiles.value = Object.fromEntries(files.filter(file => file.role === 'result').map(file => [file.file_id, file]))
    tasks.value = ((tasksResponse.data ?? []) as Record<string, unknown>[]).map(task => ({
      ...task,
      id: String(task.task_id),
      scheme_name: String(task.scheme_name ?? '未命名方案'),
      stage: String(task.stage ?? ''),
      progress: Number(task.progress ?? 0),
      status: String(task.status ?? ''),
      created_at: String(task.created_at ?? ''),
      started_at: task.started_at ? String(task.started_at) : null,
      finished_at: task.finished_at ? String(task.finished_at) : null,
      compute_duration_ms: task.compute_duration_ms == null ? null : Number(task.compute_duration_ms),
      result_file_id: task.result_file_id ? String(task.result_file_id) : null,
      processed_rows: Number(task.processed_rows ?? 0),
      total_rows: Number(task.total_rows ?? 0),
    }))
    latestSummary.value = { pending_review: 0, confirmed: 0, unmatched: 0, automatic_matched: 0 }
    latestRows.value = []
    latestExports.value = {}
    latestInputAssets.value = {}
    if (latestResult.value) await loadLatestDetails(latestResult.value)
  } catch {
    await router.push('/login')
  } finally {
    loading.value = false
  }
}

function inputAssetDisplayName(asset: InputAssetInfo | null | undefined): string {
  return String(asset?.original_name || asset?.message || '该历史任务的原始文件已无法确认')
}

function inputAssetMeta(asset: InputAssetInfo | null | undefined): string {
  if (!asset?.available) return String(asset?.message || '该历史任务的原始文件已无法确认')
  if (asset.uploaded_at) return `原文件上传时间：${formatTime(asset.uploaded_at)}`
  return '任务启动时已冻结原始文件引用'
}

function compositeTargetLabel(asset: InputAssetInfo, index: number): string {
  const name = String(asset.profile_name || '').trim()
  const version = asset.profile_version ? ` · v${asset.profile_version}` : ''
  return `${name || `子方案 ${index + 1}`}${version}`
}

function downloadInputAsset(asset: InputAssetInfo | null | undefined, role: string): void {
  if (!asset?.available || !asset.download_url) {
    ElMessage.warning(asset?.message || '该历史任务的原始文件已无法确认')
    return
  }
  downloadingInputRole.value = role
  window.location.href = String(asset.download_url)
  window.setTimeout(() => {
    if (downloadingInputRole.value === role) downloadingInputRole.value = ''
  }, 800)
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
      ElMessage.warning('该方案尚未生成可下载的最终结果')
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
        <h2>第四步 · 输出结果</h2>
        <p>查看最终匹配情况，并下载包含完整业务字段、候选明细和人工操作记录的正式 Excel。</p>
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
                {{ allUnmatched ? '结果已生成 · 建议检查匹配质量' : '最近一次已生成结果' }}
              </div>
              <h3>{{ latestResult.scheme_name }}</h3>
              <div class="result-meta-line">
                <span>任务开始时间：{{ formatTime(latestResult.started_at) }}</span>
                <span>自动计算耗时：{{ formatDurationMs(latestResult.compute_duration_ms) }}</span>
              </div>
            </div>
            <el-button type="primary" plain @click="openTask(latestResult)">查看匹配详情</el-button>
          </div>

          <div class="result-task-info">
            <div class="result-section-heading">
              <b>任务资料</b>
              <span>记录本次方案、启动信息与自动计算性能，不包含人工等待时间。</span>
            </div>
            <div class="result-lifecycle">
              <div><span>方案名称</span><b>{{ latestResult.scheme_name }}</b></div>
              <div><span>任务开始时间</span><b>{{ formatTime(latestResult.started_at) }}</b></div>
              <div><span>自动计算耗时</span><b>{{ formatDurationMs(latestResult.compute_duration_ms) }}</b></div>
              <div><span>启动账号</span><b>{{ startedAccount }}</b></div>
              <div><span>结果生成时间</span><b>{{ formatTime(resultCompletedAt(latestResult)) }}</b></div>
            </div>
          </div>

          <div class="result-input-assets">
            <div class="result-input-assets-head">
              <div>
                <b>本次使用的原始文件</b>
                <span>任务启动时冻结的输入资料，历史任务不会跟随后来更新的集团码标准文件。</span>
              </div>
            </div>
            <div class="result-input-asset-list">
              <div class="result-input-asset-row">
                <div class="result-input-asset-kind">待匹配源数据</div>
                <div class="result-input-asset-file">
                  <b>{{ inputAssetDisplayName(latestInputAssets.source) }}</b>
                  <span>{{ inputAssetMeta(latestInputAssets.source) }}</span>
                </div>
                <el-button
                  type="primary"
                  plain
                  :loading="downloadingInputRole === 'source'"
                  :disabled="!latestInputAssets.source?.available"
                  @click="downloadInputAsset(latestInputAssets.source, 'source')"
                >下载原始文件</el-button>
              </div>
              <template v-if="latestInputAssets.composite">
                <div
                  v-for="(asset, index) in (latestInputAssets.targets ?? [])"
                  :key="`${asset.profile_id ?? index}-${asset.profile_version ?? ''}`"
                  class="result-input-asset-row"
                >
                  <div class="result-input-asset-kind">{{ compositeTargetLabel(asset, index) }}</div>
                  <div class="result-input-asset-file">
                    <b>{{ inputAssetDisplayName(asset) }}</b>
                    <span>{{ inputAssetMeta(asset) }}</span>
                  </div>
                  <el-button
                    type="primary"
                    plain
                    :loading="downloadingInputRole === `target.${asset.profile_id ?? index}`"
                    :disabled="!asset.available"
                    @click="downloadInputAsset(asset, `target.${asset.profile_id ?? index}`)"
                  >下载原始文件</el-button>
                </div>
              </template>
              <div v-else class="result-input-asset-row">
                <div class="result-input-asset-kind">集团码标准数据</div>
                <div class="result-input-asset-file">
                  <b>{{ inputAssetDisplayName(latestInputAssets.target) }}</b>
                  <span>{{ inputAssetMeta(latestInputAssets.target) }}</span>
                </div>
                <el-button
                  type="primary"
                  plain
                  :loading="downloadingInputRole === 'target'"
                  :disabled="!latestInputAssets.target?.available"
                  @click="downloadInputAsset(latestInputAssets.target, 'target')"
                >下载原始文件</el-button>
              </div>
            </div>
          </div>

          <div class="result-section-heading">
            <b>本次匹配结果</b>
            <span>输入资料经过自动计算与人工处理后的业务结果摘要。</span>
          </div>
          <div class="result-metrics">
            <div class="result-metric primary"><span>源数据总数</span><b>{{ formatCount(latestTotalRows) }}</b><small>源 Excel 参与匹配的记录</small></div>
            <div class="result-metric automatic"><span>自动匹配数</span><b>{{ formatCount(latestSummary.automatic_matched) }}</b><small>系统直接形成最终集团码</small></div>
            <div class="result-metric manual"><span>人工匹配数</span><b>{{ formatCount(latestSummary.confirmed) }}</b><small>经人工选择后形成集团码</small></div>
            <div class="result-metric unmatched"><span>未匹配数</span><b>{{ formatCount(latestSummary.unmatched) }}</b><small>最终未形成集团码</small></div>
            <div class="result-metric pending"><span>待处理数</span><b>{{ formatCount(latestSummary.pending_review) }}</b><small>仍需要人工判断</small></div>
          </div>

          <div class="result-rates">
            <div class="result-rate automatic">
              <span>自动匹配率</span>
              <b>{{ formatBusinessRate(latestSummary.automatic_matched, latestTotalRows) }}</b>
              <small>系统自动形成匹配结果 / 总数据</small>
            </div>
            <div class="result-rate manual">
              <span>人工匹配率</span>
              <b>{{ formatBusinessRate(latestSummary.confirmed, latestTotalRows) }}</b>
              <small>人工最终选择匹配结果 / 总数据</small>
            </div>
            <div class="result-rate unmatched">
              <span>未匹配率</span>
              <b>{{ formatBusinessRate(latestSummary.unmatched, latestTotalRows) }}</b>
              <small>最终未形成集团码 / 总数据</small>
            </div>
            <div v-if="Number(latestSummary.pending_review || 0) > 0" class="result-rate pending">
              <span>待处理率</span>
              <b>{{ formatBusinessRate(latestSummary.pending_review, latestTotalRows) }}</b>
              <small>仍需人工判断 / 总数据</small>
            </div>
          </div>
          <div class="result-rate-note">以上比例表示不同处理结果在总数据中的占比，不代表匹配结果是否正确。</div>

          <div class="result-composition">
            <div class="result-composition-head">
              <div>
                <b>匹配结果构成</b>
                <span>按总数据占比展示自动匹配、人工匹配、未匹配与待处理。</span>
              </div>
            </div>
            <div
              class="result-composition-bar"
              role="img"
              :aria-label="`匹配结果构成：自动匹配 ${formatBusinessRate(latestSummary.automatic_matched, latestTotalRows)}，人工匹配 ${formatBusinessRate(latestSummary.confirmed, latestTotalRows)}，未匹配 ${formatBusinessRate(latestSummary.unmatched, latestTotalRows)}，待处理 ${formatBusinessRate(latestSummary.pending_review, latestTotalRows)}`"
            >
              <span class="result-composition-segment automatic" :style="{ width: businessRateWidth(latestSummary.automatic_matched, latestTotalRows) }"></span>
              <span class="result-composition-segment manual" :style="{ width: businessRateWidth(latestSummary.confirmed, latestTotalRows) }"></span>
              <span class="result-composition-segment unmatched" :style="{ width: businessRateWidth(latestSummary.unmatched, latestTotalRows) }"></span>
              <span class="result-composition-segment pending" :style="{ width: businessRateWidth(latestSummary.pending_review, latestTotalRows) }"></span>
            </div>
            <div class="result-composition-legend">
              <span><i class="composition-dot automatic"></i><b>自动匹配</b>{{ formatBusinessRate(latestSummary.automatic_matched, latestTotalRows) }} · {{ formatCount(latestSummary.automatic_matched) }} 条</span>
              <span><i class="composition-dot manual"></i><b>人工匹配</b>{{ formatBusinessRate(latestSummary.confirmed, latestTotalRows) }} · {{ formatCount(latestSummary.confirmed) }} 条</span>
              <span><i class="composition-dot unmatched"></i><b>未匹配</b>{{ formatBusinessRate(latestSummary.unmatched, latestTotalRows) }} · {{ formatCount(latestSummary.unmatched) }} 条</span>
              <span><i class="composition-dot pending"></i><b>待处理</b>{{ formatBusinessRate(latestSummary.pending_review, latestTotalRows) }} · {{ formatCount(latestSummary.pending_review) }} 条</span>
            </div>
          </div>

          <div v-if="allUnmatched" class="result-quality-alert">
            <div class="result-quality-alert-copy">
              <span class="result-quality-kicker">需要关注</span>
              <h4>本次匹配已完成，但当前没有形成有效匹配结果。</h4>
              <p>建议回到第三步查看候选相似度和字段对比，再判断是否需要调整匹配条件或进行人工匹配。</p>
            </div>
            <div class="result-quality-actions">
              <el-button type="warning" plain @click="openTask(latestResult)">进入第三步检查</el-button>
            </div>
          </div>

          <div v-else-if="(latestSummary.pending_review ?? 0) > 0" class="result-note warning">
            当前还有 {{ latestSummary.pending_review }} 条待处理记录。建议完成第三步人工处理后，再将本次文件作为最终业务结果使用。
          </div>

          <div class="result-preview">
            <div class="result-preview-head">
              <div>
                <b>最近一次生成结果预览</b>
                <span>展示 {{ previewRows.length }} 条业务结果</span>
              </div>
              <el-button link type="primary" @click="openTask(latestResult)">查看完整匹配详情 →</el-button>
            </div>
            <div class="result-preview-explain">{{ previewNarrative }}</div>
            <el-table v-if="previewRows.length" :data="previewRows" size="small" class="result-preview-table">
              <el-table-column label="源表行号" width="100"><template #default="scope">{{ sourceRowNumber(scope.row) }}</template></el-table-column>
              <el-table-column label="源物料编码" min-width="150" show-overflow-tooltip><template #default="scope"><b class="source-material-code">{{ sourceMaterialCode(scope.row) }}</b></template></el-table-column>
              <el-table-column label="状态" width="105"><template #default="scope"><el-tag size="small" :type="resultStatusType(scope.row)">{{ resultStatusLabel(scope.row) }}</el-tag></template></el-table-column>
              <el-table-column label="目标表行号" width="110"><template #default="scope">{{ targetRowNumber(scope.row) }}</template></el-table-column>
              <el-table-column label="集团码" min-width="135" show-overflow-tooltip><template #default="scope"><b class="result-code">{{ finalGroupCode(scope.row) }}</b></template></el-table-column>
              <el-table-column label="相似度" width="90"><template #default="scope">{{ similarity(scope.row) }}</template></el-table-column>
              <el-table-column label="匹配方式" width="125"><template #default="scope">{{ matchMethod(scope.row) }}</template></el-table-column>
              <el-table-column label="最后操作账号" width="135" show-overflow-tooltip><template #default="scope">{{ operationAccount(scope.row) }}</template></el-table-column>
              <el-table-column label="最后操作时间" width="170"><template #default="scope">{{ operationTime(scope.row) }}</template></el-table-column>
            </el-table>
            <div v-else class="result-preview-empty">该结果暂无可预览记录，可直接下载最终匹配结果 Excel。</div>
          </div>

          <div class="result-downloads">
            <div class="result-downloads-head">
              <div><b>输出资料</b><span>最终匹配结果 Excel，可与上方两份原始输入一起完整复原本次任务</span></div>
            </div>
            <div class="result-output-ready">
              <span class="result-output-ready-dot"></span>
              <div>
                <b>最终 Excel 已生成</b>
                <span>可直接下载正式结果；如仍需调整个别记录，可返回第三步继续人工匹配。</span>
              </div>
            </div>
            <div class="result-download-primary">
              <div class="result-download-actions">
                <el-button size="large" @click="router.push('/review')">← 人工调整</el-button>
                <el-button type="primary" size="large" :loading="downloadingExportKey === 'final'" :disabled="!finalExport" @click="downloadExport(finalExport, 'final', '该方案尚未生成可下载的最终匹配结果')">
                  下载结果 Excel
                </el-button>
              </div>
              <span>包含“匹配摘要、最终匹配结果、Top5候选、人工操作记录、未匹配清单”五类内容，并保留源/目标业务字段。</span>
            </div>
            <div class="result-excel-hints">
              <span><i class="hint-dot exact"></i>完全一致</span>
              <span><i class="hint-dot partial"></i>部分相似</span>
              <span><i class="hint-dot different"></i>不一致</span>
              <span><i class="hint-dot missing"></i>无数据</span>
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
              <span>方案：{{ pendingTask.scheme_name }}</span>
              <span>任务开始时间：{{ formatTime(pendingTask.started_at) }}</span>
              <span>自动计算耗时：{{ formatDurationMs(pendingTask.compute_duration_ms, RUNNING_STATUSES.includes(pendingTask.status) ? '计算中' : '暂无准确记录') }}</span>
              <span>阶段：{{ stageLabels[pendingTask.stage] ?? pendingTask.stage }}</span>
              <span>状态：{{ statusLabel(pendingTask.status) }}</span>
            </div>
            <el-progress v-if="waitingState.showProgress" :percentage="Math.round(pendingTask.progress)" :stroke-width="10" class="result-wait-progress"/>
            <div class="result-state-actions">
              <el-button type="primary" @click="router.push(waitingState.path)">{{ waitingState.action }}</el-button>
              <el-button @click="router.push('/tasks')">查看匹配列表</el-button>
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
            <p>当前没有可下载结果，也没有正在推进中的匹配。请先选择方案并完成计算与必要的人工处理。</p>
            <div class="result-state-actions">
              <el-button type="primary" @click="router.push('/profiles')">选择匹配方案</el-button>
              <el-button @click="router.push('/tasks')">查看匹配列表</el-button>
            </div>
          </div>
        </div>
      </template>
    </section>

    <div class="panel results-history">
      <div class="section-head results-history-head">
        <div><h3>历史结果</h3><p>已生成过正式 Excel 的匹配结果，可再次查看或下载。</p></div>
        <span class="results-history-count">{{ generatedResults.length }} 个结果</span>
      </div>
      <el-table :data="generatedResults" size="default" empty-text="暂无历史结果">
        <el-table-column label="方案名称" min-width="230"><template #default="scope"><a class="row-link" @click="openTask(scope.row)">{{ scope.row.scheme_name }}</a></template></el-table-column>
        <el-table-column label="任务开始时间" width="180"><template #default="scope">{{ formatTime(scope.row.started_at) }}</template></el-table-column>
        <el-table-column label="自动计算耗时" width="170"><template #default="scope">{{ formatDurationMs(scope.row.compute_duration_ms) }}</template></el-table-column>
        <el-table-column label="结果生成时间" width="180"><template #default="scope">{{ formatTime(resultCompletedAt(scope.row)) }}</template></el-table-column>
        <el-table-column label="源数据总数" width="120"><template #default="scope">{{ scope.row.total_rows ? formatCount(scope.row.total_rows) : '—' }}</template></el-table-column>
        <el-table-column label="状态" width="105"><template #default="scope"><el-tag size="small" :type="statusTagType(scope.row.status)">{{ statusLabel(scope.row.status) }}</el-tag></template></el-table-column>
        <el-table-column label="操作" min-width="190"><template #default="scope">
          <el-button link type="primary" @click="openTask(scope.row)">查看</el-button>
          <el-button link type="primary" :loading="downloadingTaskId===scope.row.id" @click="download(scope.row)">下载正式结果</el-button>
        </template></el-table-column>
      </el-table>
    </div>
  </div>
</template>
