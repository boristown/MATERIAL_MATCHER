<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '../api'
import '../styles/pages/review.css'

type ReviewSummary = {
  pending_review: number
  confirmed: number
  unmatched: number
  automatic_matched: number
}

type ReviewTask = {
  id: string
  name: string
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
  source_value?: string
  target_value?: string
}

type Candidate = {
  rank: number
  target_group_code: string
  target_row_number?: number | null
  score: number
  target_payload: Record<string, unknown>
  field_scores?: FieldScore[]
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

type ThresholdPreview = {
  addedAutomatic: number
  remainingManual: number
  unmatched: number
}

const route = useRoute()
const router = useRouter()
const RUNNING_STATUSES = ['RUNNING', 'PREPARING', 'RECOVERING', 'PENDING']
const PAGE_SIZE_OPTIONS = [10, 20, 50]
const NONE_SELECTION = '__NONE__'
const STATUS_TABS: Array<{ key: StatusFilter; label: string; backend?: string }> = [
  { key: 'all', label: '全部' },
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
const pageSize = ref(10)
const listLoading = ref(false)
const statusFilter = ref<StatusFilter>('review')
const searchQ = ref('')
const candidateMap = ref<Record<string, Candidate[]>>({})
const candidateLoading = ref<Record<string, boolean>>({})
const candidateError = ref<Record<string, boolean>>({})
const selectedByRow = ref<Record<string, string>>({})
const mutationBusyRow = ref('')

const mappingRules = ref<FieldDescriptor[]>([])
const selectedFieldIds = ref<string[]>([])
const fieldSelectionTouched = ref(false)
const showAllFields = ref(true)

const currentSuccessThreshold = ref(88)
const currentReviewThreshold = ref(75)
const draftSuccessThreshold = ref(88)
const thresholdPreview = ref<ThresholdPreview | null>(null)
const thresholdPreviewSignature = ref('')
const previewBusy = ref(false)
const applyBusy = ref(false)

const drawerVisible = ref(false)
const drawerItem = ref<WorkbenchItem | null>(null)

let pollTimer: number | undefined
let progressRefreshing = false
let contextVersion = 0

const activeTask = computed(() => reviewRows.value.find(task => task.id === activeTaskId.value) ?? null)
const workspaceTasks = computed(() => reviewRows.value.filter(task => {
  if (task.summaryError || task.result_file_id) return false
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
const thresholdDirty = computed(() => draftSuccessThreshold.value !== currentSuccessThreshold.value)
const thresholdValid = computed(() => draftSuccessThreshold.value > currentReviewThreshold.value && draftSuccessThreshold.value <= 100)
const currentPreviewSignature = computed(() => String(draftSuccessThreshold.value))
const canApplyThreshold = computed(() => thresholdDirty.value && thresholdValid.value && thresholdPreview.value && thresholdPreviewSignature.value === currentPreviewSignature.value)
const drawerCandidates = computed(() => drawerItem.value ? candidatesFor(drawerItem.value) : [])

const pageFieldDescriptors = computed<FieldDescriptor[]>(() => {
  const descriptors: FieldDescriptor[] = mappingRules.value.map(rule => ({ ...rule }))
  const referencedSource = new Set(descriptors.flatMap(item => item.sourceFields))
  const referencedTarget = new Set(descriptors.flatMap(item => item.targetFields))
  const sourceKeys = new Set<string>()
  const targetKeys = new Set<string>()

  for (const item of workbenchItems.value) {
    Object.keys(item.source_payload ?? {}).forEach(key => sourceKeys.add(key))
    for (const candidate of candidatesFor(item)) {
      Object.keys(candidate.target_payload ?? {}).forEach(key => targetKeys.add(key))
    }
  }

  for (const key of [...new Set([...sourceKeys, ...targetKeys])]) {
    if (referencedSource.has(key) || referencedTarget.has(key)) continue
    descriptors.push({
      id: `raw:${key}`,
      label: key,
      sourceFields: sourceKeys.has(key) ? [key] : [],
      targetFields: targetKeys.has(key) ? [key] : [],
    })
  }
  return descriptors
})

const visibleFieldDescriptors = computed(() => {
  const selected = pageFieldDescriptors.value.filter(field => selectedFieldIds.value.includes(field.id))
  return showAllFields.value ? selected : selected.slice(0, 6)
})

const drawerFieldDescriptors = computed(() => {
  if (!drawerItem.value) return []
  return descriptorsFor([drawerItem.value], drawerCandidates.value)
})

function normalizeTask(task: any): ReviewTask {
  return {
    id: String(task.task_id ?? ''),
    name: String(task.name ?? '未命名任务'),
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

function formatDate(value: string | null | undefined): string {
  if (!value) return '—'
  return value.slice(0, 19).replace('T', ' ')
}

function displayValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
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
  const percentScore = scoreAsPercent(fieldScore?.score)
  if (percentScore !== null && percentScore >= 55) return 'partial'
  return 'different'
}

function comparisonLabel(kind: ComparisonKind): string {
  return ({ exact: '一致', partial: '部分一致', different: '不一致', empty: '无数据' } as Record<ComparisonKind, string>)[kind]
}

function comparisonIcon(kind: ComparisonKind): string {
  return ({ exact: '✓', partial: '≈', different: '×', empty: '—' } as Record<ComparisonKind, string>)[kind]
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
  return String(error?.response?.data?.error?.message ?? error?.message ?? fallback)
}

function errorStatus(error: any): number {
  return Number(error?.response?.status ?? 0)
}

function candidatesFor(item: WorkbenchItem): Candidate[] {
  return (candidateMap.value[item.source_row_id] ?? item.candidates ?? []).slice(0, 5)
}

function filterCount(key: StatusFilter): number {
  if (key === 'all') return totalRecords.value
  if (key === 'auto') return summary.value.automatic_matched
  if (key === 'review') return summary.value.pending_review
  if (key === 'confirmed') return summary.value.confirmed
  return summary.value.unmatched
}

function backendStatus(key: StatusFilter): string | undefined {
  return STATUS_TABS.find(tab => tab.key === key)?.backend
}

function selectedValue(item: WorkbenchItem): string {
  return selectedByRow.value[item.source_row_id] ?? ''
}

function setSelectedValue(item: WorkbenchItem, value: string): void {
  selectedByRow.value = { ...selectedByRow.value, [item.source_row_id]: value }
}

function initialSelection(item: WorkbenchItem, candidates: Candidate[]): string {
  if (item.current_status === 'UNMATCHED') return NONE_SELECTION
  if (item.final_group_code) return String(item.final_group_code)
  if (item.current_status === 'MATCHED' && item.top1_group_code) return String(item.top1_group_code)
  const matchedCandidate = candidates.find(candidate => candidate.target_group_code === item.final_group_code)
  return matchedCandidate?.target_group_code ?? ''
}

function rowActionText(item: WorkbenchItem): string {
  const selected = selectedValue(item)
  if (selected === NONE_SELECTION) return '确认均不匹配'
  if (item.current_status === 'CONFIRMED' && selected === String(item.final_group_code ?? '')) return '已确认'
  if (item.current_status === 'MATCHED' && selected === String(item.final_group_code ?? item.top1_group_code ?? '')) return '确认自动结果'
  if (item.current_status === 'CONFIRMED') return '改为此候选'
  return '确认匹配'
}

function rowActionDisabled(item: WorkbenchItem): boolean {
  const selected = selectedValue(item)
  if (!selected) return true
  if (item.current_status === 'CONFIRMED' && selected === String(item.final_group_code ?? '')) return true
  return mutationBusyRow.value === item.source_row_id
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

function descriptorsFor(items: WorkbenchItem[], candidates: Candidate[]): FieldDescriptor[] {
  const descriptors = mappingRules.value.map(rule => ({ ...rule }))
  const referencedSource = new Set(descriptors.flatMap(item => item.sourceFields))
  const referencedTarget = new Set(descriptors.flatMap(item => item.targetFields))
  const sourceKeys = new Set<string>()
  const targetKeys = new Set<string>()
  items.forEach(item => Object.keys(item.source_payload ?? {}).forEach(key => sourceKeys.add(key)))
  candidates.forEach(candidate => Object.keys(candidate.target_payload ?? {}).forEach(key => targetKeys.add(key)))
  for (const key of [...new Set([...sourceKeys, ...targetKeys])]) {
    if (referencedSource.has(key) || referencedTarget.has(key)) continue
    descriptors.push({ id: `raw:${key}`, label: key, sourceFields: sourceKeys.has(key) ? [key] : [], targetFields: targetKeys.has(key) ? [key] : [] })
  }
  return descriptors
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

function taskThresholds(taskDetail: any): { success: number; review: number } {
  const decision = taskDetail?.config_snapshot?.decision ?? {}
  const success = Number(decision.success_threshold ?? 88)
  const review = Number(decision.review_threshold ?? 75)
  return {
    success: Number.isFinite(success) ? success : 88,
    review: Number.isFinite(review) ? review : 75,
  }
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
    final_group_code: item?.final_group_code ? String(item.final_group_code) : null,
    candidates: Array.isArray(item?.candidates) ? item.candidates.map(normalizeCandidate).slice(0, 5) : undefined,
  }
}

async function hydrateCandidates(items: WorkbenchItem[], version: number): Promise<void> {
  const nextMap: Record<string, Candidate[]> = {}
  const missing: WorkbenchItem[] = []
  for (const item of items) {
    if (item.candidates?.length) nextMap[item.source_row_id] = item.candidates.slice(0, 5)
    else missing.push(item)
  }
  candidateMap.value = nextMap
  candidateError.value = {}
  candidateLoading.value = Object.fromEntries(missing.map(item => [item.source_row_id, true]))

  for (let index = 0; index < missing.length; index += 6) {
    const batch = missing.slice(index, index + 6)
    const responses = await Promise.all(batch.map(async item => {
      try {
        const response = (await api.get(`/tasks/${activeTaskId.value}/items/${item.source_row_id}/candidates`)).data ?? {}
        return { item, candidates: (Array.isArray(response.candidates) ? response.candidates : []).map(normalizeCandidate).slice(0, 5), error: false }
      } catch {
        return { item, candidates: [] as Candidate[], error: true }
      }
    }))
    if (version !== contextVersion) return
    const mapCopy = { ...candidateMap.value }
    const loadingCopy = { ...candidateLoading.value }
    const errorCopy = { ...candidateError.value }
    for (const result of responses) {
      mapCopy[result.item.source_row_id] = result.candidates
      loadingCopy[result.item.source_row_id] = false
      errorCopy[result.item.source_row_id] = result.error
    }
    candidateMap.value = mapCopy
    candidateLoading.value = loadingCopy
    candidateError.value = errorCopy
  }

  if (version !== contextVersion) return
  const nextSelections = { ...selectedByRow.value }
  for (const item of items) {
    if (!(item.source_row_id in nextSelections)) nextSelections[item.source_row_id] = initialSelection(item, candidatesFor(item))
  }
  selectedByRow.value = nextSelections
  syncFieldSelection()
}

async function loadItems(resetPage = false, version = contextVersion): Promise<void> {
  const taskId = activeTaskId.value
  if (!taskId) return
  if (resetPage) page.value = 1
  listLoading.value = true
  try {
    const params: Record<string, unknown> = { page: page.value, page_size: pageSize.value, include_candidates: 5 }
    const status = backendStatus(statusFilter.value)
    if (status) params.status = status
    else params.status = 'ALL'
    if (searchQ.value.trim()) params.q = searchQ.value.trim()
    const response = (await api.get(`/tasks/${taskId}/workbench/items`, { params })).data ?? {}
    if (version !== contextVersion || activeTaskId.value !== taskId) return
    const items = (Array.isArray(response.items) ? response.items : []).map(normalizeWorkbenchItem)
    workbenchItems.value = items
    workbenchTotal.value = Number(response.total ?? 0)
    const lastPage = Math.max(1, Math.ceil(workbenchTotal.value / pageSize.value))
    if (page.value > lastPage) {
      page.value = lastPage
      await loadItems(false, version)
      return
    }
    await hydrateCandidates(items, version)
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
  thresholdPreview.value = null
  thresholdPreviewSignature.value = ''
  drawerVisible.value = false
  page.value = 1
  selectedByRow.value = {}
  fieldSelectionTouched.value = false
  try {
    const [taskResponse, summaryResponse] = await Promise.all([
      api.get(`/tasks/${taskId}`),
      api.get(`/tasks/${taskId}/workbench/summary`),
    ])
    if (version !== contextVersion) return
    const detail = taskResponse.data ?? {}
    const thresholds = taskThresholds(detail)
    currentSuccessThreshold.value = thresholds.success
    currentReviewThreshold.value = thresholds.review
    draftSuccessThreshold.value = thresholds.success
    mappingRules.value = mappingDescriptors(detail?.config_snapshot ?? {})
    summary.value = {
      pending_review: Number(summaryResponse.data?.pending_review ?? 0),
      confirmed: Number(summaryResponse.data?.confirmed ?? 0),
      unmatched: Number(summaryResponse.data?.unmatched ?? 0),
      automatic_matched: Number(summaryResponse.data?.automatic_matched ?? 0),
    }
    await loadItems(false, version)
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

    if (nextTask) {
      await loadWorkbenchContext(nextTask.id)
    } else {
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

function onStatusChange(next: StatusFilter): void {
  statusFilter.value = next
  void loadItems(true)
}

function onSearch(): void {
  void loadItems(true)
}

function onPageChange(nextPage: number): void {
  page.value = nextPage
  void loadItems(false)
}

function onPageSizeChange(nextSize: number): void {
  pageSize.value = nextSize
  page.value = 1
  void loadItems(false)
}

function invalidateThresholdPreview(): void {
  if (thresholdPreviewSignature.value !== currentPreviewSignature.value) thresholdPreview.value = null
}

function normalizeThresholdPreview(data: any): ThresholdPreview {
  const raw = data?.preview ?? data ?? {}
  const before = raw.before ?? raw.current_summary ?? summary.value
  const after = raw.after ?? raw.resulting_summary ?? raw.summary ?? {}
  const beforeAutomatic = Number(before.automatic_matched ?? before.matched ?? summary.value.automatic_matched)
  const afterAutomatic = Number(after.automatic_matched ?? after.matched ?? raw.automatic_matched ?? beforeAutomatic)
  return {
    addedAutomatic: Number(raw.review_to_matched ?? raw.promoted_to_matched ?? raw.matched_delta ?? Math.max(0, afterAutomatic - beforeAutomatic) ?? 0),
    remainingManual: Number(raw.remaining_review ?? raw.pending_review ?? after.pending_review ?? after.review ?? summary.value.pending_review),
    unmatched: Number(raw.resulting_unmatched ?? raw.unmatched ?? after.unmatched ?? summary.value.unmatched),
  }
}

async function previewThreshold(): Promise<void> {
  if (!activeTaskId.value || !thresholdValid.value) return
  previewBusy.value = true
  try {
    const response = await api.post(`/tasks/${activeTaskId.value}/re-decide`, {
      success_threshold: draftSuccessThreshold.value,
      review_threshold: currentReviewThreshold.value,
      mode: 'preview',
    })
    thresholdPreview.value = normalizeThresholdPreview(response.data)
    thresholdPreviewSignature.value = currentPreviewSignature.value
  } catch (error) {
    thresholdPreview.value = null
    thresholdPreviewSignature.value = ''
    ElMessage.error(apiErrorMessage(error, '阈值影响预览失败'))
  } finally {
    previewBusy.value = false
  }
}

async function applyThreshold(): Promise<void> {
  if (!activeTaskId.value || !canApplyThreshold.value) return
  try {
    await ElMessageBox.confirm(`将自动匹配阈值从 ${currentSuccessThreshold.value} 调整为 ${draftSuccessThreshold.value}。`, '应用新阈值', {
      confirmButtonText: '确认应用',
      cancelButtonText: '取消',
      type: 'warning',
    })
  } catch {
    return
  }
  applyBusy.value = true
  try {
    await api.post(`/tasks/${activeTaskId.value}/re-decide`, {
      success_threshold: draftSuccessThreshold.value,
      review_threshold: currentReviewThreshold.value,
      mode: 'apply',
    })
    currentSuccessThreshold.value = draftSuccessThreshold.value
    thresholdPreview.value = null
    thresholdPreviewSignature.value = ''
    ElMessage.success('自动匹配阈值已应用')
    await refreshAfterMutation()
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '应用新阈值失败'))
  } finally {
    applyBusy.value = false
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

async function refreshAfterMutation(): Promise<void> {
  const taskId = activeTaskId.value
  if (!taskId) return
  await refreshSummary(taskId)
  await loadItems(false)
}

async function applyRowSelection(item: WorkbenchItem): Promise<void> {
  const selected = selectedValue(item)
  if (!selected) return
  mutationBusyRow.value = item.source_row_id
  try {
    if (selected === NONE_SELECTION) {
      await api.post(`/tasks/${activeTaskId.value}/items/${item.source_row_id}/reject`, { comment: '' })
      ElMessage.success('已确认均不匹配')
    } else {
      await api.post(`/tasks/${activeTaskId.value}/items/${item.source_row_id}/confirm`, { target_id: selected, comment: '' })
      ElMessage.success(`已匹配到 ${selected}`)
    }
    await refreshAfterMutation()
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '人工匹配操作失败'))
  } finally {
    mutationBusyRow.value = ''
  }
}

async function cancelManualMatch(item: WorkbenchItem): Promise<void> {
  mutationBusyRow.value = item.source_row_id
  try {
    const paths = [
      `/tasks/${activeTaskId.value}/items/${item.source_row_id}/cancel-confirm`,
      `/tasks/${activeTaskId.value}/items/${item.source_row_id}/unconfirm`,
      `/tasks/${activeTaskId.value}/items/${item.source_row_id}/cancel`,
    ]
    let handled = false
    for (const path of paths) {
      try {
        await api.post(path, {})
        handled = true
        break
      } catch (error) {
        if ([404, 405].includes(errorStatus(error))) continue
        throw error
      }
    }
    if (!handled) throw new Error('当前后端尚未提供取消人工匹配接口')
    ElMessage.success('已取消人工匹配，可重新选择候选')
    selectedByRow.value = { ...selectedByRow.value, [item.source_row_id]: '' }
    await refreshAfterMutation()
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '取消匹配失败'))
  } finally {
    mutationBusyRow.value = ''
  }
}

async function retryCandidates(item: WorkbenchItem): Promise<void> {
  candidateLoading.value = { ...candidateLoading.value, [item.source_row_id]: true }
  candidateError.value = { ...candidateError.value, [item.source_row_id]: false }
  try {
    const response = (await api.get(`/tasks/${activeTaskId.value}/items/${item.source_row_id}/candidates`)).data ?? {}
    candidateMap.value = {
      ...candidateMap.value,
      [item.source_row_id]: (Array.isArray(response.candidates) ? response.candidates : []).map(normalizeCandidate).slice(0, 5),
    }
    syncFieldSelection()
  } catch (error) {
    candidateError.value = { ...candidateError.value, [item.source_row_id]: true }
    ElMessage.error(apiErrorMessage(error, '候选读取失败'))
  } finally {
    candidateLoading.value = { ...candidateLoading.value, [item.source_row_id]: false }
  }
}

async function openMoreFields(item: WorkbenchItem): Promise<void> {
  drawerItem.value = item
  if (!candidatesFor(item).length && !candidateLoading.value[item.source_row_id]) await retryCandidates(item)
  drawerVisible.value = true
}

onMounted(() => void load())
onBeforeUnmount(() => {
  stopPolling()
  ++contextVersion
})
</script>

<template>
  <div class="review-page">
    <div class="toolbar review-toolbar">
      <div>
        <h2>第三步 · 人工调整</h2>
        <p>直接比较源物料与前 5 个候选，选择正确集团码；不需要逐条打开弹窗。</p>
      </div>
      <div class="review-toolbar-actions">
        <el-select v-if="workspaceTasks.length > 1" :model-value="activeTaskId" class="review-task-switcher" placeholder="切换任务" @change="selectTask">
          <el-option v-for="taskRow in workspaceTasks" :key="taskRow.id" :label="`${taskRow.name} · ${formatNumber(taskRow.summary?.pending_review)} 条待人工`" :value="taskRow.id" />
        </el-select>
        <el-button :loading="loading" @click="load">刷新</el-button>
      </div>
    </div>

    <section v-if="consoleMode !== 'ready'" class="review-console" :class="`is-${consoleMode}`" aria-live="polite">
      <template v-if="consoleMode === 'waiting' && calculatingTask">
        <div class="review-console-main">
          <div class="review-console-kicker"><span class="review-status-dot"></span>第二步计算进行中</div>
          <h3>等待匹配计算完成</h3>
          <p>任务「{{ calculatingTask.name }}」仍在计算，完成后这里会自动出现在线人工匹配工作台。</p>
          <div class="review-console-meta">
            <span>{{ phaseLabel(calculatingProgress?.current_phase) }}</span>
            <span>{{ runStatusLabel(calculatingProgress?.status ?? calculatingTask.status) }}</span>
            <span v-if="waitingTotal > 0">已处理 {{ formatNumber(waitingProcessed) }} / {{ formatNumber(waitingTotal) }} 行</span>
          </div>
        </div>
        <div class="review-wait-progress">
          <div class="review-wait-percent"><b>{{ waitingPercent }}%</b><span>计算进度</span></div>
          <el-progress :percentage="waitingPercent" :stroke-width="10" :show-text="false" />
        </div>
        <div class="review-console-action">
          <el-button type="primary" plain size="large" @click="openTask(calculatingTask)">查看计算进度</el-button>
        </div>
      </template>

      <template v-else-if="consoleMode === 'error'">
        <div class="review-console-main">
          <div class="review-console-kicker"><span class="review-status-dot"></span>状态读取异常</div>
          <h3>暂时无法读取人工调整数据</h3>
          <p>{{ loadError || '部分任务汇总读取失败，请重试。' }}</p>
        </div>
        <div class="review-console-action">
          <el-button type="primary" :loading="loading" @click="load">重新读取</el-button>
        </div>
      </template>

      <template v-else>
        <div class="review-console-main">
          <div class="review-console-kicker"><span class="review-status-dot"></span>暂无可调整任务</div>
          <h3>当前没有可进入人工调整的匹配结果</h3>
          <p>请先完成第二步匹配计算；已有最终结果的任务可前往第四步查看。</p>
          <div v-if="latestFailed" class="review-failure-note">
            <b>最近失败任务：{{ latestFailed.name }}</b>
            <span>{{ latestFailed.error_message || latestFailed.error_code || '计算失败' }}</span>
          </div>
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
          <div class="review-console-kicker"><span class="review-status-dot"></span>正在调整 · {{ activeTask.name }}</div>
          <h3>所有状态都可以复查，待人工记录直接在本页完成选择</h3>
          <p>列表使用服务端分页和筛选。每条记录仅加载当前页的 Top 5 候选，不会一次把上万条数据送到浏览器。</p>
        </div>
        <div class="review-task-hero-meta">
          <span>任务 {{ activeTask.id.slice(0, 12) }}</span>
          <span>计算完成 {{ formatDate(activeTask.finished_at) }}</span>
        </div>
      </section>

      <section class="review-metric-grid" aria-label="匹配状态汇总">
        <div class="review-metric-card"><span>全部</span><b>{{ formatNumber(totalRecords) }}</b><small>本任务全部记录</small></div>
        <div class="review-metric-card is-success"><span>已自动匹配</span><b>{{ formatNumber(summary.automatic_matched) }}</b><small>系统自动完成</small></div>
        <div class="review-metric-card is-warning"><span>待人工匹配</span><b>{{ formatNumber(summary.pending_review) }}</b><small>需要人工选择</small></div>
        <div class="review-metric-card is-primary"><span>已人工匹配</span><b>{{ formatNumber(summary.confirmed) }}</b><small>可以继续复查</small></div>
        <div class="review-metric-card"><span>未匹配</span><b>{{ formatNumber(summary.unmatched) }}</b><small>当前没有匹配结果</small></div>
      </section>

      <section class="review-strategy-card">
        <div class="review-strategy-head">
          <div>
            <div class="review-section-kicker">自动匹配阈值</div>
            <h3>预览影响后再应用</h3>
            <p>这里只调整自动匹配阈值；预览不会修改正式结果。</p>
          </div>
          <div class="review-current-threshold">当前 <b>{{ currentSuccessThreshold }}</b></div>
        </div>
        <div class="review-threshold-editor">
          <div class="review-threshold-control">
            <div class="review-threshold-label"><span>新的自动匹配阈值</span><b>{{ draftSuccessThreshold }}</b></div>
            <el-slider v-model="draftSuccessThreshold" :min="currentReviewThreshold + 1" :max="100" :step="1" @input="invalidateThresholdPreview" />
          </div>
          <div class="review-threshold-actions">
            <el-button type="primary" plain :loading="previewBusy" :disabled="!thresholdDirty || !thresholdValid" @click="previewThreshold">预览影响</el-button>
            <el-button type="primary" :loading="applyBusy" :disabled="!canApplyThreshold" @click="applyThreshold">应用新阈值</el-button>
          </div>
        </div>
        <div v-if="thresholdPreview" class="review-impact-grid">
          <div><span>预计新增自动匹配</span><b>+{{ formatNumber(thresholdPreview.addedAutomatic) }}</b></div>
          <div><span>预计还需人工</span><b>{{ formatNumber(thresholdPreview.remainingManual) }}</b></div>
          <div><span>预计未匹配</span><b>{{ formatNumber(thresholdPreview.unmatched) }}</b></div>
        </div>
      </section>

      <section class="panel review-workbench-panel">
        <div class="review-workbench-head">
          <div>
            <div class="review-section-kicker">在线人工匹配</div>
            <h3>源物料与 Top 5 候选直接对比</h3>
            <p>绿色表示一致，黄色表示部分一致，红色表示不一致，灰色表示一侧或两侧没有数据；文字状态始终同时显示。</p>
          </div>
          <div class="review-field-actions">
            <el-select v-model="selectedFieldIds" multiple collapse-tags collapse-tags-tooltip class="review-field-select" placeholder="选择显示字段" @change="onFieldSelectionChange">
              <el-option v-for="field in pageFieldDescriptors" :key="field.id" :label="field.label" :value="field.id" />
            </el-select>
            <el-button @click="showAllFields = !showAllFields">{{ showAllFields ? '收起字段' : '展开全部字段' }}</el-button>
          </div>
        </div>

        <div class="review-status-tabs" role="tablist" aria-label="状态筛选">
          <button v-for="tab in STATUS_TABS" :key="tab.key" type="button" class="review-status-tab" :class="{ 'is-active': statusFilter === tab.key }" @click="onStatusChange(tab.key)">
            <span>{{ tab.label }}</span><b>{{ formatNumber(filterCount(tab.key)) }}</b>
          </button>
        </div>

        <div class="review-list-tools">
          <div class="review-search-box">
            <el-input v-model="searchQ" clearable placeholder="搜索源物料、源数据或集团码" @keyup.enter="onSearch" @clear="onSearch" />
            <el-button @click="onSearch">搜索</el-button>
          </div>
          <span>当前页 {{ workbenchItems.length }} 条 · 服务端分页</span>
        </div>

        <div v-loading="listLoading" class="review-record-list">
          <article v-for="item in workbenchItems" :key="item.source_row_id" class="review-record-card">
            <header class="review-record-head">
              <div class="review-record-identity">
                <el-tag size="small" :type="statusTagType(item.current_status)">{{ statusLabel(item.current_status) }}</el-tag>
                <div><strong>{{ item.source_id || '未命名源物料' }}</strong><span v-if="item.source_row_number">源 Excel 第 {{ item.source_row_number }} 行</span></div>
              </div>
              <div class="review-record-current">
                <span>当前结果</span><b>{{ item.final_group_code || (item.current_status === 'MATCHED' ? item.top1_group_code : '') || '—' }}</b>
                <el-button link type="primary" @click="openMoreFields(item)">查看更多字段</el-button>
              </div>
            </header>

            <div v-if="candidateError[item.source_row_id]" class="review-candidate-error">
              <span>候选加载失败。</span><el-button link type="primary" @click="retryCandidates(item)">重新加载</el-button>
            </div>

            <div class="review-candidate-strip">
              <label v-for="candidate in candidatesFor(item)" :key="candidate.rank" class="review-candidate-card" :class="{ 'is-selected': selectedValue(item) === candidate.target_group_code }">
                <input type="radio" :name="`candidate-${item.source_row_id}`" :checked="selectedValue(item) === candidate.target_group_code" @change="setSelectedValue(item, candidate.target_group_code)" />
                <div class="review-candidate-head">
                  <div><span>候选 {{ candidate.rank }}</span><strong>{{ candidate.target_group_code || '—' }}</strong></div>
                  <div class="review-candidate-score"><b>{{ formatScore(candidate.score) }}</b><small>分</small></div>
                </div>
                <div v-if="candidate.target_row_number" class="review-candidate-rowno">目标 Excel 第 {{ candidate.target_row_number }} 行</div>
                <div class="review-compare-head"><span>字段</span><span>源物料</span><span>候选</span><span>对比</span></div>
                <div v-for="field in visibleFieldDescriptors" :key="field.id" class="review-compare-row" :class="`is-${comparisonKind(item, candidate, field)}`">
                  <span class="review-compare-field" :title="field.label">{{ field.label }}</span>
                  <span class="review-compare-value source-value" :title="fieldValue(item.source_payload, field.sourceFields) || '无数据'">{{ fieldValue(item.source_payload, field.sourceFields) || '—' }}</span>
                  <span class="review-compare-value target-value" :title="fieldValue(candidate.target_payload, field.targetFields) || '无数据'">{{ fieldValue(candidate.target_payload, field.targetFields) || '—' }}</span>
                  <span class="review-compare-state"><i>{{ comparisonIcon(comparisonKind(item, candidate, field)) }}</i>{{ comparisonLabel(comparisonKind(item, candidate, field)) }}</span>
                </div>
              </label>

              <label class="review-candidate-card review-none-card" :class="{ 'is-selected': selectedValue(item) === NONE_SELECTION }">
                <input type="radio" :name="`candidate-${item.source_row_id}`" :checked="selectedValue(item) === NONE_SELECTION" @change="setSelectedValue(item, NONE_SELECTION)" />
                <div class="review-none-icon">∅</div>
                <strong>均不匹配</strong>
                <p>Top 5 都不正确时选择这里，再点击确认。</p>
              </label>
            </div>

            <footer class="review-record-actions">
              <div class="review-record-hint">
                <template v-if="candidateLoading[item.source_row_id]">正在加载 Top 5 候选…</template>
                <template v-else>已加载 {{ candidatesFor(item).length }} 个候选；可横向滚动查看。</template>
              </div>
              <div>
                <el-button v-if="item.current_status === 'CONFIRMED'" plain :loading="mutationBusyRow === item.source_row_id" @click="cancelManualMatch(item)">取消匹配</el-button>
                <el-button type="primary" :loading="mutationBusyRow === item.source_row_id" :disabled="rowActionDisabled(item)" @click="applyRowSelection(item)">{{ rowActionText(item) }}</el-button>
              </div>
            </footer>
          </article>

          <el-empty v-if="!listLoading && !workbenchItems.length" :description="`${STATUS_TABS.find(tab => tab.key === statusFilter)?.label ?? '当前'}筛选下暂无记录`" :image-size="72" />
        </div>

        <div class="review-pagination-row">
          <span>仅渲染当前页，候选也只按当前页加载</span>
          <el-pagination background layout="total, sizes, prev, pager, next" :total="workbenchTotal" :current-page="page" :page-size="pageSize" :page-sizes="PAGE_SIZE_OPTIONS" @current-change="onPageChange" @size-change="onPageSizeChange" />
        </div>
      </section>
    </template>

    <section class="panel review-list-panel">
      <div class="section-head">
        <div>
          <h3>可人工调整的任务</h3>
          <p class="review-section-desc">可以切换其它已完成匹配计算且尚未最终导出的任务。</p>
        </div>
      </div>
      <el-table v-if="reviewRows.length" :data="reviewRows" size="default">
        <el-table-column label="名称" min-width="220"><template #default="scope"><a class="row-link" @click="openTask(scope.row)">{{ scope.row.name }}</a><div class="row-sub">{{ scope.row.id }}</div></template></el-table-column>
        <el-table-column label="自动匹配" width="110"><template #default="scope">{{ scope.row.summaryError ? '—' : formatNumber(scope.row.summary?.automatic_matched) }}</template></el-table-column>
        <el-table-column label="待人工" width="100"><template #default="scope">{{ scope.row.summaryError ? '—' : formatNumber(scope.row.summary?.pending_review) }}</template></el-table-column>
        <el-table-column label="已人工" width="100"><template #default="scope">{{ scope.row.summaryError ? '—' : formatNumber(scope.row.summary?.confirmed) }}</template></el-table-column>
        <el-table-column label="未匹配" width="100"><template #default="scope">{{ scope.row.summaryError ? '—' : formatNumber(scope.row.summary?.unmatched) }}</template></el-table-column>
        <el-table-column label="计算完成" width="170"><template #default="scope">{{ formatDate(scope.row.finished_at) }}</template></el-table-column>
        <el-table-column label="操作" width="130">
          <template #default="scope">
            <el-button v-if="workspaceTasks.some(task => task.id === scope.row.id)" link type="primary" @click="selectTask(scope.row.id)">进入工作台</el-button>
            <el-button v-else link type="info" @click="openTask(scope.row)">查看任务</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-else description="暂无已完成匹配计算的任务" :image-size="72" />
    </section>

    <el-drawer v-model="drawerVisible" size="92%" class="review-detail-drawer" :with-header="false" :append-to-body="false">
      <div v-if="drawerItem" class="review-drawer">
        <div class="review-drawer-head">
          <div>
            <div class="review-section-kicker">完整字段对比</div>
            <h3>{{ drawerItem.source_id }}</h3>
            <p>这里展开当前源物料和 Top 5 候选的全部可见业务字段。</p>
          </div>
          <el-button circle @click="drawerVisible = false">×</el-button>
        </div>
        <div class="review-drawer-table-wrap">
          <table class="review-drawer-table">
            <thead>
              <tr><th>字段</th><th>源物料</th><th v-for="candidate in drawerCandidates" :key="candidate.rank">候选 {{ candidate.rank }} · {{ candidate.target_group_code }}</th></tr>
            </thead>
            <tbody>
              <tr v-for="field in drawerFieldDescriptors" :key="field.id">
                <th>{{ field.label }}</th>
                <td>{{ fieldValue(drawerItem.source_payload, field.sourceFields) || '—' }}</td>
                <td v-for="candidate in drawerCandidates" :key="candidate.rank" :class="`is-${comparisonKind(drawerItem, candidate, field)}`">
                  <span>{{ fieldValue(candidate.target_payload, field.targetFields) || '—' }}</span>
                  <small>{{ comparisonIcon(comparisonKind(drawerItem, candidate, field)) }} {{ comparisonLabel(comparisonKind(drawerItem, candidate, field)) }}</small>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </el-drawer>
  </div>
</template>
