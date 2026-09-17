<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '../api'
import {
  downloadManualWorkbook,
  fetchCalibrationStatistics,
  fetchCandidates,
  fetchWorkbenchPage,
  reDecideSingleThreshold,
  runReviewBatch,
  uploadManualWorkbook,
  type ReviewBatchAction,
  type ReviewFilter,
  type ReviewSelection,
  type ReviewStatus,
} from '../services/reviewWorkbenchApi'
import '../styles/pages/review.css'
import '../styles/pages/review-large-scale.css'

type ReviewSummary = {
  pending_review: number
  confirmed: number
  unmatched: number
  automatic_matched: number
}

type ReviewTask = {
  id: string
  scheme_name: string
  stage: string
  progress: number
  status: string
  created_at: string
  started_at?: string | null
  finished_at?: string | null
  result_file_id?: string | null
  error_code?: string | null
  error_message?: string | null
  config_snapshot?: Record<string, any>
  summary?: ReviewSummary
  summaryError?: boolean
}

type ProgressState = {
  task_id: string
  stage: string
  status: string
  progress: number
  processed_rows: number
  total_rows: number
  current_phase?: string | null
}

type FieldScore = {
  rule_id: string
  score: number
}

type Candidate = {
  rank: number
  target_group_code: string
  target_row_number?: number | null
  score: number
  target_payload: Record<string, unknown>
  field_scores?: FieldScore[]
}

type CandidateDisplayField = {
  id: string
  label: string
  value: string
}

type WorkbenchItem = {
  source_row_id: string
  source_row_number?: number | null
  source_id: string
  source_payload: Record<string, unknown>
  top1_group_code?: string | null
  top1_score?: number
  second_score?: number
  score_gap?: number
  current_status?: string
  original_status?: string
  final_group_code?: string | null
  candidates?: Candidate[]
}

type FieldDescriptor = {
  id: string
  label: string
  sourceFields: string[]
  targetFields: string[]
  ruleId?: string
}

type StatusFilter = 'all' | 'auto' | 'review' | 'confirmed' | 'unmatched'
type ComparisonKind = 'exact' | 'partial' | 'different' | 'empty'
type HistogramBucket = { min: number; max: number; count: number }

type ThresholdPreview = {
  before: { matched: number; review: number; unmatched: number; confirmed: number }
  after: { matched: number; review: number; unmatched: number; confirmed: number }
  accuracyBefore?: number | null
  accuracyAfter?: number | null
}

type ImportFeedback = {
  success: number
  skipped: number
  conflicts: number
  errors: number
  details: any[]
}

type BatchFeedback = {
  success: number
  failed: number
  conflicts: number
  details: any[]
}

const route = useRoute()
const router = useRouter()
const RUNNING_STATUSES = ['RUNNING', 'PREPARING', 'RECOVERING', 'PENDING']
const PAGE_SIZE_OPTIONS = [50, 100, 200]
const NONE_SELECTION = '__NONE__'
const STATUS_TABS: Array<{ key: StatusFilter; label: string; backend: ReviewStatus }> = [
  { key: 'all', label: '全部', backend: 'ALL' },
  { key: 'auto', label: '已自动匹配', backend: 'MATCHED' },
  { key: 'review', label: '待人工匹配', backend: 'REVIEW' },
  { key: 'confirmed', label: '已人工匹配', backend: 'CONFIRMED' },
  { key: 'unmatched', label: '未匹配', backend: 'UNMATCHED' },
]

const reviewRows = ref<ReviewTask[]>([])
const activeTaskId = ref('')
const calculatingTask = ref<ReviewTask | null>(null)
const calculatingProgress = ref<ProgressState | null>(null)
const latestFailed = ref<ReviewTask | null>(null)
const loadError = ref('')
const loading = ref(false)

const summary = ref<ReviewSummary>({ pending_review: 0, confirmed: 0, unmatched: 0, automatic_matched: 0 })
const workbenchItems = ref<WorkbenchItem[]>([])
const workbenchTotal = ref(0)
const page = ref(1)
const pageSize = ref(50)
const listLoading = ref(false)
const statusFilter = ref<StatusFilter>('review')
const searchQ = ref('')
const scoreMin = ref<number | undefined>(undefined)
const scoreMax = ref<number | undefined>(undefined)

const selectedRowIds = ref<string[]>([])
const selectAllFiltered = ref(false)
const batchBusy = ref(false)
const batchFeedback = ref<BatchFeedback | null>(null)

const candidateMap = ref<Record<string, Candidate[]>>({})
const candidateLoading = ref<Record<string, boolean>>({})
const candidateError = ref<Record<string, boolean>>({})
const expandedRows = ref<Record<string, boolean>>({})
const selectedByRow = ref<Record<string, string>>({})
const mutationBusyRow = ref('')
const comparisonPanelRefs = new Map<string, HTMLElement>()

const mappingRules = ref<FieldDescriptor[]>([])
const selectedFieldIds = ref<string[]>([])
const fieldSelectionTouched = ref(false)
const showAllFields = ref(false)

const currentSuccessThreshold = ref(88)
const draftSuccessThreshold = ref(88)
const thresholdPreview = ref<ThresholdPreview | null>(null)
const thresholdPreviewSignature = ref('')
const previewBusy = ref(false)
const applyBusy = ref(false)
const top1Histogram = ref<HistogramBucket[]>([])
const gapHistogram = ref<HistogramBucket[]>([])

const importInput = ref<HTMLInputElement | null>(null)
const importBusy = ref(false)
const importFeedback = ref<ImportFeedback | null>(null)

let pollTimer: number | undefined
let progressRefreshing = false
let contextVersion = 0

const activeTask = computed(() => reviewRows.value.find(task => task.id === activeTaskId.value) ?? null)
const workspaceTasks = computed(() => reviewRows.value.filter(task => {
  if (task.summaryError) return false
  const s = task.summary
  return Boolean(s && (s.pending_review + s.confirmed + s.unmatched + s.automatic_matched) > 0)
}))
const hasUnknownReviewState = computed(() => reviewRows.value.some(task => task.summaryError))
const consoleMode = computed<'ready' | 'waiting' | 'empty' | 'error'>(() => {
  if (loadError.value) return 'error'
  if (activeTask.value) return 'ready'
  if (hasUnknownReviewState.value) return 'error'
  if (calculatingTask.value) return 'waiting'
  return 'empty'
})
const waitingPercent = computed(() => percent(calculatingProgress.value?.progress ?? calculatingTask.value?.progress ?? 0))
const waitingProcessed = computed(() => Number(calculatingProgress.value?.processed_rows ?? 0))
const waitingTotal = computed(() => Number(calculatingProgress.value?.total_rows ?? 0))
const totalRecords = computed(() => summary.value.pending_review + summary.value.confirmed + summary.value.unmatched + summary.value.automatic_matched)
const currentStatusBackend = computed<ReviewStatus>(() => STATUS_TABS.find(tab => tab.key === statusFilter.value)?.backend ?? 'REVIEW')
const currentFilter = computed<ReviewFilter>(() => ({
  status: currentStatusBackend.value,
  q: searchQ.value.trim() || undefined,
  first_score_min: scoreMin.value,
  first_score_max: scoreMax.value,
}))
const currentPageIds = computed(() => workbenchItems.value.map(item => item.source_row_id))
const selectedExplicitCount = computed(() => selectedRowIds.value.length)
const allPageSelected = computed(() => currentPageIds.value.length > 0 && currentPageIds.value.every(id => selectedRowIds.value.includes(id)))
const hasSelection = computed(() => selectAllFiltered.value || selectedExplicitCount.value > 0)
const selectionCount = computed(() => selectAllFiltered.value ? workbenchTotal.value : selectedExplicitCount.value)
const thresholdDirty = computed(() => draftSuccessThreshold.value !== currentSuccessThreshold.value)
const thresholdValid = computed(() => draftSuccessThreshold.value >= 1 && draftSuccessThreshold.value <= 100)
const currentPreviewSignature = computed(() => `${draftSuccessThreshold.value}`)
const canApplyThreshold = computed(() => thresholdDirty.value && thresholdValid.value && thresholdPreview.value !== null && thresholdPreviewSignature.value === currentPreviewSignature.value)
const maxHistogramCount = computed(() => Math.max(1, ...top1Histogram.value.map(item => item.count), ...gapHistogram.value.map(item => item.count)))

const pageFieldDescriptors = computed<FieldDescriptor[]>(() => {
  const descriptors = mappingRules.value.map(rule => ({ ...rule }))
  const referencedSource = new Set(descriptors.flatMap(item => item.sourceFields))
  const referencedTarget = new Set(descriptors.flatMap(item => item.targetFields))
  const sourceKeys = new Set<string>()
  const targetKeys = new Set<string>()
  for (const item of workbenchItems.value) {
    Object.keys(item.source_payload ?? {}).forEach(key => sourceKeys.add(key))
    for (const candidate of candidatesFor(item)) Object.keys(candidate.target_payload ?? {}).forEach(key => targetKeys.add(key))
  }
  for (const key of [...new Set([...sourceKeys, ...targetKeys])]) {
    if (referencedSource.has(key) || referencedTarget.has(key)) continue
    descriptors.push({ id: `raw:${key}`, label: key, sourceFields: sourceKeys.has(key) ? [key] : [], targetFields: targetKeys.has(key) ? [key] : [] })
  }
  return descriptors
})
const visibleFieldDescriptors = computed(() => {
  const selected = pageFieldDescriptors.value.filter(field => selectedFieldIds.value.includes(field.id))
  return showAllFields.value ? selected : selected.slice(0, 4)
})
const coreVisibleFields = computed(() => visibleFieldDescriptors.value.slice(0, 3))

function normalizeTask(task: any): ReviewTask {
  return {
    id: String(task.task_id ?? ''),
    scheme_name: String(task.scheme_name ?? '未命名方案'),
    stage: String(task.stage ?? ''),
    progress: Number(task.progress ?? 0),
    status: String(task.status ?? ''),
    created_at: String(task.created_at ?? ''),
    started_at: task.started_at ? String(task.started_at) : null,
    finished_at: task.finished_at ? String(task.finished_at) : null,
    result_file_id: task.result_file_id ? String(task.result_file_id) : null,
    error_code: task.error_code ? String(task.error_code) : null,
    error_message: task.error_message ? String(task.error_message) : null,
    config_snapshot: task.config_snapshot ?? undefined,
  }
}

function percent(value: unknown): number {
  const number = Number(value)
  if (!Number.isFinite(number)) return 0
  return Math.max(0, Math.min(100, Math.round(number)))
}
function formatNumber(value: unknown): string {
  const number = Number(value ?? 0)
  return Number.isFinite(number) ? number.toLocaleString() : '0'
}
function formatScore(value: unknown): string {
  const number = Number(value ?? 0)
  return Number.isFinite(number) ? number.toFixed(1) : '0.0'
}
function formatPercent(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return '—'
  const normalized = Math.abs(Number(value)) <= 1 ? Number(value) * 100 : Number(value)
  return `${normalized.toFixed(2)}%`
}
function formatDelta(after: number, before: number): string {
  const delta = Number(after) - Number(before)
  if (!Number.isFinite(delta) || delta === 0) return '0'
  return `${delta > 0 ? '+' : ''}${formatNumber(delta)}`
}
function formatDate(value: string | null | undefined): string {
  if (!value) return '—'
  return value.slice(0, 19).replace('T', ' ')
}
function rawValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return ''
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}
function fieldValue(payload: Record<string, unknown>, fields: string[]): string {
  const values = fields.map(field => rawValue(payload?.[field])).filter(Boolean)
  return values.length ? values.join(' / ') : ''
}
function normalizedText(value: string): string {
  return value.trim().replace(/\s+/g, ' ').toLocaleLowerCase()
}
function scoreAsPercent(score: unknown): number | null {
  const value = Number(score)
  if (!Number.isFinite(value)) return null
  return value <= 1 ? value * 100 : value
}
function comparisonKind(item: WorkbenchItem, candidate: Candidate, field: FieldDescriptor): ComparisonKind {
  const source = fieldValue(item.source_payload, field.sourceFields)
  const target = fieldValue(candidate.target_payload, field.targetFields)
  if (!source || !target) return 'empty'
  if (normalizedText(source) === normalizedText(target)) return 'exact'
  const fieldScore = candidate.field_scores?.find(score => score.rule_id === field.ruleId)
  const fieldPercent = scoreAsPercent(fieldScore?.score)
  if (fieldPercent !== null && fieldPercent >= 55) return 'partial'
  return 'different'
}
function comparisonLabel(kind: ComparisonKind): string {
  return ({ exact: '一致', partial: '部分一致', different: '不一致', empty: '无数据' } as Record<ComparisonKind, string>)[kind]
}
function statusLabel(status: string | undefined): string {
  return ({ MATCHED: '已自动匹配', REVIEW: '待人工匹配', CONFIRMED: '已人工匹配', UNMATCHED: '未匹配' } as Record<string, string>)[String(status ?? '')] ?? '未知状态'
}
function statusTagType(status: string | undefined): 'success' | 'warning' | 'info' | 'primary' {
  if (status === 'MATCHED') return 'success'
  if (status === 'REVIEW') return 'warning'
  if (status === 'CONFIRMED') return 'primary'
  return 'info'
}
function phaseLabel(phase: string | null | undefined): string {
  return ({ INDEX: '构建向量索引', RETRIEVE: '候选召回', RERANK: '逐条匹配评分', PERSIST: '结果持久化', DONE: '计算完成', WAITING: '等待调度', FAILED: '计算失败' } as Record<string, string>)[String(phase ?? '')] ?? '准备计算'
}
function runStatusLabel(status: string): string {
  return ({ RUNNING: '运行中', PREPARING: '准备中', RECOVERING: '恢复中', PENDING: '排队中', COMPLETED: '已完成', FAILED: '失败' } as Record<string, string>)[status] ?? status
}
function apiErrorMessage(error: any, fallback: string): string {
  return String(error?.message ?? error?.response?.data?.error?.message ?? fallback)
}
function candidatesFor(item: WorkbenchItem): Candidate[] {
  return (candidateMap.value[item.source_row_id] ?? item.candidates ?? []).slice(0, 5)
}
function candidateDisplayFields(candidate: Candidate): CandidateDisplayField[] {
  const selectedIds = new Set(selectedFieldIds.value)
  const ordered = [
    ...pageFieldDescriptors.value.filter(field => selectedIds.has(field.id)),
    ...pageFieldDescriptors.value.filter(field => !selectedIds.has(field.id)),
  ]
  const result: CandidateDisplayField[] = []
  const seen = new Set<string>()
  const code = normalizedText(candidate.target_group_code)
  const add = (id: string, label: string, value: string): void => {
    const normalized = normalizedText(value)
    if (!normalized || normalized === code || seen.has(normalized) || result.length >= 2) return
    seen.add(normalized)
    result.push({ id, label, value })
  }
  for (const field of ordered) {
    add(field.id, field.label, fieldValue(candidate.target_payload, field.targetFields))
    if (result.length >= 2) return result
  }
  for (const [key, value] of Object.entries(candidate.target_payload ?? {})) {
    add(`fallback:${key}`, key, rawValue(value))
    if (result.length >= 2) break
  }
  return result
}
function selectedCandidate(item: WorkbenchItem): Candidate | null {
  const selected = selectedByRow.value[item.source_row_id]
  if (!selected || selected === NONE_SELECTION) return candidatesFor(item)[0] ?? null
  return candidatesFor(item).find(candidate => candidate.target_group_code === selected) ?? candidatesFor(item)[0] ?? null
}
function selectedComparisonKind(item: WorkbenchItem, field: FieldDescriptor): ComparisonKind {
  const candidate = selectedCandidate(item)
  return candidate ? comparisonKind(item, candidate, field) : 'empty'
}
function selectedTargetValue(item: WorkbenchItem, field: FieldDescriptor): string {
  const candidate = selectedCandidate(item)
  return candidate ? fieldValue(candidate.target_payload, field.targetFields) : ''
}
function filterCount(key: StatusFilter): number {
  if (key === 'all') return totalRecords.value
  if (key === 'auto') return summary.value.automatic_matched
  if (key === 'review') return summary.value.pending_review
  if (key === 'confirmed') return summary.value.confirmed
  return summary.value.unmatched
}
function initialSelection(item: WorkbenchItem): string {
  if (item.current_status === 'UNMATCHED') return NONE_SELECTION
  if (item.final_group_code) return String(item.final_group_code)
  if (item.current_status === 'MATCHED' && item.top1_group_code) return String(item.top1_group_code)
  return ''
}
function mappingDescriptors(config: any): FieldDescriptor[] {
  const rules = Array.isArray(config?.rules) ? config.rules : []
  return rules.map((rule: any, index: number) => {
    const sourceFields = Array.isArray(rule?.source?.fields) ? rule.source.fields.map(String) : []
    const targetFields = Array.isArray(rule?.target?.fields) ? rule.target.fields.map(String) : []
    const sourceLabel = sourceFields.join(' / ') || '源字段'
    const targetLabel = targetFields.join(' / ') || '目标字段'
    return {
      id: `rule:${String(rule?.id ?? index)}`,
      label: sourceLabel === targetLabel ? sourceLabel : `${sourceLabel} ↔ ${targetLabel}`,
      sourceFields,
      targetFields,
      ruleId: String(rule?.id ?? index),
    }
  })
}
function syncFieldSelection(): void {
  const ids = pageFieldDescriptors.value.map(field => field.id)
  if (!fieldSelectionTouched.value) {
    selectedFieldIds.value = ids
    return
  }
  selectedFieldIds.value = selectedFieldIds.value.filter(id => ids.includes(id))
}
function onFieldSelectionChange(): void {
  fieldSelectionTouched.value = true
}
function clearSelection(): void {
  selectedRowIds.value = []
  selectAllFiltered.value = false
}
function onFilterChanged(): void {
  clearSelection()
  batchFeedback.value = null
  page.value = 1
  void loadItems(false)
}
function togglePageSelection(): void {
  if (allPageSelected.value) {
    const pageSet = new Set(currentPageIds.value)
    selectedRowIds.value = selectedRowIds.value.filter(id => !pageSet.has(id))
    selectAllFiltered.value = false
    return
  }
  selectedRowIds.value = [...new Set([...selectedRowIds.value, ...currentPageIds.value])]
  selectAllFiltered.value = false
}
function toggleRowSelection(sourceRowId: string, checked: boolean): void {
  selectAllFiltered.value = false
  if (checked) selectedRowIds.value = [...new Set([...selectedRowIds.value, sourceRowId])]
  else selectedRowIds.value = selectedRowIds.value.filter(id => id !== sourceRowId)
}
function onRowCheckboxChange(sourceRowId: string, value: string | number | boolean): void {
  toggleRowSelection(sourceRowId, Boolean(value))
}
function onPageChange(next: number): void {
  page.value = next
  clearSelection()
  void loadItems(false)
}
function onPageSizeChange(next: number): void {
  pageSize.value = next
  page.value = 1
  clearSelection()
  void loadItems(false)
}
function selectFilteredResults(): void {
  selectAllFiltered.value = true
  selectedRowIds.value = []
}
function currentSelection(): ReviewSelection {
  if (selectAllFiltered.value) return { mode: 'filter', filter: { ...currentFilter.value } }
  return { mode: 'explicit', source_row_ids: [...selectedRowIds.value] }
}
function histogramWidth(count: number): string {
  return `${Math.max(2, Math.round(count / maxHistogramCount.value * 100))}%`
}
function setComparisonPanelRef(sourceRowId: string, element: any): void {
  if (element instanceof HTMLElement) comparisonPanelRefs.set(sourceRowId, element)
  else comparisonPanelRefs.delete(sourceRowId)
}
async function revealComparisonPanel(sourceRowId: string): Promise<void> {
  await nextTick()
  const panel = comparisonPanelRefs.get(sourceRowId)
  if (!panel) return
  const wrap = panel.closest('.review-table-wrap') as HTMLElement | null
  if (!wrap) return
  const panelRect = panel.getBoundingClientRect()
  const wrapRect = wrap.getBoundingClientRect()
  const visibleTop = Math.max(wrapRect.top, 44)
  const visibleBottom = Math.min(wrapRect.bottom, window.innerHeight) - 12
  if (panelRect.top >= visibleTop && panelRect.bottom <= visibleBottom) return
  const delta = panelRect.top < visibleTop
    ? panelRect.top - visibleTop
    : Math.min(panelRect.top - visibleTop, panelRect.bottom - visibleBottom)
  if (Math.abs(delta) < 1) return
  if (wrap.scrollHeight > wrap.clientHeight + 1) wrap.scrollTop += delta
  else window.scrollBy(0, delta)
}

function normalizeCandidate(candidate: any): Candidate {
  return {
    rank: Number(candidate?.rank ?? 0),
    target_group_code: String(candidate?.target_group_code ?? candidate?.group_code ?? ''),
    target_row_number: candidate?.target_row_number === null || candidate?.target_row_number === undefined ? null : Number(candidate.target_row_number),
    score: Number(candidate?.score ?? 0),
    target_payload: candidate?.target_payload && typeof candidate.target_payload === 'object' ? candidate.target_payload : {},
    field_scores: Array.isArray(candidate?.field_scores) ? candidate.field_scores : [],
  }
}
function normalizeWorkbenchItem(item: any): WorkbenchItem {
  return {
    source_row_id: String(item?.source_row_id ?? ''),
    source_row_number: item?.source_row_number === null || item?.source_row_number === undefined ? null : Number(item.source_row_number),
    source_id: String(item?.source_id ?? ''),
    source_payload: item?.source_payload && typeof item.source_payload === 'object' ? item.source_payload : {},
    top1_group_code: item?.top1_group_code ? String(item.top1_group_code) : null,
    top1_score: Number(item?.top1_score ?? item?.first_score ?? 0),
    second_score: Number(item?.second_score ?? 0),
    score_gap: Number(item?.score_gap ?? 0),
    current_status: String(item?.current_status ?? item?.status ?? 'REVIEW'),
    original_status: item?.original_status ? String(item.original_status) : undefined,
    final_group_code: item?.final_group_code ? String(item.final_group_code) : null,
    candidates: Array.isArray(item?.candidates) ? item.candidates.map(normalizeCandidate).slice(0, 5) : undefined,
  }
}
function normalizeHistogram(value: any): HistogramBucket[] {
  if (!Array.isArray(value)) return []
  return value.map((item: any) => ({ min: Number(item?.min ?? 0), max: Number(item?.max ?? 0), count: Number(item?.count ?? 0) }))
}
function normalizeCounts(value: any, fallback: ReviewSummary) {
  return {
    matched: Number(value?.matched ?? value?.automatic_matched ?? fallback.automatic_matched),
    review: Number(value?.review ?? value?.pending_review ?? fallback.pending_review),
    unmatched: Number(value?.unmatched ?? fallback.unmatched),
    confirmed: Number(value?.confirmed ?? fallback.confirmed),
  }
}
function normalizeThresholdPreview(data: any): ThresholdPreview {
  const raw = data?.preview ?? data ?? {}
  const before = normalizeCounts(raw.before ?? raw.current_summary, summary.value)
  const after = normalizeCounts(raw.after ?? raw.resulting_summary ?? raw.summary, summary.value)
  const accuracyBeforeRaw = raw?.accuracy_before ?? raw?.before_accuracy ?? raw?.gold?.before_accuracy
  const accuracyAfterRaw = raw?.accuracy_after ?? raw?.after_accuracy ?? raw?.gold?.after_accuracy
  return {
    before,
    after,
    accuracyBefore: accuracyBeforeRaw === undefined ? null : Number(accuracyBeforeRaw),
    accuracyAfter: accuracyAfterRaw === undefined ? null : Number(accuracyAfterRaw),
  }
}
function normalizeImportFeedback(data: any): ImportFeedback {
  return {
    success: Number(data?.success_count ?? 0),
    skipped: Number(data?.skipped_count ?? 0),
    conflicts: Number(data?.conflict_count ?? 0),
    errors: Number(data?.error_count ?? 0),
    details: Array.isArray(data?.details) ? data.details : [],
  }
}

function stopPolling(): void {
  if (pollTimer) window.clearInterval(pollTimer)
  pollTimer = undefined
}
function startPollingIfNeeded(): void {
  stopPolling()
  if (consoleMode.value === 'waiting' && calculatingTask.value) pollTimer = window.setInterval(() => void refreshCalculatingProgress(), 3000)
}
async function loadReviewSummary(task: ReviewTask): Promise<ReviewTask> {
  try {
    const response = (await api.get(`/tasks/${task.id}/workbench/summary`)).data ?? {}
    return {
      ...task,
      summary: {
        pending_review: Number(response.pending_review ?? 0),
        confirmed: Number(response.confirmed ?? 0),
        unmatched: Number(response.unmatched ?? 0),
        automatic_matched: Number(response.automatic_matched ?? 0),
      },
      summaryError: false,
    }
  } catch {
    return { ...task, summaryError: true }
  }
}
async function refreshCalculatingProgress(): Promise<void> {
  const task = calculatingTask.value
  if (!task || progressRefreshing) return
  progressRefreshing = true
  try {
    const progressResponse = (await api.get(`/tasks/${task.id}/progress`)).data as ProgressState
    calculatingProgress.value = progressResponse
    task.progress = Number(progressResponse.progress ?? task.progress)
    if (!RUNNING_STATUSES.includes(String(progressResponse.status)) || String(progressResponse.stage) !== 'CALCULATE') await load()
  } catch {
    // 保留最后一次成功状态，下一轮轮询继续尝试。
  } finally {
    progressRefreshing = false
  }
}
async function refreshSummary(taskId: string): Promise<void> {
  const response = (await api.get(`/tasks/${taskId}/workbench/summary`)).data ?? {}
  summary.value = {
    pending_review: Number(response.pending_review ?? 0),
    confirmed: Number(response.confirmed ?? 0),
    unmatched: Number(response.unmatched ?? 0),
    automatic_matched: Number(response.automatic_matched ?? 0),
  }
  const row = reviewRows.value.find(item => item.id === taskId)
  if (row) row.summary = { ...summary.value }
}
async function loadCalibration(taskId: string, fallbackConfig?: any): Promise<void> {
  const fallbackDecision = fallbackConfig?.decision ?? {}
  const fallbackSuccess = Number(fallbackDecision.success_threshold ?? 88)
  try {
    const data = await fetchCalibrationStatistics(taskId)
    const current = data?.current ?? {}
    currentSuccessThreshold.value = Number(current.success_threshold ?? fallbackSuccess)
    draftSuccessThreshold.value = currentSuccessThreshold.value
    top1Histogram.value = normalizeHistogram(data?.top1_score_histogram)
    gapHistogram.value = normalizeHistogram(data?.top1_top2_gap_histogram)
  } catch (error) {
    currentSuccessThreshold.value = Number.isFinite(fallbackSuccess) ? fallbackSuccess : 88
    draftSuccessThreshold.value = currentSuccessThreshold.value
    top1Histogram.value = []
    gapHistogram.value = []
    ElMessage.warning(apiErrorMessage(error, '分数分布读取失败，仍可调整自动匹配阈值'))
  }
}
async function loadItems(resetPage = false, version = contextVersion): Promise<void> {
  const taskId = activeTaskId.value
  if (!taskId) return
  if (resetPage) page.value = 1
  listLoading.value = true
  candidateError.value = {}
  try {
    const response = await fetchWorkbenchPage(taskId, currentFilter.value, page.value, pageSize.value)
    if (version !== contextVersion || activeTaskId.value !== taskId) return
    const items = (Array.isArray(response.items) ? response.items : []).map(normalizeWorkbenchItem)
    workbenchItems.value = items
    workbenchTotal.value = Number(response.total ?? 0)
    const nextMap: Record<string, Candidate[]> = {}
    const nextSelected = { ...selectedByRow.value }
    for (const item of items) {
      if (item.candidates?.length) nextMap[item.source_row_id] = item.candidates
      if (!(item.source_row_id in nextSelected)) nextSelected[item.source_row_id] = initialSelection(item)
    }
    candidateMap.value = nextMap
    selectedByRow.value = nextSelected
    syncFieldSelection()
    const lastPage = Math.max(1, Math.ceil(workbenchTotal.value / pageSize.value))
    if (page.value > lastPage) {
      page.value = lastPage
      await loadItems(false, version)
    }
  } catch (error) {
    if (version === contextVersion) ElMessage.error(apiErrorMessage(error, '人工匹配工作台读取失败'))
  } finally {
    if (version === contextVersion) listLoading.value = false
  }
}
async function loadWorkbenchContext(taskId: string): Promise<void> {
  if (!taskId) return
  const version = ++contextVersion
  activeTaskId.value = taskId
  page.value = 1
  selectedByRow.value = {}
  candidateMap.value = {}
  expandedRows.value = {}
  comparisonPanelRefs.clear()
  fieldSelectionTouched.value = false
  thresholdPreview.value = null
  thresholdPreviewSignature.value = ''
  importFeedback.value = null
  clearSelection()
  try {
    const [taskResponse] = await Promise.all([
      api.get(`/tasks/${taskId}`),
      refreshSummary(taskId),
    ])
    if (version !== contextVersion) return
    const detail = taskResponse.data ?? {}
    mappingRules.value = mappingDescriptors(detail?.config_snapshot ?? {})
    await Promise.all([
      loadCalibration(taskId, detail?.config_snapshot ?? {}),
      loadItems(false, version),
    ])
  } catch (error) {
    if (version === contextVersion) ElMessage.error(apiErrorMessage(error, '人工匹配工作台加载失败'))
  }
}
async function load(): Promise<void> {
  if (loading.value) return
  loading.value = true
  loadError.value = ''
  stopPolling()
  try {
    const tasks = ((await api.get('/tasks')).data ?? [])
      .map((task: any) => normalizeTask(task))
      .sort((a: ReviewTask, b: ReviewTask) => b.created_at.localeCompare(a.created_at))
    const candidates = tasks.filter((task: ReviewTask) => task.status === 'COMPLETED' && ['REVIEW', 'RESULT'].includes(task.stage))
    reviewRows.value = await Promise.all(candidates.map((task: ReviewTask) => loadReviewSummary(task)))
    calculatingTask.value = tasks.find((task: ReviewTask) => task.stage === 'CALCULATE' && RUNNING_STATUSES.includes(task.status)) ?? null
    latestFailed.value = tasks.find((task: ReviewTask) => task.status === 'FAILED') ?? null
    calculatingProgress.value = null
    const requestedTaskId = typeof route.query.task === 'string' ? route.query.task : ''
    const requested = workspaceTasks.value.find(task => task.id === requestedTaskId)
    const preserved = workspaceTasks.value.find(task => task.id === activeTaskId.value)
    const nextTask = requested ?? preserved ?? workspaceTasks.value[0] ?? null
    activeTaskId.value = nextTask?.id ?? ''
    if (nextTask) await loadWorkbenchContext(nextTask.id)
    else {
      ++contextVersion
      workbenchItems.value = []
      workbenchTotal.value = 0
      candidateMap.value = {}
      summary.value = { pending_review: 0, confirmed: 0, unmatched: 0, automatic_matched: 0 }
      if (calculatingTask.value && !hasUnknownReviewState.value) await refreshCalculatingProgress()
    }
  } catch (error) {
    reviewRows.value = []
    activeTaskId.value = ''
    calculatingTask.value = null
    calculatingProgress.value = null
    latestFailed.value = null
    loadError.value = apiErrorMessage(error, '第三步状态读取失败')
  } finally {
    loading.value = false
    startPollingIfNeeded()
  }
}
async function selectTask(taskId: string): Promise<void> {
  const task = workspaceTasks.value.find(row => row.id === taskId)
  if (!task) return
  await router.replace({ path: '/review', query: { task: task.id } })
  await loadWorkbenchContext(task.id)
}
function openTask(task: ReviewTask): void {
  void router.push(`/tasks/${task.id}`)
}
async function ensureCandidates(item: WorkbenchItem): Promise<void> {
  if (candidatesFor(item).length || candidateLoading.value[item.source_row_id]) return
  candidateLoading.value = { ...candidateLoading.value, [item.source_row_id]: true }
  candidateError.value = { ...candidateError.value, [item.source_row_id]: false }
  try {
    const rows = await fetchCandidates(activeTaskId.value, item.source_row_id)
    candidateMap.value = { ...candidateMap.value, [item.source_row_id]: rows.map(normalizeCandidate).slice(0, 5) }
    syncFieldSelection()
  } catch (error) {
    candidateError.value = { ...candidateError.value, [item.source_row_id]: true }
    ElMessage.error(apiErrorMessage(error, 'Top 5 候选读取失败'))
  } finally {
    candidateLoading.value = { ...candidateLoading.value, [item.source_row_id]: false }
  }
}
async function toggleCandidates(item: WorkbenchItem): Promise<void> {
  const next = !expandedRows.value[item.source_row_id]
  expandedRows.value = { ...expandedRows.value, [item.source_row_id]: next }
  if (next) {
    await ensureCandidates(item)
    await revealComparisonPanel(item.source_row_id)
  }
}
async function setSelectedValue(item: WorkbenchItem, value: string): Promise<void> {
  selectedByRow.value = { ...selectedByRow.value, [item.source_row_id]: value }
  expandedRows.value = { ...expandedRows.value, [item.source_row_id]: true }
  await revealComparisonPanel(item.source_row_id)
}
async function applyRowSelection(item: WorkbenchItem): Promise<void> {
  const selected = selectedByRow.value[item.source_row_id]
  if (!selected) return
  mutationBusyRow.value = item.source_row_id
  try {
    if (selected === NONE_SELECTION) {
      await api.post(`/tasks/${activeTaskId.value}/items/${item.source_row_id}/reject`, { comment: '' })
      ElMessage.success('已标记均不匹配')
    } else {
      await api.post(`/tasks/${activeTaskId.value}/items/${item.source_row_id}/confirm`, { target_id: selected, comment: '' })
      ElMessage.success(`已匹配到 ${selected}`)
    }
    await Promise.all([refreshSummary(activeTaskId.value), loadItems(false)])
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '人工匹配操作失败'))
  } finally {
    mutationBusyRow.value = ''
  }
}
async function restoreRow(item: WorkbenchItem): Promise<void> {
  mutationBusyRow.value = item.source_row_id
  try {
    await api.post(`/tasks/${activeTaskId.value}/items/${item.source_row_id}/cancel`, { comment: '' })
    ElMessage.success('已恢复原结果')
    await Promise.all([refreshSummary(activeTaskId.value), loadItems(false)])
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '恢复原结果失败'))
  } finally {
    mutationBusyRow.value = ''
  }
}
async function runBatch(action: ReviewBatchAction): Promise<void> {
  if (!activeTaskId.value || !hasSelection.value) return
  const actionLabel: Record<ReviewBatchAction, string> = {
    confirm_top1: '确认第一候选',
    mark_unmatched: '标记均不匹配',
    cancel_manual_match: '取消人工匹配',
    restore_original: '恢复原结果',
  }
  try {
    await ElMessageBox.confirm(
      `将对 ${formatNumber(selectionCount.value)} 条记录执行“${actionLabel[action]}”。本次只确认一次，不会逐条弹窗。`,
      '批量操作确认',
      { confirmButtonText: '确认执行', cancelButtonText: '取消', type: 'warning' },
    )
  } catch {
    return
  }
  batchBusy.value = true
  batchFeedback.value = null
  try {
    const result = await runReviewBatch(activeTaskId.value, action, currentSelection())
    batchFeedback.value = {
      success: result.success_count,
      failed: result.failed_count,
      conflicts: result.conflict_count,
      details: result.details,
    }
    clearSelection()
    await Promise.all([refreshSummary(activeTaskId.value), loadItems(false)])
    ElMessage.success(`批量操作完成：成功 ${result.success_count} 条`)
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '批量操作失败'))
  } finally {
    batchBusy.value = false
  }
}
function invalidateThresholdPreview(): void {
  if (thresholdPreviewSignature.value !== currentPreviewSignature.value) thresholdPreview.value = null
}
async function previewThreshold(): Promise<void> {
  if (!activeTaskId.value || !thresholdValid.value) return
  previewBusy.value = true
  try {
    const data = await reDecideSingleThreshold(activeTaskId.value, draftSuccessThreshold.value, 'preview')
    thresholdPreview.value = normalizeThresholdPreview(data)
    thresholdPreviewSignature.value = currentPreviewSignature.value
  } catch (error) {
    thresholdPreview.value = null
    thresholdPreviewSignature.value = ''
    ElMessage.error(apiErrorMessage(error, '自动匹配阈值影响预览失败'))
  } finally {
    previewBusy.value = false
  }
}
async function applyThreshold(): Promise<void> {
  if (!activeTaskId.value || !canApplyThreshold.value) return
  try {
    await ElMessageBox.confirm(
      `自动匹配阈值 ${currentSuccessThreshold.value} → ${draftSuccessThreshold.value}。未达到阈值但有可用候选的记录将交给人工处理。`,
      '应用自动匹配阈值',
      { confirmButtonText: '确认应用', cancelButtonText: '取消', type: 'warning' },
    )
  } catch {
    return
  }
  applyBusy.value = true
  try {
    await reDecideSingleThreshold(activeTaskId.value, draftSuccessThreshold.value, 'apply')
    currentSuccessThreshold.value = draftSuccessThreshold.value
    thresholdPreview.value = null
    thresholdPreviewSignature.value = ''
    clearSelection()
    await Promise.all([refreshSummary(activeTaskId.value), loadCalibration(activeTaskId.value), loadItems(true)])
    ElMessage.success('自动匹配阈值已应用')
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '应用自动匹配阈值失败'))
  } finally {
    applyBusy.value = false
  }
}
function startManualUpload(): void {
  importInput.value?.click()
}
async function onManualUpload(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file || !activeTaskId.value) return
  importBusy.value = true
  importFeedback.value = null
  try {
    const data = await uploadManualWorkbook(activeTaskId.value, file)
    importFeedback.value = normalizeImportFeedback(data)
    await Promise.all([refreshSummary(activeTaskId.value), loadItems(true)])
    ElMessage.success('人工匹配结果已处理')
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '上传人工匹配结果失败'))
  } finally {
    importBusy.value = false
  }
}

onMounted(() => void load())
onBeforeUnmount(() => {
  stopPolling()
  comparisonPanelRefs.clear()
  ++contextVersion
})
</script>

<template>
  <div class="review-page">
    <div class="toolbar review-toolbar">
      <div>
        <h2>第三步 · 人工调整</h2>
        <p>批量处理大多数记录，只对少量真正需要判断的数据展开 Top 1～Top 5。</p>
      </div>
      <div class="review-toolbar-actions">
        <el-select v-if="workspaceTasks.length > 1" :model-value="activeTaskId" class="review-task-switcher" placeholder="切换方案" @change="selectTask">
          <el-option v-for="taskRow in workspaceTasks" :key="taskRow.id" :label="`${taskRow.scheme_name} · ${formatNumber(taskRow.summary?.pending_review)} 条待人工`" :value="taskRow.id" />
        </el-select>
        <template v-if="activeTaskId">
          <el-button @click="downloadManualWorkbook(activeTaskId)">下载人工匹配 Excel</el-button>
          <el-button :loading="importBusy" @click="startManualUpload">上传人工匹配结果</el-button>
          <input ref="importInput" class="review-hidden-file" type="file" accept=".xlsx,.xlsm" @change="onManualUpload" />
        </template>
        <el-button :loading="loading" @click="load">刷新</el-button>
      </div>
    </div>

    <section v-if="consoleMode !== 'ready'" class="review-console" :class="`is-${consoleMode}`" aria-live="polite">
      <template v-if="consoleMode === 'waiting' && calculatingTask">
        <div class="review-console-main">
          <div class="review-console-kicker"><span class="review-status-dot"></span>第二步计算进行中</div>
          <h3>等待匹配计算完成</h3>
          <p>方案「{{ calculatingTask.scheme_name }}」仍在计算，完成后会自动进入人工调整。</p>
          <div class="review-console-meta">
            <span>开始时间 {{ formatDate(calculatingTask.started_at ?? calculatingTask.created_at) }}</span>
            <span>{{ phaseLabel(calculatingProgress?.current_phase) }}</span>
            <span>{{ runStatusLabel(calculatingProgress?.status ?? calculatingTask.status) }}</span>
            <span v-if="waitingTotal > 0">已处理 {{ formatNumber(waitingProcessed) }} / {{ formatNumber(waitingTotal) }} 行</span>
          </div>
        </div>
        <div class="review-wait-progress">
          <div class="review-wait-percent"><b>{{ waitingPercent }}%</b><span>计算进度</span></div>
          <el-progress :percentage="waitingPercent" :stroke-width="10" :show-text="false" />
        </div>
        <div class="review-console-action"><el-button type="primary" plain size="large" @click="openTask(calculatingTask)">查看计算进度</el-button></div>
      </template>
      <template v-else-if="consoleMode === 'error'">
        <div class="review-console-main">
          <div class="review-console-kicker"><span class="review-status-dot"></span>状态读取异常</div>
          <h3>暂时无法读取人工调整数据</h3>
          <p>{{ loadError || '部分方案汇总读取失败，请重试。' }}</p>
        </div>
        <div class="review-console-action"><el-button type="primary" :loading="loading" @click="load">重新读取</el-button></div>
      </template>
      <template v-else>
        <div class="review-console-main">
          <div class="review-console-kicker"><span class="review-status-dot"></span>暂无可调整方案</div>
          <h3>当前没有可进入人工调整的匹配结果</h3>
          <p>请先完成第二步匹配计算；已有最终结果的方案可前往第四步查看。</p>
          <div v-if="latestFailed" class="review-failure-note"><b>最近失败方案：{{ latestFailed.scheme_name }}</b><span>{{ latestFailed.error_message || latestFailed.error_code || '计算失败' }}</span></div>
        </div>
        <div class="review-console-action review-empty-actions">
          <el-button type="primary" size="large" @click="router.push('/tasks')">前往第二步</el-button>
          <el-button size="large" @click="router.push('/results')">查看第四步</el-button>
        </div>
      </template>
    </section>

    <template v-if="consoleMode === 'ready' && activeTask">
      <section class="review-task-hero">
        <div>
          <div class="review-section-kicker">方案名称 · {{ activeTask.scheme_name }}</div>
          <h3>先筛选和批量处理，再展开少量需要判断的记录</h3>
          <p>列表只请求当前页，状态、搜索、分数范围和分页都交给服务端处理；不会生成十万行 Vue DOM，也不会一次加载全量候选。</p>
        </div>
        <div class="review-task-hero-meta">
          <span>开始时间 {{ formatDate(activeTask.started_at ?? activeTask.created_at) }}</span>
          <span>计算完成 {{ formatDate(activeTask.finished_at) }}</span>
        </div>
      </section>

      <section class="review-metric-grid" aria-label="匹配状态汇总">
        <button class="review-metric-card" @click="statusFilter = 'all'; onFilterChanged()"><span>全部</span><b>{{ formatNumber(totalRecords) }}</b><small>全部记录</small></button>
        <button class="review-metric-card is-success" @click="statusFilter = 'auto'; onFilterChanged()"><span>已自动匹配</span><b>{{ formatNumber(summary.automatic_matched) }}</b><small>系统自动完成</small></button>
        <button class="review-metric-card is-warning" @click="statusFilter = 'review'; onFilterChanged()"><span>待人工匹配</span><b>{{ formatNumber(summary.pending_review) }}</b><small>需要人工处理</small></button>
        <button class="review-metric-card is-primary" @click="statusFilter = 'confirmed'; onFilterChanged()"><span>已人工匹配</span><b>{{ formatNumber(summary.confirmed) }}</b><small>可以继续复查</small></button>
        <button class="review-metric-card" @click="statusFilter = 'unmatched'; onFilterChanged()"><span>未匹配</span><b>{{ formatNumber(summary.unmatched) }}</b><small>当前没有匹配结果</small></button>
      </section>

      <section v-if="importFeedback" class="review-import-feedback">
        <div class="review-feedback-head">
          <div><strong>人工匹配 Excel 上传结果</strong><span>已按服务端审计结果处理；冲突不会被静默覆盖。</span></div>
          <el-button link @click="importFeedback = null">关闭</el-button>
        </div>
        <div class="review-import-grid">
          <div><span>成功</span><b>{{ formatNumber(importFeedback.success) }}</b></div>
          <div><span>跳过</span><b>{{ formatNumber(importFeedback.skipped) }}</b></div>
          <div><span>冲突</span><b>{{ formatNumber(importFeedback.conflicts) }}</b></div>
          <div><span>错误</span><b>{{ formatNumber(importFeedback.errors) }}</b></div>
        </div>
        <details v-if="importFeedback.details.length"><summary>展开查看冲突与错误明细</summary><p v-for="(detail, index) in importFeedback.details" :key="index" class="review-feedback-line">{{ detail.message || detail.code || JSON.stringify(detail) }}</p></details>
      </section>

      <section class="review-strategy-card">
        <div class="review-strategy-head">
          <div>
            <div class="review-section-kicker">全局判定调参</div>
            <h3>只调整自动匹配阈值，其余有候选记录交给人工</h3>
            <p>达到自动匹配阈值的记录由系统自动完成；未达到但有可用候选的记录进入人工处理。预览只使用已落库分数，不重新向量化、召回或评分。</p>
          </div>
          <div class="review-current-thresholds">
            <span>当前自动匹配阈值 <b>{{ currentSuccessThreshold }}</b></span>
          </div>
        </div>
        <div class="review-threshold-editor-grid">
          <div>
            <div class="review-threshold-label"><span>自动匹配阈值</span><b>{{ draftSuccessThreshold }}</b></div>
            <el-slider v-model="draftSuccessThreshold" :min="1" :max="100" :step="1" @input="invalidateThresholdPreview" />
          </div>
          <div class="review-threshold-actions">
            <el-button type="primary" plain :loading="previewBusy" :disabled="!thresholdDirty || !thresholdValid" @click="previewThreshold">预览影响</el-button>
            <el-button type="primary" :loading="applyBusy" :disabled="!canApplyThreshold" @click="applyThreshold">应用新阈值</el-button>
          </div>
        </div>
        <div v-if="!thresholdValid" class="review-threshold-error">自动匹配阈值需在 1～100 之间。</div>
        <div class="review-threshold-preview">
          <div class="review-current-after-grid">
            <div><span>状态</span><b>当前</b><b>调整后</b><b>变化</b></div>
            <div><span>预计自动匹配</span><b>{{ formatNumber(thresholdPreview?.before.matched ?? summary.automatic_matched) }}</b><b>{{ thresholdPreview ? formatNumber(thresholdPreview.after.matched) : '—' }}</b><b>{{ thresholdPreview ? formatDelta(thresholdPreview.after.matched, thresholdPreview.before.matched) : '—' }}</b></div>
            <div><span>预计需要人工处理</span><b>{{ formatNumber(thresholdPreview?.before.review ?? summary.pending_review) }}</b><b>{{ thresholdPreview ? formatNumber(thresholdPreview.after.review) : '—' }}</b><b>{{ thresholdPreview ? formatDelta(thresholdPreview.after.review, thresholdPreview.before.review) : '—' }}</b></div>
            <div><span>无可用候选 / 未匹配</span><b>{{ formatNumber(thresholdPreview?.before.unmatched ?? summary.unmatched) }}</b><b>{{ thresholdPreview ? formatNumber(thresholdPreview.after.unmatched) : '—' }}</b><b>{{ thresholdPreview ? formatDelta(thresholdPreview.after.unmatched, thresholdPreview.before.unmatched) : '—' }}</b></div>
          </div>
          <div class="review-histogram-grid">
            <div class="review-histogram-card">
              <div class="review-histogram-head"><b>Top1 分数分布</b><span>0-10 ... 90-100</span></div>
              <div v-if="top1Histogram.length" class="review-histogram">
                <div v-for="bucket in top1Histogram" :key="bucket.min" class="review-histogram-row"><span>{{ bucket.min }}-{{ bucket.max }}</span><div><i :style="{ width: histogramWidth(bucket.count) }"></i></div><b>{{ formatNumber(bucket.count) }}</b></div>
              </div>
              <div v-else class="review-histogram-empty">当前后端未返回分数分布。</div>
            </div>
            <div class="review-histogram-card">
              <div class="review-histogram-head"><b>Top1 / Top2 分差分布</b><span>Top1 score - Top2 score</span></div>
              <div v-if="gapHistogram.length" class="review-histogram">
                <div v-for="bucket in gapHistogram" :key="bucket.min" class="review-histogram-row"><span>{{ bucket.min }}-{{ bucket.max }}</span><div><i :style="{ width: histogramWidth(bucket.count) }"></i></div><b>{{ formatNumber(bucket.count) }}</b></div>
              </div>
              <div v-else class="review-histogram-empty">当前后端未返回分差分布。</div>
            </div>
          </div>
          <div v-if="thresholdPreview && thresholdPreview.accuracyBefore != null && thresholdPreview.accuracyAfter != null" class="review-gold-card"><span>金标实测准确率</span><b>{{ formatPercent(thresholdPreview?.accuracyBefore) }} → {{ formatPercent(thresholdPreview?.accuracyAfter) }}</b></div>
          <div v-else class="review-gold-card"><span>未检测到可用于本次阈值预览的金标准确率数据，因此这里只展示数量变化。</span></div>
        </div>
      </section>

      <section class="panel review-workbench-panel">
        <div class="review-workbench-head">
          <div>
            <div class="review-section-kicker">在线人工匹配</div>
            <h3>服务端筛选 + 批量处理 + 行内 Top 5</h3>
            <p>字段对比统一使用：一致 / 部分一致 / 不一致 / 无数据；浅绿、浅黄、浅红、浅灰与文字状态同时出现。</p>
          </div>
          <div class="review-field-actions">
            <el-select v-model="selectedFieldIds" multiple collapse-tags collapse-tags-tooltip class="review-field-select" placeholder="列显示设置" @change="onFieldSelectionChange">
              <el-option v-for="field in pageFieldDescriptors" :key="field.id" :label="field.label" :value="field.id" />
            </el-select>
            <el-button @click="showAllFields = !showAllFields">{{ showAllFields ? '收起字段' : '展开全部字段' }}</el-button>
          </div>
        </div>

        <div class="review-status-tabs" role="tablist" aria-label="状态筛选">
          <button v-for="tab in STATUS_TABS" :key="tab.key" type="button" class="review-status-tab" :class="{ 'is-active': statusFilter === tab.key }" @click="statusFilter = tab.key; onFilterChanged()"><span>{{ tab.label }}</span><b>{{ formatNumber(filterCount(tab.key)) }}</b></button>
        </div>

        <div class="review-filter-row">
          <el-input v-model="searchQ" class="review-search-box" clearable placeholder="搜索源物料、源数据或集团码" @keyup.enter="onFilterChanged" @clear="onFilterChanged" />
          <div class="review-score-filter"><span>第一候选分</span><el-input-number v-model="scoreMin" :min="0" :max="100" :controls="false" placeholder="最低" /><span>—</span><el-input-number v-model="scoreMax" :min="0" :max="100" :controls="false" placeholder="最高" /><el-button @click="onFilterChanged">筛选</el-button></div>
          <span class="review-server-note">当前筛选 {{ formatNumber(workbenchTotal) }} 条 · server-side</span>
        </div>

        <div class="review-bulk-bar" :class="{ 'has-selection': hasSelection }">
          <div class="review-bulk-select">
            <el-checkbox :model-value="selectAllFiltered || allPageSelected" :indeterminate="selectedExplicitCount > 0 && !allPageSelected && !selectAllFiltered" @change="togglePageSelection">全选本页</el-checkbox>
            <strong v-if="selectAllFiltered">已选择当前筛选出的全部 {{ formatNumber(workbenchTotal) }} 条</strong>
            <strong v-else-if="selectedExplicitCount">已选择本页 {{ formatNumber(selectedExplicitCount) }} 条</strong>
            <span v-else>可先全选本页，再扩展到当前筛选全部结果</span>
            <el-button v-if="allPageSelected && workbenchTotal > currentPageIds.length && !selectAllFiltered" link type="primary" @click="selectFilteredResults">选择当前筛选出的全部 {{ formatNumber(workbenchTotal) }} 条</el-button>
          </div>
          <div class="review-bulk-actions">
            <el-button size="small" :disabled="!hasSelection" :loading="batchBusy" @click="runBatch('confirm_top1')">确认第一候选</el-button>
            <el-button size="small" :disabled="!hasSelection" :loading="batchBusy" @click="runBatch('mark_unmatched')">标记均不匹配</el-button>
            <el-button size="small" :disabled="!hasSelection" :loading="batchBusy" @click="runBatch('cancel_manual_match')">取消人工匹配</el-button>
            <el-button size="small" :disabled="!hasSelection" :loading="batchBusy" @click="runBatch('restore_original')">恢复原结果</el-button>
            <el-button size="small" :disabled="!hasSelection" @click="clearSelection">清除选择</el-button>
          </div>
        </div>

        <div v-if="batchFeedback" class="review-batch-feedback">
          <div><strong>批量操作结果</strong><span>成功 {{ formatNumber(batchFeedback.success) }} · 失败 {{ formatNumber(batchFeedback.failed) }} · 冲突 {{ formatNumber(batchFeedback.conflicts) }}</span></div>
          <details v-if="batchFeedback.details.length"><summary>查看并发冲突 / 失败明细</summary><p v-for="(detail, index) in batchFeedback.details" :key="index">{{ detail.message || detail.code || JSON.stringify(detail) }}</p></details>
        </div>

        <div v-loading="listLoading" class="review-table-wrap">
          <table class="review-data-table">
            <thead>
              <tr>
                <th class="review-check-col">选择</th>
                <th class="review-source-col">源物料</th>
                <th class="review-core-fields">当前显示字段</th>
                <th class="review-score-col">Top1</th>
                <th class="review-candidates-col">Top 1～Top 5</th>
                <th class="review-action-col">操作</th>
              </tr>
            </thead>
            <tbody>
              <template v-for="item in workbenchItems" :key="item.source_row_id">
                <tr>
                  <td class="review-check-col"><el-checkbox :model-value="selectAllFiltered || selectedRowIds.includes(item.source_row_id)" @change="onRowCheckboxChange(item.source_row_id, $event)" /></td>
                  <td class="review-source-col">
                    <el-tag size="small" :type="statusTagType(item.current_status)">{{ statusLabel(item.current_status) }}</el-tag>
                    <strong :title="item.source_id">{{ item.source_id || '未命名源物料' }}</strong>
                    <span v-if="item.source_row_number">源 Excel 第 {{ item.source_row_number }} 行</span>
                    <div class="review-current-result">{{ item.final_group_code || (item.current_status === 'MATCHED' ? item.top1_group_code : '') || '—' }}</div>
                  </td>
                  <td class="review-core-fields">
                    <div v-for="field in coreVisibleFields" :key="field.id"><span :title="field.label">{{ field.label }}</span><b :title="fieldValue(item.source_payload, field.sourceFields) || '无数据'">{{ fieldValue(item.source_payload, field.sourceFields) || '—' }}</b></div>
                    <small v-if="!coreVisibleFields.length">暂无可显示字段</small>
                  </td>
                  <td class="review-score-col"><b>{{ formatScore(item.top1_score) }}</b><span>分差 {{ formatScore(item.score_gap) }}</span></td>
                  <td class="review-candidates-col">
                    <div v-if="candidatesFor(item).length" class="review-candidate-buttons">
                      <button v-for="candidate in candidatesFor(item)" :key="candidate.rank" type="button" :class="{ 'is-selected': selectedByRow[item.source_row_id] === candidate.target_group_code }" @click="setSelectedValue(item, candidate.target_group_code)">
                        <span class="review-candidate-topline"><span>Top {{ candidate.rank }}</span><small>{{ formatScore(candidate.score) }} 分</small></span>
                        <b class="review-candidate-code" :title="candidate.target_group_code">{{ candidate.target_group_code || '—' }}</b>
                        <span v-for="field in candidateDisplayFields(candidate)" :key="field.id" class="review-candidate-meta" :title="`${field.label}：${field.value}`"><em>{{ field.label }}</em><i>{{ field.value }}</i></span>
                      </button>
                      <button type="button" class="is-none" :class="{ 'is-selected': selectedByRow[item.source_row_id] === NONE_SELECTION }" @click="setSelectedValue(item, NONE_SELECTION)"><span>无匹配</span><b>均不匹配</b><small>不选 Top5</small></button>
                    </div>
                    <div v-else class="review-lazy-candidates">
                      <el-button link type="primary" :loading="candidateLoading[item.source_row_id]" @click="toggleCandidates(item)">查看 Top 1～Top 5</el-button>
                      <span v-if="candidateError[item.source_row_id]">候选读取失败，可重试</span>
                    </div>
                  </td>
                  <td class="review-action-col">
                    <div class="review-row-actions">
                      <el-button link type="primary" :loading="candidateLoading[item.source_row_id]" @click="toggleCandidates(item)">{{ expandedRows[item.source_row_id] ? '收起对比' : '字段对比' }}</el-button>
                      <el-button link type="primary" :disabled="!selectedByRow[item.source_row_id]" :loading="mutationBusyRow === item.source_row_id" @click="applyRowSelection(item)">确认</el-button>
                      <el-button v-if="item.current_status === 'CONFIRMED' || item.current_status === 'UNMATCHED'" link type="info" :loading="mutationBusyRow === item.source_row_id" @click="restoreRow(item)">恢复原结果</el-button>
                    </div>
                  </td>
                </tr>
                <tr v-if="expandedRows[item.source_row_id]" class="review-expanded-row">
                  <td colspan="6">
                    <div v-if="candidateLoading[item.source_row_id]" class="review-inline-loading">正在加载 Top 5 候选…</div>
                    <div v-else-if="selectedCandidate(item)" :ref="element => setComparisonPanelRef(item.source_row_id, element)" class="review-expanded-card">
                      <div class="review-expanded-head"><div><strong>当前对比：{{ selectedCandidate(item)?.target_group_code }}</strong><span v-if="selectedCandidate(item)?.target_row_number">目标 Excel 第 {{ selectedCandidate(item)?.target_row_number }} 行</span></div><span>字段状态：一致 / 部分一致 / 不一致 / 无数据</span></div>
                      <div class="review-comparison-scroll">
                        <table class="review-comparison-table">
                          <thead><tr><th>字段</th><th>源物料</th><th>候选</th><th>状态</th></tr></thead>
                          <tbody>
                            <tr v-for="field in visibleFieldDescriptors" :key="field.id">
                              <th>{{ field.label }}</th>
                              <td>{{ fieldValue(item.source_payload, field.sourceFields) || '—' }}</td>
                              <td :class="`is-${selectedComparisonKind(item, field)}`"><span>{{ selectedTargetValue(item, field) || '—' }}</span><small>{{ comparisonLabel(selectedComparisonKind(item, field)) }}</small></td>
                              <td :class="`is-${selectedComparisonKind(item, field)}`"><strong>{{ comparisonLabel(selectedComparisonKind(item, field)) }}</strong></td>
                            </tr>
                          </tbody>
                        </table>
                      </div>
                    </div>
                    <div v-else class="review-histogram-empty">Top 5 当前为空；可以标记均不匹配。</div>
                  </td>
                </tr>
              </template>
            </tbody>
          </table>
          <el-empty v-if="!listLoading && !workbenchItems.length" :description="`${STATUS_TABS.find(tab => tab.key === statusFilter)?.label ?? '当前'}筛选下暂无记录`" :image-size="72" />
        </div>

        <div class="review-pagination-row">
          <span>只渲染当前页；每页 {{ pageSize }} 条</span>
          <el-pagination background layout="total, sizes, prev, pager, next" :total="workbenchTotal" :current-page="page" :page-size="pageSize" :page-sizes="PAGE_SIZE_OPTIONS" @current-change="onPageChange" @size-change="onPageSizeChange" />
        </div>
      </section>
    </template>

    <section class="panel review-list-panel">
      <div class="section-head"><div><h3>可人工调整的方案</h3><p class="review-section-desc">可切换其它已完成匹配计算的方案。</p></div></div>
      <el-table v-if="reviewRows.length" :data="reviewRows" size="default">
        <el-table-column label="方案名称" min-width="220"><template #default="scope"><a class="row-link" @click="openTask(scope.row)">{{ scope.row.scheme_name }}</a><div class="row-sub">开始 {{ formatDate(scope.row.started_at ?? scope.row.created_at) }}</div></template></el-table-column>
        <el-table-column label="自动匹配" width="110"><template #default="scope">{{ scope.row.summaryError ? '—' : formatNumber(scope.row.summary?.automatic_matched) }}</template></el-table-column>
        <el-table-column label="待人工" width="100"><template #default="scope">{{ scope.row.summaryError ? '—' : formatNumber(scope.row.summary?.pending_review) }}</template></el-table-column>
        <el-table-column label="已人工" width="100"><template #default="scope">{{ scope.row.summaryError ? '—' : formatNumber(scope.row.summary?.confirmed) }}</template></el-table-column>
        <el-table-column label="未匹配" width="100"><template #default="scope">{{ scope.row.summaryError ? '—' : formatNumber(scope.row.summary?.unmatched) }}</template></el-table-column>
        <el-table-column label="计算完成" width="170"><template #default="scope">{{ formatDate(scope.row.finished_at) }}</template></el-table-column>
        <el-table-column label="操作" width="130"><template #default="scope"><el-button v-if="workspaceTasks.some(task => task.id === scope.row.id)" link type="primary" @click="selectTask(scope.row.id)">进入工作台</el-button><el-button v-else link type="info" @click="openTask(scope.row)">查看详情</el-button></template></el-table-column>
      </el-table>
      <el-empty v-else description="暂无已完成匹配计算的方案" :image-size="72" />
    </section>
  </div>
</template>
