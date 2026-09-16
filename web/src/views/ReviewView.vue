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

type WorkbenchItem = {
  source_row_id: string
  source_id: string
  source_payload: Record<string, unknown>
  top1_group_code?: string | null
  top1_score: number
  second_score: number
  score_gap: number
  critical_conflict: boolean
  current_status?: string
}

type FieldScore = {
  rule_id: string
  score: number
  weight: number
  source_value: string
  target_value: string
  critical: boolean
  conflict: boolean
}

type Candidate = {
  rank: number
  target_group_code: string
  score: number
  critical_conflict: boolean
  target_payload: Record<string, unknown>
  field_scores: FieldScore[]
}

type RiskMode = 'all' | 'high' | 'gap' | 'conflict' | 'medium' | 'low'

type RiskCounts = Record<RiskMode, number>

type ThresholdPreview = {
  exact: boolean
  reviewToMatched: number
  remainingReview: number
  protectedConflicts: number
  resultingUnmatched: number
  note: string
}

const route = useRoute()
const router = useRouter()
const RUNNING_STATUSES = ['RUNNING', 'PREPARING', 'RECOVERING', 'PENDING']
const PAGE_SIZE_OPTIONS = [20, 50, 100]
const RISK_MODES: RiskMode[] = ['all', 'high', 'gap', 'conflict', 'medium', 'low']

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
const riskMode = ref<RiskMode>('all')
const riskCounts = ref<RiskCounts>({ all: 0, high: 0, gap: 0, conflict: 0, medium: 0, low: 0 })
const riskCountsLoading = ref(false)
const searchQ = ref('')
const selectedRows = ref<WorkbenchItem[]>([])
const mutationBusy = ref(false)

const currentSuccessThreshold = ref(88)
const currentReviewThreshold = ref(75)
const draftSuccessThreshold = ref(88)
const draftReviewThreshold = ref(75)
const thresholdPreview = ref<ThresholdPreview | null>(null)
const thresholdPreviewSignature = ref('')
const previewBusy = ref(false)
const applyBusy = ref(false)

const drawerVisible = ref(false)
const drawerLoading = ref(false)
const drawerItem = ref<WorkbenchItem | null>(null)
const candidates = ref<Candidate[]>([])
const candidateIndex = ref(0)

let pollTimer: number | undefined
let progressRefreshing = false
let contextVersion = 0

const activeTask = computed(() => reviewRows.value.find(task => task.id === activeTaskId.value) ?? null)
const actionableTasks = computed(() => reviewRows.value.filter(task => !task.summaryError && Number(task.summary?.pending_review ?? 0) > 0 && !task.result_file_id))
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
const totalRecords = computed(() => Number(summary.value.pending_review) + Number(summary.value.confirmed) + Number(summary.value.unmatched) + Number(summary.value.automatic_matched))
const thresholdDirty = computed(() => draftSuccessThreshold.value !== currentSuccessThreshold.value || draftReviewThreshold.value !== currentReviewThreshold.value)
const thresholdValid = computed(() => draftReviewThreshold.value >= 0 && draftReviewThreshold.value < draftSuccessThreshold.value && draftSuccessThreshold.value <= 100)
const currentPreviewSignature = computed(() => `${draftSuccessThreshold.value}:${draftReviewThreshold.value}`)
const canApplyThresholds = computed(() => Boolean(thresholdPreview.value) && thresholdPreviewSignature.value === currentPreviewSignature.value && thresholdValid.value && thresholdDirty.value)
const currentCandidate = computed(() => candidates.value[candidateIndex.value] ?? null)
const topCandidates = computed(() => candidates.value.slice(0, 2))
const matchingFields = computed(() => (currentCandidate.value?.field_scores ?? []).filter(field => !field.conflict && Number(field.score) >= 80))
const conflictFields = computed(() => (currentCandidate.value?.field_scores ?? []).filter(field => field.conflict))
const deductionFields = computed(() => (currentCandidate.value?.field_scores ?? []).filter(field => Number(field.score) < 99.999).sort((a, b) => Number(a.score) - Number(b.score)))
const candidatePayloadDiffs = computed(() => {
  const first = candidates.value[0]?.target_payload ?? {}
  const second = candidates.value[1]?.target_payload ?? {}
  const keys = [...new Set([...Object.keys(first), ...Object.keys(second)])]
  return keys
    .filter(key => displayValue(first[key]) !== displayValue(second[key]))
    .slice(0, 8)
    .map(key => ({ key, first: displayValue(first[key]), second: displayValue(second[key]) }))
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

function deductionPoints(field: FieldScore): string {
  const weight = Number(field.weight ?? 0)
  const score = Number(field.score ?? 0)
  if (!Number.isFinite(weight) || !Number.isFinite(score)) return '0'
  return Math.max(0, weight * (100 - score) / 100).toFixed(1).replace(/\.0$/, '')
}

function displayValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—'
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}

function sourceBrief(item: WorkbenchItem): string {
  return Object.values(item.source_payload ?? {}).filter(value => value !== null && value !== undefined && value !== '').slice(0, 4).map(displayValue).join(' · ').slice(0, 90) || '—'
}

function phaseLabel(phase: string | null | undefined): string {
  return ({ INDEX: '构建向量索引', RETRIEVE: '候选召回', RERANK: '逐条匹配评分', PERSIST: '结果持久化', DONE: '计算完成', WAITING: '等待调度', FAILED: '计算失败' } as Record<string, string>)[String(phase ?? '')] ?? '准备计算'
}

function statusLabel(status: string): string {
  return ({ RUNNING: '运行中', PREPARING: '准备中', RECOVERING: '恢复中', PENDING: '排队中', COMPLETED: '已完成', FAILED: '失败' } as Record<string, string>)[status] ?? status
}

function apiErrorMessage(error: any, fallback: string): string {
  return String(error?.response?.data?.error?.message ?? error?.message ?? fallback)
}

function errorStatus(error: any): number {
  return Number(error?.response?.status ?? 0)
}

function stopPolling(): void {
  if (pollTimer) window.clearInterval(pollTimer)
  pollTimer = undefined
}

function startPollingIfNeeded(): void {
  stopPolling()
  if (consoleMode.value === 'waiting' && calculatingTask.value) {
    pollTimer = window.setInterval(() => void refreshCalculatingProgress(), 3000)
  }
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
    // 瞬时读取失败时保留最后已知状态，下一轮自动重试。
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

function riskParams(mode: RiskMode): Record<string, unknown> {
  if (mode === 'conflict') return { critical_conflict: true }
  if (mode === 'gap') return { critical_conflict: false, gap_max: 5 }
  if (mode === 'high') return { critical_conflict: false, gap_min: 5.000001, first_score_min: 90 }
  if (mode === 'medium') return { critical_conflict: false, gap_min: 5.000001, first_score_min: 75, first_score_max: 89.999999 }
  if (mode === 'low') return { critical_conflict: false, gap_min: 5.000001, first_score_max: 74.999999 }
  return {}
}

function riskOf(item: WorkbenchItem): RiskMode {
  if (item.critical_conflict) return 'conflict'
  if (Number(item.score_gap) <= 5) return 'gap'
  if (Number(item.top1_score) >= 90) return 'high'
  if (Number(item.top1_score) >= 75) return 'medium'
  return 'low'
}

function riskLabel(mode: RiskMode): string {
  return ({ all: '全部待判断', high: '高分且无冲突', gap: '候选分差很小', conflict: '关键字段冲突', medium: '中等置信度', low: '明显低分' } as Record<RiskMode, string>)[mode]
}

function riskHint(mode: RiskMode): string {
  return ({
    all: '只包含后端仍为 REVIEW 的记录',
    high: '≥90 分、分差 > 5、无关键冲突',
    gap: '第一/第二候选分差 ≤ 5',
    conflict: '关键字段存在硬冲突，不自动放行',
    medium: '75–90 分且无明显冲突',
    low: '<75 分，优先判断是否未匹配',
  } as Record<RiskMode, string>)[mode]
}

function riskTagType(mode: RiskMode): 'success' | 'warning' | 'danger' | 'info' | 'primary' {
  if (mode === 'high') return 'success'
  if (mode === 'conflict') return 'danger'
  if (mode === 'gap') return 'warning'
  if (mode === 'medium') return 'primary'
  return 'info'
}

async function fetchWorkbenchCount(taskId: string, mode: RiskMode): Promise<number> {
  if (mode === 'all') return Number(summary.value.pending_review ?? 0)
  const response = (await api.get(`/tasks/${taskId}/workbench/items`, { params: { ...riskParams(mode), page: 1, page_size: 1 } })).data ?? {}
  return Number(response.total ?? 0)
}

async function loadRiskCounts(taskId: string, version = contextVersion): Promise<void> {
  riskCountsLoading.value = true
  try {
    const modes: RiskMode[] = ['high', 'gap', 'conflict', 'medium', 'low']
    const values = await Promise.all(modes.map(mode => fetchWorkbenchCount(taskId, mode)))
    if (version !== contextVersion || activeTaskId.value !== taskId) return
    riskCounts.value = {
      all: Number(summary.value.pending_review ?? 0),
      high: values[0],
      gap: values[1],
      conflict: values[2],
      medium: values[3],
      low: values[4],
    }
  } finally {
    if (version === contextVersion) riskCountsLoading.value = false
  }
}

async function loadItems(resetPage = false, version = contextVersion): Promise<void> {
  const taskId = activeTaskId.value
  if (!taskId) return
  if (resetPage) page.value = 1
  listLoading.value = true
  try {
    const params: Record<string, unknown> = { ...riskParams(riskMode.value), page: page.value, page_size: pageSize.value }
    if (searchQ.value.trim()) params.q = searchQ.value.trim()
    const response = (await api.get(`/tasks/${taskId}/workbench/items`, { params })).data ?? {}
    if (version !== contextVersion || activeTaskId.value !== taskId) return
    workbenchItems.value = Array.isArray(response.items) ? response.items : []
    workbenchTotal.value = Number(response.total ?? 0)
    selectedRows.value = []
    const lastPage = Math.max(1, Math.ceil(workbenchTotal.value / pageSize.value))
    if (page.value > lastPage) {
      page.value = lastPage
      await loadItems(false, version)
    }
  } catch (error) {
    if (version === contextVersion) ElMessage.error(apiErrorMessage(error, '人工队列读取失败'))
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
  searchQ.value = ''
  riskMode.value = 'all'
  page.value = 1
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
    draftReviewThreshold.value = thresholds.review
    summary.value = {
      pending_review: Number(summaryResponse.data?.pending_review ?? 0),
      confirmed: Number(summaryResponse.data?.confirmed ?? 0),
      unmatched: Number(summaryResponse.data?.unmatched ?? 0),
      automatic_matched: Number(summaryResponse.data?.automatic_matched ?? 0),
    }
    await Promise.all([loadRiskCounts(taskId, version), loadItems(false, version)])
  } catch (error) {
    if (version === contextVersion) ElMessage.error(apiErrorMessage(error, '人工工作台加载失败'))
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

    const reviewCandidates = tasks.filter((task: ReviewTask) => task.status === 'COMPLETED' && task.stage === 'REVIEW')
    reviewRows.value = await Promise.all(reviewCandidates.map((task: ReviewTask) => loadReviewSummary(task)))
    calculatingTask.value = tasks.find((task: ReviewTask) => task.stage === 'CALCULATE' && RUNNING_STATUSES.includes(task.status)) ?? null
    latestFailed.value = tasks.find((task: ReviewTask) => task.status === 'FAILED') ?? null
    calculatingProgress.value = null

    const requestedTaskId = typeof route.query.task === 'string' ? route.query.task : ''
    const requested = actionableTasks.value.find(task => task.id === requestedTaskId)
    const preserved = actionableTasks.value.find(task => task.id === activeTaskId.value)
    const nextTask = requested ?? preserved ?? actionableTasks.value[0] ?? null
    activeTaskId.value = nextTask?.id ?? ''

    if (nextTask) {
      await loadWorkbenchContext(nextTask.id)
    } else {
      ++contextVersion
      workbenchItems.value = []
      workbenchTotal.value = 0
      summary.value = { pending_review: 0, confirmed: 0, unmatched: 0, automatic_matched: 0 }
      if (calculatingTask.value && !hasUnknownReviewState.value) await refreshCalculatingProgress()
    }
  } catch (error) {
    reviewRows.value = []
    activeTaskId.value = ''
    calculatingTask.value = null
    calculatingProgress.value = null
    latestFailed.value = null
    loadError.value = apiErrorMessage(error, 'STEP3 状态读取失败')
  } finally {
    loading.value = false
    startPollingIfNeeded()
  }
}

async function selectTask(taskId: string): Promise<void> {
  const task = actionableTasks.value.find(row => row.id === taskId)
  if (!task) return
  await router.replace({ path: '/review', query: { task: task.id } })
  await loadWorkbenchContext(task.id)
}

function openTask(task: ReviewTask): void {
  void router.push(`/tasks/${task.id}`)
}

function onRiskChange(mode: RiskMode): void {
  riskMode.value = mode
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

function onSelection(rows: WorkbenchItem[]): void {
  selectedRows.value = rows
}

function invalidateThresholdPreview(): void {
  if (thresholdPreviewSignature.value !== currentPreviewSignature.value) thresholdPreview.value = null
}

async function postFirstAvailable(paths: string[], payload: Record<string, unknown>): Promise<{ data: any; path: string } | null> {
  for (const path of paths) {
    try {
      const response = await api.post(path, payload)
      return { data: response.data, path }
    } catch (error) {
      if ([404, 405].includes(errorStatus(error))) continue
      throw error
    }
  }
  return null
}

function normalizeThresholdPreview(data: any): ThresholdPreview {
  const raw = data?.preview ?? data ?? {}
  const rawSummary = raw.summary ?? raw.resulting_summary ?? {}
  const reviewToMatched = Number(raw.review_to_matched ?? raw.promoted_to_matched ?? raw.matched_delta ?? raw.impact?.review_to_matched ?? 0)
  const remainingReview = Number(raw.remaining_review ?? raw.pending_review ?? rawSummary.pending_review ?? raw.impact?.remaining_review ?? summary.value.pending_review)
  const protectedConflicts = Number(raw.protected_conflicts ?? raw.critical_conflicts_blocked ?? raw.critical_conflict_count ?? raw.impact?.protected_conflicts ?? riskCounts.value.conflict)
  const resultingUnmatched = Number(raw.resulting_unmatched ?? raw.unmatched ?? rawSummary.unmatched ?? summary.value.unmatched)
  return {
    exact: true,
    reviewToMatched: Number.isFinite(reviewToMatched) ? reviewToMatched : 0,
    remainingReview: Number.isFinite(remainingReview) ? remainingReview : Number(summary.value.pending_review),
    protectedConflicts: Number.isFinite(protectedConflicts) ? protectedConflicts : Number(riskCounts.value.conflict),
    resultingUnmatched: Number.isFinite(resultingUnmatched) ? resultingUnmatched : Number(summary.value.unmatched),
    note: String(raw.note ?? '后端已按完整任务数据完成预览；正式数据尚未修改。'),
  }
}

async function fallbackThresholdPreview(taskId: string): Promise<ThresholdPreview> {
  const [promoteResponse, conflictResponse] = await Promise.all([
    api.get(`/tasks/${taskId}/workbench/items`, { params: { first_score_min: draftSuccessThreshold.value, critical_conflict: false, page: 1, page_size: 1 } }),
    api.get(`/tasks/${taskId}/workbench/items`, { params: { critical_conflict: true, page: 1, page_size: 1 } }),
  ])
  const promoted = Number(promoteResponse.data?.total ?? 0)
  const protectedConflicts = Number(conflictResponse.data?.total ?? 0)
  return {
    exact: false,
    reviewToMatched: promoted,
    remainingReview: Math.max(0, Number(summary.value.pending_review) - promoted),
    protectedConflicts,
    resultingUnmatched: Number(summary.value.unmatched),
    note: '兼容预览：当前后端 preview 接口尚未部署，仅用服务端筛选对现有 REVIEW 做只读估算。应用时仍由后端对完整未人工处理数据重判。',
  }
}

async function previewThresholds(): Promise<void> {
  const taskId = activeTaskId.value
  if (!taskId || !thresholdValid.value) {
    ElMessage.warning('阈值需满足：0 ≤ 人工确认下限 < 自动匹配阈值 ≤ 100')
    return
  }
  previewBusy.value = true
  try {
    const payload = { success_threshold: draftSuccessThreshold.value, review_threshold: draftReviewThreshold.value }
    const response = await postFirstAvailable([
      `/tasks/${taskId}/workbench/thresholds/preview`,
      `/tasks/${taskId}/thresholds/preview`,
      `/tasks/${taskId}/threshold-preview`,
      `/tasks/${taskId}/re-decide/preview`,
    ], payload)
    thresholdPreview.value = response ? normalizeThresholdPreview(response.data) : await fallbackThresholdPreview(taskId)
    thresholdPreviewSignature.value = currentPreviewSignature.value
  } catch (error) {
    thresholdPreview.value = null
    thresholdPreviewSignature.value = ''
    ElMessage.error(apiErrorMessage(error, '阈值影响预览失败'))
  } finally {
    previewBusy.value = false
  }
}

async function applyThresholds(): Promise<void> {
  const taskId = activeTaskId.value
  if (!taskId || !canApplyThresholds.value || !thresholdPreview.value) return
  try {
    await ElMessageBox.confirm(
      `将自动匹配阈值调整为 ${draftSuccessThreshold.value}，人工确认下限调整为 ${draftReviewThreshold.value}。本操作只会在你确认后修改正式判定结果。`,
      '应用新阈值',
      { confirmButtonText: '确认应用', cancelButtonText: '取消', type: 'warning' },
    )
  } catch {
    return
  }
  applyBusy.value = true
  try {
    const payload = { success_threshold: draftSuccessThreshold.value, review_threshold: draftReviewThreshold.value }
    const response = await postFirstAvailable([
      `/tasks/${taskId}/workbench/thresholds/apply`,
      `/tasks/${taskId}/thresholds/apply`,
      `/tasks/${taskId}/threshold-apply`,
    ], payload)
    if (!response) await api.post(`/tasks/${taskId}/re-decide`, payload)
    currentSuccessThreshold.value = draftSuccessThreshold.value
    currentReviewThreshold.value = draftReviewThreshold.value
    thresholdPreview.value = null
    thresholdPreviewSignature.value = ''
    ElMessage.success('新阈值已应用，人工队列已按最新结果刷新')
    await load()
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '应用新阈值失败'))
  } finally {
    applyBusy.value = false
  }
}

async function batchConfirmHigh(): Promise<void> {
  const base = selectedRows.value.length ? selectedRows.value : workbenchItems.value
  const rows = base.filter(item => riskOf(item) === 'high')
  if (!rows.length) {
    ElMessage.info('当前选择/当前页没有“高分且无冲突”的记录')
    return
  }
  try {
    await ElMessageBox.confirm(`将批量确认 ${rows.length} 条高置信记录的第一候选。`, '批量确认高置信第一候选', { confirmButtonText: '确认', cancelButtonText: '取消', type: 'warning' })
  } catch {
    return
  }
  mutationBusy.value = true
  try {
    const response = (await api.post(`/tasks/${activeTaskId.value}/workbench/batch-confirm-top1`, { source_row_ids: rows.map(row => row.source_row_id) })).data ?? {}
    ElMessage.success(`已确认 ${Number(response.success?.length ?? rows.length)} 条`)
    await refreshAfterMutation()
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '批量确认失败'))
  } finally {
    mutationBusy.value = false
  }
}

async function batchRejectLow(): Promise<void> {
  const base = selectedRows.value.length ? selectedRows.value : workbenchItems.value
  const rows = base.filter(item => riskOf(item) === 'low')
  if (!rows.length) {
    ElMessage.info('当前选择/当前页没有“明显低分”的记录')
    return
  }
  try {
    await ElMessageBox.confirm(`将 ${rows.length} 条明显低分记录标记为未匹配。`, '批量标记明显未匹配', { confirmButtonText: '确认', cancelButtonText: '取消', type: 'warning' })
  } catch {
    return
  }
  mutationBusy.value = true
  try {
    const response = (await api.post(`/tasks/${activeTaskId.value}/workbench/batch-reject`, { source_row_ids: rows.map(row => row.source_row_id) })).data ?? {}
    ElMessage.success(`已标记未匹配 ${Number(response.success?.length ?? rows.length)} 条`)
    await refreshAfterMutation()
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '批量标记未匹配失败'))
  } finally {
    mutationBusy.value = false
  }
}

async function refreshAfterMutation(): Promise<void> {
  const taskId = activeTaskId.value
  if (!taskId) return
  const response = (await api.get(`/tasks/${taskId}/workbench/summary`)).data ?? {}
  summary.value = {
    pending_review: Number(response.pending_review ?? 0),
    confirmed: Number(response.confirmed ?? 0),
    unmatched: Number(response.unmatched ?? 0),
    automatic_matched: Number(response.automatic_matched ?? 0),
  }
  const row = reviewRows.value.find(item => item.id === taskId)
  if (row) row.summary = { ...summary.value }
  if (summary.value.pending_review <= 0) {
    await load()
    return
  }
  await Promise.all([loadRiskCounts(taskId), loadItems(false)])
}

async function openCandidates(item: WorkbenchItem): Promise<void> {
  drawerItem.value = item
  drawerVisible.value = true
  drawerLoading.value = true
  candidateIndex.value = 0
  candidates.value = []
  try {
    const response = (await api.get(`/tasks/${activeTaskId.value}/items/${item.source_row_id}/candidates`)).data ?? {}
    candidates.value = Array.isArray(response.candidates) ? response.candidates : []
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '候选详情读取失败'))
  } finally {
    drawerLoading.value = false
  }
}

async function confirmCandidate(candidate = currentCandidate.value): Promise<void> {
  if (!drawerItem.value || !candidate) return
  mutationBusy.value = true
  try {
    await api.post(`/tasks/${activeTaskId.value}/items/${drawerItem.value.source_row_id}/confirm`, { target_id: candidate.target_group_code, comment: '' })
    ElMessage.success(`已确认候选 ${candidate.target_group_code}`)
    drawerVisible.value = false
    await refreshAfterMutation()
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '确认候选失败'))
  } finally {
    mutationBusy.value = false
  }
}

async function rejectDrawerItem(): Promise<void> {
  if (!drawerItem.value) return
  mutationBusy.value = true
  try {
    await api.post(`/tasks/${activeTaskId.value}/items/${drawerItem.value.source_row_id}/reject`, { comment: '' })
    ElMessage.success('已标记为未匹配')
    drawerVisible.value = false
    await refreshAfterMutation()
  } catch (error) {
    ElMessage.error(apiErrorMessage(error, '标记未匹配失败'))
  } finally {
    mutationBusy.value = false
  }
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
        <h2>STEP 3 · 异常处理工作台</h2>
        <p>自动消化大多数记录，批量处理明显记录，把人工精力留给真正有歧义的小部分。</p>
      </div>
      <div class="review-toolbar-actions">
        <el-select v-if="actionableTasks.length > 1" :model-value="activeTaskId" class="review-task-switcher" placeholder="切换待处理任务" @change="selectTask">
          <el-option v-for="taskRow in actionableTasks" :key="taskRow.id" :label="`${taskRow.name} · ${formatNumber(taskRow.summary?.pending_review)} 条待确认`" :value="taskRow.id" />
        </el-select>
        <el-button :loading="loading" @click="load">刷新状态</el-button>
      </div>
    </div>

    <section v-if="consoleMode !== 'ready'" class="review-console" :class="`is-${consoleMode}`" aria-live="polite">
      <template v-if="consoleMode === 'waiting' && calculatingTask">
        <div class="review-console-main">
          <div class="review-console-kicker"><span class="review-status-dot"></span>STEP2 计算进行中</div>
          <h3>正在等待 STEP2 计算完成</h3>
          <p>当前任务「{{ calculatingTask.name }}」仍在计算。中间结果不会提前进入人工队列，计算完成后这里会自动切换为异常处理工作台。</p>
          <div class="review-console-meta">
            <span>{{ phaseLabel(calculatingProgress?.current_phase) }}</span>
            <span>{{ statusLabel(calculatingProgress?.status ?? calculatingTask.status) }}</span>
            <span v-if="waitingTotal > 0">已处理 {{ formatNumber(waitingProcessed) }} / {{ formatNumber(waitingTotal) }} 行</span>
          </div>
        </div>
        <div class="review-wait-progress">
          <div class="review-wait-percent"><b>{{ waitingPercent }}%</b><span>STEP2 计算进度</span></div>
          <el-progress :percentage="waitingPercent" :stroke-width="10" :show-text="false" />
        </div>
        <div class="review-console-action">
          <el-button type="primary" plain size="large" @click="openTask(calculatingTask)">查看 STEP2 计算进度</el-button>
          <small>当前不可进行人工复核</small>
        </div>
      </template>

      <template v-else-if="consoleMode === 'error'">
        <div class="review-console-main">
          <div class="review-console-kicker"><span class="review-status-dot"></span>状态读取异常</div>
          <h3>暂时无法确认是否存在可人工处理的数据</h3>
          <p>{{ loadError || '部分人工处理汇总读取失败，为避免误导，未把未知状态的任务标记为可处理。' }}</p>
        </div>
        <div class="review-console-action">
          <el-button type="primary" :loading="loading" @click="load">重新读取</el-button>
          <el-button @click="router.push('/tasks')">前往 STEP2</el-button>
        </div>
      </template>

      <template v-else>
        <div class="review-console-main">
          <div class="review-console-kicker"><span class="review-status-dot"></span>暂无待处理数据</div>
          <h3>当前没有真正需要人工判断的记录</h3>
          <p>如果 STEP2 尚未开始，请先启动计算；如果任务已完成且待确认数为 0，可以直接进入 STEP4。</p>
          <div v-if="latestFailed" class="review-failure-note">
            <b>最近失败任务：{{ latestFailed.name }}</b>
            <span>{{ latestFailed.error_message || latestFailed.error_code || '计算失败，未产生可进入 STEP3 的完成数据' }}</span>
            <el-button link type="danger" @click="openTask(latestFailed)">查看失败详情</el-button>
          </div>
        </div>
        <div class="review-console-action review-empty-actions">
          <el-button type="primary" size="large" @click="router.push('/tasks')">前往 STEP2</el-button>
          <el-button size="large" @click="router.push('/results')">查看 STEP4</el-button>
        </div>
      </template>
    </section>

    <template v-if="consoleMode === 'ready' && activeTask">
      <section class="review-task-hero">
        <div>
          <div class="review-console-kicker"><span class="review-status-dot"></span>正在处理 · {{ activeTask.name }}</div>
          <h3>先处理异常类型，再深入到单条候选</h3>
          <p>默认列表只请求后端仍处于 REVIEW 的记录；分页、筛选和搜索全部在服务端执行，不会把全量数据加载到浏览器。</p>
        </div>
        <div class="review-task-hero-meta">
          <span>任务 {{ activeTask.id.slice(0, 12) }}</span>
          <span>完成 {{ formatDate(activeTask.finished_at) }}</span>
        </div>
      </section>

      <section class="review-metric-grid" aria-label="人工处理汇总">
        <div class="review-metric-card"><span>总记录数</span><b>{{ formatNumber(totalRecords) }}</b><small>本任务全部记录</small></div>
        <div class="review-metric-card is-success"><span>自动匹配</span><b>{{ formatNumber(summary.automatic_matched) }}</b><small>无需人工</small></div>
        <div class="review-metric-card is-warning"><span>待确认</span><b>{{ formatNumber(summary.pending_review) }}</b><small>当前人工队列</small></div>
        <div class="review-metric-card"><span>已人工确认</span><b>{{ formatNumber(summary.confirmed) }}</b><small>人工已处理</small></div>
        <div class="review-metric-card"><span>未匹配</span><b>{{ formatNumber(summary.unmatched) }}</b><small>已判定无匹配</small></div>
        <div class="review-metric-card is-danger"><span>关键字段冲突</span><b>{{ riskCountsLoading ? '…' : formatNumber(riskCounts.conflict) }}</b><small>不会自动放行</small></div>
        <div class="review-metric-card is-warning"><span>候选分差过小</span><b>{{ riskCountsLoading ? '…' : formatNumber(riskCounts.gap) }}</b><small>Top1 / Top2 ≤ 5 分</small></div>
      </section>

      <section class="review-strategy-card">
        <div class="review-strategy-head">
          <div>
            <div class="review-section-kicker">判定策略</div>
            <h3>先预览影响，再应用新阈值</h3>
            <p>拖动滑块只修改本地草稿，不会立即改变正式匹配结果。必须先点击“预览影响”，确认后才能应用。</p>
          </div>
          <div class="review-current-thresholds">
            <span>当前自动匹配阈值 <b>{{ currentSuccessThreshold }}</b></span>
            <span>当前人工确认下限 <b>{{ currentReviewThreshold }}</b></span>
          </div>
        </div>

        <div class="review-threshold-editor">
          <div class="review-threshold-control">
            <div class="review-threshold-label"><span>自动匹配阈值</span><b>{{ draftSuccessThreshold }}</b></div>
            <el-slider v-model="draftSuccessThreshold" :min="1" :max="100" :step="1" @input="invalidateThresholdPreview" />
          </div>
          <div class="review-threshold-control">
            <div class="review-threshold-label"><span>人工确认下限</span><b>{{ draftReviewThreshold }}</b></div>
            <el-slider v-model="draftReviewThreshold" :min="0" :max="99" :step="1" @input="invalidateThresholdPreview" />
          </div>
          <div class="review-threshold-actions">
            <el-button type="primary" plain :loading="previewBusy" :disabled="!thresholdValid" @click="previewThresholds">预览影响</el-button>
            <el-button type="primary" :loading="applyBusy" :disabled="!canApplyThresholds" @click="applyThresholds">应用新阈值</el-button>
          </div>
        </div>
        <div v-if="!thresholdValid" class="review-threshold-error">阈值需满足：0 ≤ 人工确认下限 &lt; 自动匹配阈值 ≤ 100。</div>

        <div v-if="thresholdPreview" class="review-impact-preview" :class="{ 'is-estimate': !thresholdPreview.exact }">
          <div class="review-impact-title">
            <div><b>预览结果</b><span>{{ thresholdPreview.exact ? '完整后端预览' : '兼容只读估算' }}</span></div>
            <small>正式数据尚未修改</small>
          </div>
          <div class="review-impact-grid">
            <div><span>REVIEW → MATCHED</span><b>+{{ formatNumber(thresholdPreview.reviewToMatched) }}</b></div>
            <div><span>仍需人工</span><b>{{ formatNumber(thresholdPreview.remainingReview) }}</b></div>
            <div><span>关键冲突保护</span><b>{{ formatNumber(thresholdPreview.protectedConflicts) }}</b></div>
            <div><span>预计未匹配</span><b>{{ formatNumber(thresholdPreview.resultingUnmatched) }}</b></div>
          </div>
          <p>{{ thresholdPreview.note }}</p>
        </div>
      </section>

      <section class="panel review-workbench-panel">
        <div class="review-workbench-head">
          <div>
            <div class="review-section-kicker">异常队列</div>
            <h3>真正需要人判断的记录</h3>
            <p>按风险类别切换，优先批量消化明显记录；只有有歧义的行才进入候选对比。</p>
          </div>
          <div class="review-batch-actions">
            <el-button type="success" plain :loading="mutationBusy" @click="batchConfirmHigh">批量确认高置信第一候选</el-button>
            <el-button type="danger" plain :loading="mutationBusy" @click="batchRejectLow">批量标记明显未匹配</el-button>
          </div>
        </div>

        <div class="review-risk-grid">
          <button v-for="mode in RISK_MODES" :key="mode" type="button" class="review-risk-card" :class="{ 'is-active': riskMode === mode, [`is-${mode}`]: true }" @click="onRiskChange(mode)">
            <span>{{ riskLabel(mode) }}</span>
            <b>{{ riskCountsLoading && mode !== 'all' ? '…' : formatNumber(riskCounts[mode]) }}</b>
            <small>{{ riskHint(mode) }}</small>
          </button>
        </div>

        <div class="review-list-tools">
          <div class="review-search-box">
            <el-input v-model="searchQ" clearable placeholder="搜索物料编码、源数据或第一候选集团码" @keyup.enter="onSearch" @clear="onSearch" />
            <el-button @click="onSearch">搜索</el-button>
          </div>
          <span class="review-selection-hint">已选 {{ selectedRows.length }} 条；未选择时批量按钮仅处理当前页对应风险记录。</span>
        </div>

        <el-table v-loading="listLoading" :data="workbenchItems" size="default" row-key="source_row_id" @selection-change="onSelection">
          <el-table-column type="selection" width="46" />
          <el-table-column prop="source_id" label="源物料" min-width="150" />
          <el-table-column label="源数据摘要" min-width="260">
            <template #default="scope"><span class="review-payload-brief">{{ sourceBrief(scope.row) }}</span></template>
          </el-table-column>
          <el-table-column label="风险" width="150">
            <template #default="scope"><el-tag size="small" :type="riskTagType(riskOf(scope.row))">{{ riskLabel(riskOf(scope.row)) }}</el-tag></template>
          </el-table-column>
          <el-table-column label="第一候选" min-width="150">
            <template #default="scope"><b>{{ scope.row.top1_group_code || '—' }}</b><div class="review-score-sub">{{ formatScore(scope.row.top1_score) }} 分</div></template>
          </el-table-column>
          <el-table-column label="第二候选" width="110">
            <template #default="scope">{{ formatScore(scope.row.second_score) }} 分</template>
          </el-table-column>
          <el-table-column label="分差" width="90">
            <template #default="scope"><b :class="{ 'review-gap-danger': Number(scope.row.score_gap) <= 5 }">{{ formatScore(scope.row.score_gap) }}</b></template>
          </el-table-column>
          <el-table-column label="操作" width="132" fixed="right">
            <template #default="scope"><el-button link type="primary" @click="openCandidates(scope.row)">为什么犹豫？</el-button></template>
          </el-table-column>
          <template #empty><el-empty description="当前风险分类下暂无待处理记录" :image-size="64" /></template>
        </el-table>

        <div class="review-pagination-row">
          <span>服务端分页 · 当前仅渲染 {{ workbenchItems.length }} 条</span>
          <el-pagination background layout="total, sizes, prev, pager, next" :total="workbenchTotal" :current-page="page" :page-size="pageSize" :page-sizes="PAGE_SIZE_OPTIONS" @current-change="onPageChange" @size-change="onPageSizeChange" />
        </div>
      </section>
    </template>

    <section class="panel review-list-panel">
      <div class="section-head">
        <div>
          <h3>人工处理任务记录</h3>
          <p class="review-section-desc">用于切换历史/并行 REVIEW 任务；真正的逐条处理在上方异常工作台完成。</p>
        </div>
      </div>
      <el-table v-if="reviewRows.length" :data="reviewRows" size="default">
        <el-table-column label="名称" min-width="220"><template #default="scope"><a class="row-link" @click="openTask(scope.row)">{{ scope.row.name }}</a><div class="row-sub">{{ scope.row.id }}</div></template></el-table-column>
        <el-table-column label="待确认" width="120"><template #default="scope">{{ scope.row.summaryError ? '—' : formatNumber(scope.row.summary?.pending_review) }}</template></el-table-column>
        <el-table-column label="已人工确认" width="120"><template #default="scope">{{ scope.row.summaryError ? '—' : formatNumber(scope.row.summary?.confirmed) }}</template></el-table-column>
        <el-table-column label="计算完成时间" width="170"><template #default="scope">{{ formatDate(scope.row.finished_at) }}</template></el-table-column>
        <el-table-column label="操作" width="150">
          <template #default="scope">
            <el-button v-if="!scope.row.summaryError && Number(scope.row.summary?.pending_review ?? 0) > 0 && !scope.row.result_file_id" link type="primary" @click="selectTask(scope.row.id)">在工作台处理</el-button>
            <el-button v-else link type="info" @click="openTask(scope.row)">查看任务</el-button>
          </template>
        </el-table-column>
      </el-table>
      <el-empty v-else description="暂无进入过人工处理阶段的任务" :image-size="72" />
    </section>

    <el-drawer v-model="drawerVisible" size="720px" class="review-decision-drawer" :with-header="false" :append-to-body="false">
      <div class="review-drawer" v-loading="drawerLoading">
        <div class="review-drawer-head">
          <div>
            <div class="review-section-kicker">候选解释</div>
            <h3>系统为什么犹豫？</h3>
            <p v-if="drawerItem">源物料 {{ drawerItem.source_id }} · 第一候选 {{ drawerItem.top1_group_code || '—' }}</p>
          </div>
          <el-button circle @click="drawerVisible = false">×</el-button>
        </div>

        <template v-if="drawerItem && !drawerLoading">
          <div class="review-ambiguity-banner" :class="{ 'is-conflict': drawerItem.critical_conflict }">
            <div><span>Top1</span><b>{{ formatScore(drawerItem.top1_score) }}</b></div>
            <div><span>Top2</span><b>{{ formatScore(drawerItem.second_score) }}</b></div>
            <div><span>分差</span><b>{{ formatScore(drawerItem.score_gap) }}</b></div>
            <p v-if="drawerItem.critical_conflict">存在关键字段冲突，即使总分较高也不会自动放行。</p>
            <p v-else-if="Number(drawerItem.score_gap) <= 5">第一、第二候选过于接近，系统无法安全自动决定。</p>
            <p v-else-if="Number(drawerItem.top1_score) < 75">总体证据偏弱，更接近“未匹配”而不是强行选一个候选。</p>
            <p v-else>总体分数处于人工确认区间，需要人确认第一候选是否符合业务语义。</p>
          </div>

          <div v-if="topCandidates.length" class="review-candidate-grid">
            <button v-for="(candidate, index) in topCandidates" :key="candidate.rank" type="button" class="review-candidate-card" :class="{ 'is-selected': candidateIndex === index }" @click="candidateIndex = index">
              <div class="review-candidate-rank">候选 {{ candidate.rank }}</div>
              <strong>{{ candidate.target_group_code }}</strong>
              <div class="review-candidate-score">{{ formatScore(candidate.score) }} <small>分</small></div>
              <el-tag v-if="candidate.critical_conflict" size="small" type="danger">关键冲突</el-tag>
              <span v-else class="review-candidate-safe">无关键冲突</span>
            </button>
          </div>

          <div v-if="candidatePayloadDiffs.length" class="review-evidence-section">
            <div class="review-evidence-title"><h4>第一 / 第二候选差在哪里</h4><span>只展示不同字段</span></div>
            <div class="review-diff-table">
              <div class="review-diff-row review-diff-head"><span>字段</span><span>第一候选</span><span>第二候选</span></div>
              <div v-for="diff in candidatePayloadDiffs" :key="diff.key" class="review-diff-row"><b>{{ diff.key }}</b><span>{{ diff.first }}</span><span>{{ diff.second }}</span></div>
            </div>
          </div>

          <div v-if="currentCandidate" class="review-evidence-section">
            <div class="review-evidence-title"><h4>字段证据</h4><span>当前查看：{{ currentCandidate.target_group_code }}</span></div>
            <div class="review-evidence-summary">
              <span class="is-match">一致 {{ matchingFields.length }}</span>
              <span class="is-conflict">冲突 {{ conflictFields.length }}</span>
              <span class="is-deduction">导致扣分 {{ deductionFields.length }}</span>
            </div>
            <div class="review-field-list">
              <div v-for="field in currentCandidate.field_scores" :key="field.rule_id" class="review-field-row" :class="{ 'is-conflict': field.conflict, 'is-deduction': !field.conflict && Number(field.score) < 99.999 }">
                <div class="review-field-main"><b>{{ field.rule_id }}</b><span>{{ field.source_value || '—' }} → {{ field.target_value || '—' }}</span></div>
                <div class="review-field-flags"><el-tag v-if="field.critical" size="small" type="danger">关键字段</el-tag><el-tag v-if="field.conflict" size="small" type="danger">冲突</el-tag><el-tag v-else-if="Number(field.score) >= 80" size="small" type="success">一致</el-tag><el-tag v-else size="small" type="warning">扣分项</el-tag><span>{{ formatScore(field.score) }} 分 · 权重 {{ formatScore(field.weight) }}<template v-if="Number(field.score) < 99.999"> · 扣分约 {{ deductionPoints(field) }}</template></span></div>
              </div>
            </div>
          </div>

          <div v-if="candidates.length > 2" class="review-more-candidates">
            <span>其他候选</span>
            <el-button v-for="(candidate, index) in candidates.slice(2)" :key="candidate.rank" size="small" :type="candidateIndex === index + 2 ? 'primary' : 'default'" @click="candidateIndex = index + 2">#{{ candidate.rank }} {{ candidate.target_group_code }} · {{ formatScore(candidate.score) }}</el-button>
          </div>

          <div class="review-drawer-actions">
            <el-button type="danger" plain :loading="mutationBusy" @click="rejectDrawerItem">标记未匹配</el-button>
            <el-button type="primary" :loading="mutationBusy" :disabled="!currentCandidate" @click="confirmCandidate()">确认当前候选</el-button>
          </div>
        </template>
      </div>
    </el-drawer>
  </div>
</template>
