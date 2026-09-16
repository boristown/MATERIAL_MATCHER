<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '../api'

type FileRecord = { file_id: string; original_name: string }
type ColumnInfo = { header: string; business_hint?: string | null }
type FieldSide = { fields: string[]; combine: 'concat' | 'coalesce' | 'best_of'; separator: string; pipeline: Array<Record<string, unknown>> }
type Rule = { id: string; source: FieldSide; target: FieldSide; matcher: string; weight: number; critical: boolean; matcher_options: Record<string, unknown> }
type ProfileRow = { profile_id: string; name: string; latest_published_version?: number | null; updated_at?: string }
type WorkbenchItem = { source_row_id: string; source_id: string; source_payload: Record<string, unknown>; top1_group_code?: string | null; top1_score: number; second_score: number; score_gap: number; critical_conflict: boolean; current_status?: string }
type FieldScore = { rule_id: string; score: number; weight: number; source_value: string; target_value: string; critical: boolean; conflict: boolean }
type Candidate = { rank: number; target_group_code: string; score: number; critical_conflict: boolean; target_payload: Record<string, unknown>; field_scores: FieldScore[] }

const route = useRoute(), router = useRouter()

/* ---------- 阶段 ---------- */
const stage = ref(0) // 0配置 1计算 2人工调整 3输出结果
const stageTitles = ['配置', '计算', '人工调整', '输出结果']

/* ---------- 配置:方案与数据 ---------- */
const name = ref('')
const profiles = ref<ProfileRow[]>([])
const appliedProfile = ref<{ id: string; version: number } | null>(null)
const profilePicker = ref('')
const source = ref<FileRecord | null>(null)
const sourceColumns = ref<ColumnInfo[]>([])
const sourceIdColumn = ref('')
const targetMode = ref<'existing' | 'upload'>('existing')
const target = ref<FileRecord | null>(null)
const targetColumns = ref<ColumnInfo[]>([])
const groupCodeColumn = ref('')
const catalogs = ref<any[]>([])
const catalogVersionId = ref('')
const draftId = ref('')
const busy = ref(false)
const embeddingReady = ref(false)

/* ---------- 配置:规则/过滤/阈值 ---------- */
const rules = ref<Rule[]>([])
const scopeMode = ref<'GLOBAL' | 'STRICT' | 'MAPPED'>('GLOBAL')
const scopeSourceField = ref(''), scopeTargetField = ref('')
const filterEnabled = ref(false)
const filterField = ref('')
const filterValues = ref<string[]>([])
const filterMode = ref<'include' | 'exclude'>('include')
const successThreshold = ref(88), reviewThreshold = ref(75), topN = ref(5)
const retrievalMaxLength = ref(256)
const retrievalDocument = ref<Record<string, unknown>>({})
const advanced = ref(false)

/* ---------- 计算 ---------- */
const task = ref<any>(null)
const progress = ref<any>(null)
const liveResults = ref<Array<Record<string, unknown>>>([])
const liveCounts = ref({ matched: 0, review: 0, confirmed: 0, unmatched: 0, matched_group_codes: 0 })
let pollTimer: number | undefined
let pollTicks = 0

/* ---------- 人工调整 ---------- */
const reviewSummary = ref<any>({ pending_review: 0, confirmed: 0, unmatched: 0, automatic_matched: 0 })
const workbenchItems = ref<WorkbenchItem[]>([])
const selectedRows = ref<WorkbenchItem[]>([])
const searchQ = ref('')
const filterMode2 = ref('all')
const thrSuccess = ref(88), thrReview = ref(75)
const redecideBusy = ref(false)
const drawerVisible = ref(false), drawerItem = ref<WorkbenchItem | null>(null)
const candidates = ref<Candidate[]>([]), candidateIndex = ref(0)
const finalized = ref(false)

/* ---------- 连线画布 ---------- */
const canvasRef = ref<HTMLElement | null>(null)
const chipRefs: Record<string, HTMLElement | null> = {}
const linePositions = ref<Array<{ id: string; x1: number; y1: number; x2: number; y2: number }>>([])
const pendingSource = ref<string | null>(null)

function setChipRef(side: string, header: string, el: any): void { chipRefs[`${side}:${header}`] = (el as HTMLElement) ?? null }

const srcHeaders = computed(() => sourceColumns.value.map(column => column.header))
const tgtHeaders = computed(() => targetColumns.value.map(column => column.header))
const idCandidateColumns = computed(() => srcHeaders.value.filter(header => header !== sourceIdColumn.value))

function hintOf(columns: ColumnInfo[], header: string): string {
  return columns.find(column => column.header === header)?.business_hint ?? ''
}

function makeRule(sourceFields: string[], targetFields: string[], matcher: string, weight: number, critical = false): Rule {
  return {
    id: `rule_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`,
    source: { fields: sourceFields, combine: 'concat', separator: ' ', pipeline: [] },
    target: { fields: targetFields, combine: 'concat', separator: ' ', pipeline: [] },
    matcher, weight, critical, matcher_options: {},
  }
}

function normalizeWeights(): void {
  const total = rules.value.reduce((sum, rule) => sum + Number(rule.weight || 0), 0)
  if (total > 0 && total !== 100) {
    let acc = 0
    rules.value.forEach((rule, index) => {
      if (index === rules.value.length - 1) rule.weight = Math.max(0, 100 - acc)
      else { rule.weight = Math.round((Number(rule.weight) / total) * 100); acc += rule.weight }
    })
  }
}

function autoMap(): void {
  const pairs: Array<[string, string, string, number]> = [
    ['material_name', 'material_name', 'hybrid', 40],
    ['model', 'model', 'hybrid', 25],
    ['specification', 'specification', 'fuzzy', 15],
    ['manufacturer', 'manufacturer', 'fuzzy', 10],
    ['material_group', 'material_group', 'exact', 10],
  ]
  const usedTargets = new Set<string>()
  const out: Rule[] = []
  for (const [sourceHint, targetHint, matcher, weight] of pairs) {
    const sCol = sourceColumns.value.find(column => column.business_hint === sourceHint && column.header !== sourceIdColumn.value)
    const tCol = targetColumns.value.find(column => column.business_hint === targetHint && column.header !== groupCodeColumn.value && !usedTargets.has(column.header))
    if (sCol && tCol) { out.push(makeRule([sCol.header], [tCol.header], matcher, weight)); usedTargets.add(tCol.header) }
  }
  for (const sCol of sourceColumns.value) {
    if (out.some(rule => rule.source.fields.includes(sCol.header))) continue
    if (sCol.header === sourceIdColumn.value) continue
    const tCol = targetColumns.value.find(column => column.header === sCol.header && !usedTargets.has(column.header) && column.header !== groupCodeColumn.value)
    if (tCol) { out.push(makeRule([sCol.header], [tCol.header], 'fuzzy', 12)); usedTargets.add(tCol.header) }
  }
  if (!out.length && srcHeaders.value.length && tgtHeaders.value.length) out.push(defaultRule())
  rules.value = out
  normalizeWeights()
  void nextTick(updateLines)
  ElMessage.success(`已根据字段语义自动生成 ${out.length} 条映射,可手动连线调整`)
}

function defaultRule(): Rule {
  const sField = sourceColumns.value.find(column => column.header !== sourceIdColumn.value)?.header ?? srcHeaders.value[0] ?? ''
  const tField = targetColumns.value.find(column => column.header !== groupCodeColumn.value)?.header ?? tgtHeaders.value[0] ?? ''
  return makeRule(sField ? [sField] : [], tField ? [tField] : [], 'hybrid', 100)
}

function onSourceChip(header: string): void {
  pendingSource.value = pendingSource.value === header ? null : header
}
function onTargetChip(header: string): void {
  if (!pendingSource.value) { ElMessage.info('请先点击左侧源字段,再点击右侧目标字段完成连线'); return }
  const existing = rules.value.find(rule => rule.source.fields[0] === pendingSource.value && rule.target.fields[0] === header)
  if (existing) { ElMessage.warning('该连线已存在'); pendingSource.value = null; return }
  rules.value = rules.value.filter(rule => rule.source.fields[0] !== pendingSource.value)
  rules.value.push(makeRule([pendingSource.value], [header], 'hybrid', rules.value.length ? 20 : 100))
  normalizeWeights()
  pendingSource.value = null
  void nextTick(updateLines)
}
function removeRule(ruleId: string): void {
  rules.value = rules.value.filter(rule => rule.id !== ruleId)
  void nextTick(updateLines)
}
function ruleSideLabel(side: FieldSide): string {
  return side.fields.join(side.combine === 'coalesce' ? ' / ' : ' + ')
}

function updateLines(): void {
  const canvas = canvasRef.value
  if (!canvas) { linePositions.value = []; return }
  const box = canvas.getBoundingClientRect()
  const positions: Array<{ id: string; x1: number; y1: number; x2: number; y2: number }> = []
  for (const rule of rules.value) {
    const sKey = `s:${rule.source.fields[0] ?? ''}`
    const tKey = `t:${rule.target.fields[0] ?? ''}`
    const sEl = chipRefs[sKey], tEl = chipRefs[tKey]
    if (!sEl || !tEl) continue
    const sBox = sEl.getBoundingClientRect(), tBox = tEl.getBoundingClientRect()
    positions.push({
      id: rule.id,
      x1: sBox.right - box.left, y1: sBox.top + sBox.height / 2 - box.top,
      x2: tBox.left - box.left, y2: tBox.top + tBox.height / 2 - box.top,
    })
  }
  linePositions.value = positions
}
function linePath(line: { x1: number; y1: number; x2: number; y2: number }): string {
  const dx = Math.max(36, Math.abs(line.x2 - line.x1) / 2)
  return `M ${line.x1} ${line.y1} C ${line.x1 + dx} ${line.y1}, ${line.x2 - dx} ${line.y2}, ${line.x2} ${line.y2}`
}

/* ---------- 数据加载 ---------- */
function columnsFromInspection(inspection: any): ColumnInfo[] {
  return inspection?.sheets?.find((item: any) => item.sheet_name === inspection.recommended_sheet)?.columns ?? []
}
function findHint(columns: ColumnInfo[], hint: string): string {
  return columns.find(column => column.business_hint === hint)?.header ?? ''
}
async function loadFileColumns(fileId: string, kind: 'source' | 'target'): Promise<void> {
  const response = (await api.get(`/files/${fileId}/inspection`)).data
  const columns = columnsFromInspection(response.inspection)
  if (kind === 'source') {
    source.value = response.file
    sourceColumns.value = columns
    if (!sourceIdColumn.value || !columns.some(column => column.header === sourceIdColumn.value)) {
      sourceIdColumn.value = findHint(columns, 'source_id') || columns[0]?.header || ''
    }
    if (!filterField.value) filterField.value = findHint(columns, 'material_group') || findHint(columns, 'material_type') || ''
  } else {
    target.value = response.file
    targetColumns.value = columns
    if (!groupCodeColumn.value || !columns.some(column => column.header === groupCodeColumn.value)) {
      groupCodeColumn.value = findHint(columns, 'group_code') || columns[0]?.header || ''
    }
  }
  void nextTick(updateLines)
}
async function upload(kind: 'source' | 'target', selected: any): Promise<void> {
  busy.value = true
  try {
    const form = new FormData()
    form.append('role', kind)
    form.append('file', selected.raw)
    const response = (await api.post('/files/upload', form)).data
    const columns = columnsFromInspection(response.inspection)
    if (kind === 'source') {
      source.value = response.file
      sourceColumns.value = columns
      sourceIdColumn.value = findHint(columns, 'source_id') || columns[0]?.header || ''
      filterField.value = findHint(columns, 'material_group') || ''
    } else {
      target.value = response.file
      targetColumns.value = columns
      groupCodeColumn.value = findHint(columns, 'group_code') || columns[0]?.header || ''
      targetMode.value = 'upload'
      catalogVersionId.value = ''
    }
    ElMessage.success(`已解析 ${columns.length} 个字段`)
    if (source.value && target.value && !rules.value.length) autoMap()
    void nextTick(updateLines)
  } catch (error) { ElMessage.error((error as Error).message) } finally { busy.value = false }
}
async function loadCatalogs(): Promise<void> {
  catalogs.value = ((await api.get('/catalogs')).data ?? []).filter((item: any) => item.status === 'READY')
    .sort((a: any, b: any) => Number(b.active) - Number(a.active) || String(b.created_at).localeCompare(String(a.created_at)))
  if (!catalogVersionId.value && catalogs.value.length) catalogVersionId.value = catalogs.value[0].version_id
  if (catalogVersionId.value) await selectCatalog(catalogVersionId.value)
}
async function selectCatalog(versionId: string): Promise<void> {
  const catalog = catalogs.value.find((item: any) => item.version_id === versionId)
  if (!catalog) return
  groupCodeColumn.value = catalog.group_code_column
  try { await loadFileColumns(catalog.source_file_id, 'target') } catch (error) { ElMessage.error((error as Error).message) }
}
async function loadProfiles(): Promise<void> {
  try { profiles.value = (await api.get('/profiles')).data ?? [] } catch { profiles.value = [] }
}
async function applyProfile(profileId: string): Promise<void> {
  if (!profileId) return
  const versions = (await api.get(`/profiles/${profileId}/versions`)).data as any[]
  const published = versions.find(item => item.status === 'PUBLISHED') ?? versions[0]
  if (!published) { ElMessage.warning('该方案没有可用版本'); return }
  loadDocument(published.document ?? {})
  appliedProfile.value = { id: profileId, version: Number(published.version_no) }
  name.value = name.value || (profiles.value.find(item => item.profile_id === profileId)?.name ?? '')
  ElMessage.success(`已应用方案「${profiles.value.find(item => item.profile_id === profileId)?.name ?? profileId}」v${published.version_no},字段映射与阈值已载入`)
  void nextTick(updateLines)
}
function loadDocument(document: any): void {
  if (!document || typeof document !== 'object') return
  if (Array.isArray(document.rules) && document.rules.length) rules.value = document.rules
  if (document.source_id_column && sourceColumns.value.some(column => column.header === document.source_id_column)) sourceIdColumn.value = document.source_id_column
  scopeMode.value = document.scope_mode ?? 'GLOBAL'
  scopeSourceField.value = document.scope?.source_field ?? ''
  scopeTargetField.value = document.scope?.target_field ?? ''
  successThreshold.value = Number(document.decision?.success_threshold ?? 88)
  reviewThreshold.value = Number(document.decision?.review_threshold ?? 75)
  topN.value = Number(document.decision?.top_n ?? 5)
  thrSuccess.value = successThreshold.value
  thrReview.value = reviewThreshold.value
  retrievalMaxLength.value = Number(document.retrieval?.max_length ?? 256)
  retrievalDocument.value = { ...(document.retrieval ?? {}) }
  const flt = document.source_filter
  if (flt && flt.field) { filterEnabled.value = true; filterField.value = flt.field; filterValues.value = Array.isArray(flt.values) ? flt.values.map(String) : []; filterMode.value = flt.mode === 'exclude' ? 'exclude' : 'include' }
}
function documentBody(): Record<string, unknown> {
  const retrieval = { mode: 'auto', provider: 'onnx_local', model_id: 'BAAI/bge-base-zh-v1.5', dimensions: 768, max_length: retrievalMaxLength.value, precision: 'fp32', retrieval_top_k: 200, oversample: 4, ...(retrievalDocument.value ?? {}) }
  return {
    source_id_column: sourceIdColumn.value || null,
    scope_mode: scopeMode.value,
    scope: { source_field: scopeSourceField.value || null, target_field: scopeTargetField.value || null, mapping: {} },
    source_filter: filterEnabled.value && filterField.value && filterValues.value.length ? { field: filterField.value, values: filterValues.value, mode: filterMode.value, match: 'exact' } : null,
    rules: rules.value,
    decision: { success_threshold: successThreshold.value, review_enabled: true, review_threshold: reviewThreshold.value, top_n: topN.value },
    retrieval,
    advanced: {},
  }
}
const configValid = computed(() => Boolean(source.value) && Boolean(sourceIdColumn.value) && (targetMode.value === 'existing' ? Boolean(catalogVersionId.value) : Boolean(target.value && groupCodeColumn.value)) && rules.value.length > 0 && reviewThreshold.value < successThreshold.value)

async function ensureDraft(): Promise<void> {
  if (draftId.value) return
  const draft = (await api.post('/task-drafts', { name: name.value || '未命名匹配任务' })).data
  draftId.value = draft.draft_id
}
async function saveConfig(): Promise<void> {
  await ensureDraft()
  let versionId = catalogVersionId.value
  if (targetMode.value === 'upload') {
    if (!target.value || !groupCodeColumn.value) throw new Error('请先上传集团码文件并选择集团码列')
    const existing = catalogs.value.find((item: any) => item.source_file_id === target.value!.file_id)
    if (existing) versionId = existing.version_id
    else {
      const catalog = (await api.post('/catalogs', { name: `${name.value || '任务'}-集团码目录`, source_file_id: target.value.file_id, group_code_column: groupCodeColumn.value })).data
      versionId = catalog.version_id
      await loadCatalogs()
    }
  }
  await api.put(`/task-drafts/${draftId.value}/data`, {
    source_file_id: source.value!.file_id,
    catalog_version_id: versionId,
    template_profile_id: appliedProfile.value?.id ?? null,
    template_profile_version: appliedProfile.value?.version ?? null,
  })
  await api.put(`/task-drafts/${draftId.value}/rules`, documentBody())
}
async function saveAsProfile(): Promise<void> {
  if (!rules.value.length) { ElMessage.warning('请先完成字段映射'); return }
  try {
    const { value } = await ElMessageBox.prompt('方案名称(发布后不可变,可被任务复用)', '存为匹配方案', { inputValue: name.value || '', confirmButtonText: '校验并发布', cancelButtonText: '取消' })
    const created = (await api.post('/profiles', { name: value.trim() || `方案-${Date.now()}`, document: documentBody() })).data
    await api.post(`/profiles/${created.profile_id}/validate`)
    await api.post(`/profiles/${created.profile_id}/publish`)
    await loadProfiles()
    ElMessage.success('方案已发布,可在新建任务时直接选用')
  } catch (error) { if (error !== 'cancel') ElMessage.error((error as Error).message ?? '保存失败') }
}
async function dryRun(): Promise<void> {
  busy.value = true
  try {
    await saveConfig()
    const response = (await api.post(`/task-drafts/${draftId.value}/dry-run`, { sample_rows: 100 })).data
    ElMessage.success(`试算完成:自动 ${response.summary?.matched ?? 0} · 待确认 ${response.summary?.review ?? 0} · 未匹配 ${response.summary?.unmatched ?? 0}`)
  } catch (error) { ElMessage.error((error as Error).message) } finally { busy.value = false }
}
async function start(): Promise<void> {
  if (!configValid.value) return
  busy.value = true
  try {
    await saveConfig()
    task.value = (await api.post(`/task-drafts/${draftId.value}/start`)).data
    stage.value = 1
    await router.replace(`/tasks/${task.value.task_id}`)
    startPolling()
  } catch (error) { ElMessage.error((error as Error).message) } finally { busy.value = false }
}

/* ---------- 计算:实时看板 ---------- */
function fmtDuration(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(seconds) || seconds < 0) return '估算中'
  const total = Math.round(seconds)
  if (total < 60) return `${total} 秒`
  if (total < 3600) return `${Math.floor(total / 60)} 分 ${total % 60} 秒`
  return `${Math.floor(total / 3600)} 小时 ${Math.floor((total % 3600) / 60)} 分`
}
function fmtClock(iso: string | null | undefined): string {
  if (!iso) return '—'
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? '—' : `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`
}
function elapsedSeconds(startedAt: string | null | undefined): number | null {
  if (!startedAt) return null
  const started = new Date(startedAt).getTime()
  return Number.isNaN(started) ? null : Math.max(0, (Date.now() - started) / 1000)
}
const statusLabel = computed(() => ({ PENDING: '排队中', PREPARING: '准备中', RECOVERING: '重启恢复中', RUNNING: '运行中', COMPLETED: '已完成', FAILED: '失败' }[String(task.value?.status ?? '')] ?? String(task.value?.status ?? '')))
const phaseLabel = computed(() => ({ INDEX: '构建向量索引(首次建库较慢,索引就绪后长期复用)', RETRIEVE: '候选召回', RERANK: '实时逐条匹配与精细评分', PERSIST: '结果持久化', DONE: '已完成', WAITING: '等待调度', FAILED: '失败', RECOVERING: '恢复中' }[String(progress.value?.current_phase ?? '')] ?? '准备中'))
const isInterim = computed(() => Boolean(progress.value?.interim))
const liveProgressPercent = computed(() => Math.round(Number(progress.value?.progress ?? task.value?.progress ?? 0)))

function stopPolling(): void { if (pollTimer) window.clearInterval(pollTimer); pollTimer = undefined }
function startPolling(): void { stopPolling(); pollTicks = 0; void pollProgress(); pollTimer = window.setInterval(() => void pollProgress(), 1000) }
async function pollLiveResults(): Promise<void> {
  try {
    const response = (await api.get(`/tasks/${task.value.task_id}/live-results`, { params: { limit: 10 } })).data
    liveResults.value = response.rows ?? []
    liveCounts.value = response.counts ?? liveCounts.value
  } catch { /* 忽略瞬时错误 */ }
}
async function pollProgress(): Promise<void> {
  if (!task.value?.task_id) return
  try {
    progress.value = (await api.get(`/tasks/${task.value.task_id}/progress`)).data
    liveCounts.value = progress.value?.live_counts ?? liveCounts.value
    pollTicks += 1
    if (pollTicks % 5 === 1) void pollLiveResults()
    task.value = (await api.get(`/tasks/${task.value.task_id}`)).data
    if (task.value.status === 'FAILED') { stopPolling(); ElMessage.error(task.value.error_message || '比对计算失败') }
    else if (task.value.status === 'COMPLETED') { stopPolling(); await enterStage2Or3() }
  } catch (error) { stopPolling(); ElMessage.error((error as Error).message) }
}
async function enterStage2Or3(): Promise<void> {
  await loadReviewSummary()
  finalized.value = Boolean(task.value?.result_file_id) || task.value?.stage === 'RESULT'
  if ((reviewSummary.value.pending_review ?? 0) > 0 && !finalized.value) { stage.value = 2; await loadWorkbench() }
  else { stage.value = 3 }
}

/* ---------- 人工调整 ---------- */
async function loadReviewSummary(): Promise<void> {
  if (!task.value?.task_id) return
  reviewSummary.value = (await api.get(`/tasks/${task.value.task_id}/workbench/summary`)).data
}
function filterParams(): Record<string, unknown> {
  const params: Record<string, unknown> = {}
  if (searchQ.value.trim()) params.q = searchQ.value.trim()
  if (filterMode2.value === 'high') { params.first_score_min = 90; params.critical_conflict = false }
  else if (filterMode2.value === '80-90') { params.first_score_min = 80; params.first_score_max = 90 }
  else if (filterMode2.value === 'gap') params.gap_max = 5
  else if (filterMode2.value === 'conflict') params.critical_conflict = true
  return params
}
async function loadWorkbench(): Promise<void> {
  if (!task.value?.task_id) return
  const [summaryResponse, itemsResponse] = await Promise.all([
    api.get(`/tasks/${task.value.task_id}/workbench/summary`),
    api.get(`/tasks/${task.value.task_id}/workbench/items`, { params: { ...filterParams(), page: 1, page_size: 100 } }),
  ])
  reviewSummary.value = summaryResponse.data
  workbenchItems.value = itemsResponse.data.items
  selectedRows.value = []
}
let searchTimer: number | undefined
watch(searchQ, () => { if (searchTimer) window.clearTimeout(searchTimer); searchTimer = window.setTimeout(() => void loadWorkbench().catch(() => undefined), 350) })
function onSelection(rows: WorkbenchItem[]): void { selectedRows.value = rows }
async function openCandidates(item: WorkbenchItem): Promise<void> {
  drawerItem.value = item
  const response = (await api.get(`/tasks/${task.value.task_id}/items/${item.source_row_id}/candidates`)).data
  candidates.value = response.candidates
  candidateIndex.value = 0
  drawerVisible.value = true
}
const currentCandidate = computed(() => candidates.value[candidateIndex.value] ?? null)
async function confirmCandidate(item: WorkbenchItem, targetId?: string): Promise<void> {
  const value = targetId || (item.top1_group_code ? String(item.top1_group_code) : '')
  if (!value) return
  await api.post(`/tasks/${task.value.task_id}/items/${item.source_row_id}/confirm`, { target_id: value, comment: '' })
  await loadWorkbench(); ElMessage.success('已确认')
}
async function rejectItem(item: WorkbenchItem): Promise<void> {
  await api.post(`/tasks/${task.value.task_id}/items/${item.source_row_id}/reject`, { comment: '' })
  await loadWorkbench(); ElMessage.success('已标记未匹配')
}
async function confirmFromDrawer(): Promise<void> {
  if (!drawerItem.value || !currentCandidate.value) return
  await confirmCandidate(drawerItem.value, currentCandidate.value.target_group_code)
  if (workbenchItems.value.length) await openCandidates(workbenchItems.value[0]); else drawerVisible.value = false
}
async function rejectFromDrawer(): Promise<void> {
  if (!drawerItem.value) return
  await rejectItem(drawerItem.value)
  if (workbenchItems.value.length) await openCandidates(workbenchItems.value[0]); else drawerVisible.value = false
}
async function batchConfirm(): Promise<void> {
  if (!selectedRows.value.length) return
  const response = (await api.post(`/tasks/${task.value.task_id}/workbench/batch-confirm-top1`, { source_row_ids: selectedRows.value.map(row => row.source_row_id) })).data
  await loadWorkbench(); ElMessage.success(`已确认 ${response.success.length} 条`)
}
async function batchReject(): Promise<void> {
  if (!selectedRows.value.length) return
  const response = (await api.post(`/tasks/${task.value.task_id}/workbench/batch-reject`, { source_row_ids: selectedRows.value.map(row => row.source_row_id) })).data
  await loadWorkbench(); ElMessage.success(`已标记未匹配 ${response.success.length} 条`)
}
async function reDecide(): Promise<void> {
  redecideBusy.value = true
  try {
    const response = (await api.post(`/tasks/${task.value.task_id}/re-decide`, { success_threshold: thrSuccess.value, review_threshold: thrReview.value })).data
    await loadWorkbench()
    ElMessage.success(`重判完成:自动匹配 ${response.summary.automatic_matched} · 待确认 ${response.summary.pending_review} · 未匹配 ${response.summary.unmatched}`)
  } catch (error) { ElMessage.error((error as Error).message) } finally { redecideBusy.value = false }
}

/* ---------- 输出结果 ---------- */
const finalTotal = computed(() => Number(reviewSummary.value.pending_review ?? 0) + Number(reviewSummary.value.confirmed ?? 0) + Number(reviewSummary.value.unmatched ?? 0) + Number(reviewSummary.value.automatic_matched ?? 0))
async function finalize(): Promise<void> {
  await loadReviewSummary()
  let allow = false
  if (Number(reviewSummary.value.pending_review ?? 0) > 0) {
    try { await ElMessageBox.confirm(`仍有 ${reviewSummary.value.pending_review} 条待确认。继续生成后这些行集团码为空。`, '生成最终结果', { confirmButtonText: '继续生成', cancelButtonText: '返回处理', type: 'warning' }); allow = true } catch { return }
  }
  try {
    await api.post(`/tasks/${task.value.task_id}/finalize`, { allow_unresolved_review: allow })
    task.value = (await api.get(`/tasks/${task.value.task_id}`)).data
    finalized.value = true
    await loadReviewSummary()
    ElMessage.success('最终结果已生成(含匹配摘要与样式)')
  } catch (error) { ElMessage.error((error as Error).message) }
}
function downloadResult(): void { window.location.href = `/api/tasks/${task.value.task_id}/result` }

/* ---------- 恢复 ---------- */
async function restoreDraft(id: string): Promise<void> {
  const draft = (await api.get(`/task-drafts/${id}`)).data
  draftId.value = draft.draft_id
  name.value = draft.name
  if (draft.source_file_id) await loadFileColumns(String(draft.source_file_id), 'source')
  if (draft.catalog_version_id) {
    catalogVersionId.value = String(draft.catalog_version_id)
    targetMode.value = 'existing'
    await selectCatalog(catalogVersionId.value)
  }
  loadDocument(draft.config_document ?? {})
  if (draft.template_profile_id) appliedProfile.value = { id: String(draft.template_profile_id), version: Number(draft.template_profile_version ?? 1) }
  stage.value = 0
}
async function restoreTask(taskId: string): Promise<void> {
  task.value = (await api.get(`/tasks/${taskId}`)).data
  name.value = task.value.name
  loadDocument(task.value.config_snapshot ?? {})
  if (task.value.source_file_id) await loadFileColumns(String(task.value.source_file_id), 'source').catch(() => undefined)
  if (task.value.catalog_version_id) { catalogVersionId.value = String(task.value.catalog_version_id); await selectCatalog(catalogVersionId.value).catch(() => undefined) }
  if (task.value.status === 'COMPLETED') { await enterStage2Or3() }
  else if (task.value.status === 'FAILED') { stage.value = 1 }
  else { stage.value = 1; startPolling() }
}

watch([rules, scopeMode, successThreshold, reviewThreshold, topN], () => void nextTick(updateLines), { deep: true })
onMounted(async () => {
  window.addEventListener('resize', updateLines)
  try {
    const status = (await api.get('/system/vector-status')).data
    embeddingReady.value = Boolean(status.embedding?.ready)
  } catch { embeddingReady.value = false }
  await Promise.all([loadCatalogs(), loadProfiles()])
  const profileParam = typeof route.query.profile === 'string' ? route.query.profile : ''
  if (profileParam) { profilePicker.value = profileParam; await applyProfile(profileParam).catch(() => undefined) }
  if (route.params.taskId) { await restoreTask(String(route.params.taskId)).catch(() => router.push('/tasks')); return }
  const draft = typeof route.query.draft === 'string' ? route.query.draft : ''
  if (draft) { await restoreDraft(draft).catch(() => undefined) }
})
onBeforeUnmount(() => { stopPolling(); window.removeEventListener('resize', updateLines) })
</script>

<template>
  <div class="wizard">
    <div class="toolbar">
      <div>
        <h2>{{ name || '新建匹配任务' }}</h2>
        <p>配置(数据+字段映射) → 计算(实时进度) → 人工调整 → 输出结果</p>
      </div>
      <div class="toolbar-actions">
        <el-select v-model="profilePicker" placeholder="选用已发布方案…" clearable filterable style="width:280px" @change="applyProfile">
          <el-option v-for="item in profiles" :key="item.profile_id" :value="item.profile_id" :label="`${item.name}${item.latest_published_version ? ' · v' + item.latest_published_version : ''}`"/>
        </el-select>
        <el-button @click="saveAsProfile">存为方案</el-button>
      </div>
    </div>
    <el-steps :active="stage" align-center finish-status="success" class="stage-steps">
      <el-step v-for="(title, index) in stageTitles" :key="title" :title="`${index + 1}. ${title}`" :status="index < stage ? 'success' : index === stage ? 'process' : 'wait'"/>
    </el-steps>

    <!-- 第一步:配置 -->
    <template v-if="stage === 0">
      <div class="panel">
        <h3>① 数据</h3>
        <div class="uploads">
          <div class="upload-card">
            <b>源数据(SAP 物料)</b>
            <el-upload drag :auto-upload="false" :show-file-list="false" :on-change="(file:any)=>upload('source',file)" accept=".xlsx,.xlsm,.csv">
              <div class="upload-inner"><span class="upload-icon">⬆</span><div>拖入 Excel / CSV,自动解析字段</div><small v-if="source" class="ok">{{ source.original_name }} · {{ sourceColumns.length }} 字段</small></div>
            </el-upload>
            <el-select v-if="sourceColumns.length" v-model="sourceIdColumn" placeholder="物料编码列">
              <el-option v-for="column in srcHeaders" :key="column" :label="column" :value="column"/>
            </el-select>
          </div>
          <div class="upload-card">
            <b>目标数据(集团码)</b>
            <el-radio-group v-model="targetMode" size="small" class="target-mode">
              <el-radio-button value="existing">选择已有目录</el-radio-button>
              <el-radio-button value="upload">拖入新文件</el-radio-button>
            </el-radio-group>
            <el-select v-if="targetMode==='existing'" v-model="catalogVersionId" filterable placeholder="选择集团码目录版本" @change="selectCatalog">
              <el-option v-for="item in catalogs" :key="item.version_id" :value="item.version_id" :label="`${item.name}${item.active ? ' · 当前' : ''} · ${item.version_id.slice(0,8)}`"/>
            </el-select>
            <el-upload v-else drag :auto-upload="false" :show-file-list="false" :on-change="(file:any)=>upload('target',file)" accept=".xlsx,.xlsm,.csv">
              <div class="upload-inner"><span class="upload-icon">⬆</span><div>拖入集团码 Excel / CSV</div><small v-if="target" class="ok">{{ target.original_name }} · {{ targetColumns.length }} 字段</small></div>
            </el-upload>
            <el-select v-if="targetColumns.length" v-model="groupCodeColumn" placeholder="集团码列">
              <el-option v-for="column in tgtHeaders" :key="column" :label="column" :value="column"/>
            </el-select>
          </div>
        </div>
      </div>

      <div class="panel">
        <div class="section-head">
          <h3 style="margin:0">② 字段映射(点击左侧字段 → 点击右侧字段即连线)</h3>
          <div>
            <el-button size="small" type="primary" plain :disabled="!sourceColumns.length || !targetColumns.length" @click="autoMap">自动识别映射</el-button>
            <el-button size="small" :disabled="!sourceColumns.length || !targetColumns.length" @click="rules.push(defaultRule()); normalizeWeights()">手动加一条</el-button>
          </div>
        </div>
        <div v-if="!sourceColumns.length || !targetColumns.length" class="canvas-empty">
          <el-empty description="先在上方拖入源数据与目标数据,字段清单会自动解析到这里" :image-size="70"/>
        </div>
        <div v-else ref="canvasRef" class="mapping-canvas">
          <svg class="lines" :style="{width:'100%',height:'100%'}">
            <path v-for="line in linePositions" :key="line.id" :d="linePath(line)" class="map-line" :class="{critical: rules.find(r=>r.id===line.id)?.critical}"/>
          </svg>
          <div class="field-col">
            <div class="field-col-title">源字段(SAP)</div>
            <div v-for="column in sourceColumns" :key="'s'+column.header" :ref="el=>setChipRef('s', column.header, el)" class="field-chip" :class="{selected: pendingSource===column.header, used: rules.some(r=>r.source.fields.includes(column.header)), idcol: column.header===sourceIdColumn}" @click="column.header!==sourceIdColumn && onSourceChip(column.header)">
              {{ column.header }}<em v-if="column.business_hint" class="hint">{{ {source_id:'编码',material_name:'名称',model:'型号',specification:'规格',manufacturer:'厂商',material_group:'物料组',group_code:'集团码'}[column.business_hint] ?? '' }}</em>
            </div>
          </div>
          <div class="field-col">
            <div class="field-col-title">目标字段(集团码)</div>
            <div v-for="column in targetColumns" :key="'t'+column.header" :ref="el=>setChipRef('t', column.header, el)" class="field-chip right" :class="{used: rules.some(r=>r.target.fields.includes(column.header)), idcol: column.header===groupCodeColumn}" @click="column.header!==groupCodeColumn && onTargetChip(column.header)">
              {{ column.header }}<em v-if="column.business_hint" class="hint">{{ {source_id:'编码',material_name:'名称',model:'型号',specification:'规格',manufacturer:'厂商',material_group:'物料组',group_code:'集团码'}[column.business_hint] ?? '' }}</em>
            </div>
          </div>
        </div>
        <el-table v-if="rules.length" :data="rules" size="small" class="rules-table">
          <el-table-column label="源字段" min-width="180"><template #default="scope"><span class="chip-text">{{ ruleSideLabel(scope.row.source) }}</span></template></el-table-column>
          <el-table-column label="" width="46"><template #default>➜</template></el-table-column>
          <el-table-column label="目标字段" min-width="180"><template #default="scope"><span class="chip-text">{{ ruleSideLabel(scope.row.target) }}</span></template></el-table-column>
          <el-table-column label="匹配方式" width="150"><template #default="scope">
            <el-select v-model="scope.row.matcher" size="small">
              <el-option label="完全一致" value="exact"/><el-option label="包含" value="contains"/><el-option label="模糊相似" value="fuzzy"/><el-option label="综合(字符+语义)" value="hybrid"/><el-option :label="embeddingReady?'语义相似(bge)':'语义(模型未就绪)'" value="semantic" :disabled="!embeddingReady"/>
            </el-select>
          </template></el-table-column>
          <el-table-column label="权重" width="130"><template #default="scope"><el-input-number v-model="scope.row.weight" size="small" :min="0" :max="100" controls-position="right"/></template></el-table-column>
          <el-table-column label="关键" width="70"><template #default="scope"><el-switch v-model="scope.row.critical" size="small"/></template></el-table-column>
          <el-table-column label="" width="60"><template #default="scope"><el-button link type="danger" size="small" @click="removeRule(scope.row.id)">删除</el-button></template></el-table-column>
        </el-table>
      </div>

      <div class="panel">
        <h3>③ 过滤与阈值</h3>
        <div class="filter-row">
          <el-switch v-model="filterEnabled"/><span>仅处理满足条件的源数据行</span>
          <template v-if="filterEnabled">
            <el-select v-model="filterField" placeholder="字段" style="width:180px" filterable>
              <el-option v-for="column in srcHeaders" :key="column" :label="column" :value="column"/>
            </el-select>
            <el-radio-group v-model="filterMode" size="small"><el-radio-button value="include">等于其中之一</el-radio-button><el-radio-button value="exclude">排除</el-radio-button></el-radio-group>
            <el-select v-model="filterValues" multiple filterable allow-create default-first-option placeholder="输入值后回车,如 Z001" style="width:320px">
              <el-option v-for="value in filterValues" :key="value" :label="value" :value="value"/>
            </el-select>
            <span class="muted">例:物料类型只匹配 Z001;或本次仅处理 A006</span>
          </template>
        </div>
        <div class="threshold">
          <span>自动匹配阈值 ≥</span><el-slider v-model="successThreshold" :min="1" :max="100" style="width:180px"/>
          <span>人工确认下限 ≥</span><el-slider v-model="reviewThreshold" :min="0" :max="99" style="width:180px"/>
          <span>候选 TopN</span><el-input-number v-model="topN" :min="1" :max="50" size="small"/>
        </div>
        <h4 class="click" @click="advanced=!advanced">高级(向量检索参数){{ advanced ? ' ▲' : ' ▼' }}</h4>
        <div v-if="advanced" class="threshold">
          <span>max_length</span>
          <el-select v-model="retrievalMaxLength" style="width:110px"><el-option :value="128" label="128"/><el-option :value="192" label="192"/><el-option :value="256" label="256"/><el-option :value="512" label="512"/></el-select>
          <span class="muted">匹配范围</span>
          <el-select v-model="scopeMode" style="width:150px"><el-option label="全库匹配" value="GLOBAL"/><el-option label="同组匹配" value="STRICT"/><el-option label="分类映射" value="MAPPED"/></el-select>
          <template v-if="scopeMode!=='GLOBAL'">
            <el-select v-model="scopeSourceField" placeholder="源分类字段" style="width:160px"><el-option v-for="column in srcHeaders" :key="column" :label="column" :value="column"/></el-select>
            <el-select v-model="scopeTargetField" placeholder="目标分类字段" style="width:160px"><el-option v-for="column in tgtHeaders" :key="column" :label="column" :value="column"/></el-select>
          </template>
        </div>
        <div class="actions">
          <el-button :loading="busy" :disabled="!configValid" @click="dryRun">试算 100 条</el-button>
          <el-button type="primary" :loading="busy" :disabled="!configValid" @click="start">开始匹配 →</el-button>
        </div>
      </div>
    </template>

    <!-- 第二步:计算 -->
    <div v-else-if="stage === 1" class="panel">
      <h3>实时计算<span v-if="isInterim" class="live-dot">●</span><span v-if="isInterim" class="live-tag">中间结果实时更新</span></h3>
      <div class="progress-board">
        <div class="progress-main">
          <el-progress type="dashboard" :width="180" :percentage="liveProgressPercent" :status="task?.status==='FAILED'?'exception':task?.status==='COMPLETED'?'success':''">
            <template #default><div class="dash-inner"><b>{{ liveProgressPercent }}%</b><span>{{ statusLabel }}</span></div></template>
          </el-progress>
          <p class="phase-line">{{ phaseLabel }}</p>
          <p class="muted">已处理 {{ progress?.processed_rows ?? task?.processed_rows ?? 0 }} / {{ progress?.total_rows || task?.total_rows || '待统计' }} 行</p>
        </div>
        <div class="progress-stats">
          <div class="stat-card primary"><span>已匹配集团码</span><b>{{ Number(liveCounts.matched_group_codes ?? 0).toLocaleString() }}</b></div>
          <div class="stat-card"><span>待人工确认</span><b>{{ Number(liveCounts.review ?? 0).toLocaleString() }}</b></div>
          <div class="stat-card"><span>未匹配</span><b>{{ Number(liveCounts.unmatched ?? 0).toLocaleString() }}</b></div>
          <div class="stat-card"><span>吞吐</span><b>{{ progress?.estimate?.rows_per_minute ? Number(progress.estimate.rows_per_minute).toFixed(0) : '—' }} <i>行/分钟</i></b></div>
          <div class="stat-card"><span>已用时</span><b>{{ fmtDuration(elapsedSeconds(progress?.started_at ?? task?.started_at)) }}</b></div>
          <div class="stat-card accent"><span>{{ progress?.current_phase === 'INDEX' ? '本阶段预计还需' : '预计剩余' }}</span><b>{{ progress?.current_phase === 'INDEX' ? fmtDuration(progress?.estimate?.phase_remaining_seconds) : fmtDuration(progress?.estimate?.eta_seconds) }}</b><i v-if="progress?.estimate?.eta_at">完成约 {{ fmtClock(progress.estimate.eta_at) }}</i></div>
        </div>
      </div>
      <el-steps v-if="progress?.steps?.length" align-center class="flow-steps">
        <el-step v-for="step in progress.steps" :key="step.key" :title="step.label" :status="step.status==='DONE'?'success':step.status==='RUNNING'?'process':step.status==='FAILED'?'error':'wait'" :description="step.status==='SKIPPED'?'无需':step.status==='RUNNING'?'进行中':step.status==='DONE'?'完成':step.status==='FAILED'?'失败':'等待'"/>
      </el-steps>
      <div class="live-block">
        <div class="live-head"><b>最新处理结果</b><span class="muted">约每秒刷新</span></div>
        <el-table :data="liveResults" size="small" max-height="280" :empty-text="isInterim?'正在计算首批结果…':'暂无'">
          <el-table-column prop="source_id" label="物料编码" min-width="150"/>
          <el-table-column prop="top1_group_code" label="集团码" min-width="130"/>
          <el-table-column label="得分" width="80"><template #default="scope">{{ Number(scope.row.top1_score ?? 0).toFixed(1) }}</template></el-table-column>
          <el-table-column label="判定" width="100"><template #default="scope"><el-tag size="small" :type="scope.row.current_status==='MATCHED'?'success':scope.row.current_status==='REVIEW'?'warning':'info'">{{ {MATCHED:'自动匹配',REVIEW:'待确认',UNMATCHED:'未匹配',CONFIRMED:'已确认'}[String(scope.row.current_status)] ?? scope.row.current_status }}</el-tag></template></el-table-column>
        </el-table>
      </div>
      <el-alert v-if="task?.status==='FAILED'" :title="task.error_message || '比对失败'" type="error" :closable="false"/>
      <div class="actions"><el-button @click="router.push('/tasks')">返回列表</el-button><el-button type="primary" :disabled="task?.status!=='COMPLETED'" @click="enterStage2Or3">下一步:人工调整 →</el-button></div>
    </div>

    <!-- 第三步:人工调整 -->
    <div v-else-if="stage === 2" class="panel">
      <div class="section-head">
        <h3 style="margin:0">人工调整(待确认 {{ reviewSummary.pending_review ?? 0 }})</h3>
        <el-input v-model="searchQ" placeholder="按物料编码/描述/集团码模糊搜索…" clearable style="width:320px" prefix-icon="Search"/>
      </div>
      <div class="stats">
        <b>待确认 {{ reviewSummary.pending_review ?? 0 }}</b>
        <span>已确认 {{ reviewSummary.confirmed ?? 0 }}</span>
        <span>未匹配 {{ reviewSummary.unmatched ?? 0 }}</span>
        <span>自动匹配 {{ reviewSummary.automatic_matched ?? 0 }}</span>
      </div>
      <div class="threshold-card">
        <span class="muted">调整阈值即时重判(不影响已人工处理行):</span>
        <span>自动 ≥</span><el-slider v-model="thrSuccess" :min="1" :max="100" style="width:150px" :disabled="finalized"/>
        <span>复核 ≥</span><el-slider v-model="thrReview" :min="0" :max="99" style="width:150px" :disabled="finalized"/>
        <el-button size="small" type="primary" plain :loading="redecideBusy" :disabled="finalized || thrReview >= thrSuccess" @click="reDecide">按新阈值重判</el-button>
        <el-tag v-if="finalized" type="info" size="small">结果已生成,阈值已锁定</el-tag>
      </div>
      <div class="quick">
        <el-button :type="filterMode2==='all'?'primary':'default'" size="small" @click="filterMode2='all';loadWorkbench()">全部</el-button>
        <el-button :type="filterMode2==='high'?'primary':'default'" size="small" @click="filterMode2='high';loadWorkbench()">90分以上无冲突</el-button>
        <el-button :type="filterMode2==='gap'?'primary':'default'" size="small" @click="filterMode2='gap';loadWorkbench()">分差&lt;5</el-button>
        <el-button :type="filterMode2==='conflict'?'primary':'default'" size="small" @click="filterMode2='conflict';loadWorkbench()">关键字段冲突</el-button>
        <el-button size="small" :disabled="!selectedRows.length" @click="batchConfirm">批量确认第一候选</el-button>
        <el-button size="small" :disabled="!selectedRows.length" @click="batchReject">批量标记未匹配</el-button>
      </div>
      <el-table :data="workbenchItems" size="small" @selection-change="onSelection">
        <el-table-column type="selection" width="42"/>
        <el-table-column prop="source_id" label="物料编码" min-width="140"/>
        <el-table-column label="源数据摘要" min-width="220"><template #default="scope"><span class="payload-brief">{{ Object.values(scope.row.source_payload ?? {}).filter(v=>v).slice(0,4).join(' · ').slice(0,60) }}</span></template></el-table-column>
        <el-table-column prop="top1_group_code" label="第一候选" min-width="130"/>
        <el-table-column label="分/分差" width="110"><template #default="scope">{{ Number(scope.row.top1_score).toFixed(0) }} / {{ Number(scope.row.score_gap).toFixed(0) }}</template></el-table-column>
        <el-table-column label="冲突" width="70"><template #default="scope"><el-tag size="small" :type="scope.row.critical_conflict?'danger':'success'">{{ scope.row.critical_conflict?'有':'无' }}</el-tag></template></el-table-column>
        <el-table-column label="操作" width="230"><template #default="scope">
          <el-button link size="small" @click="openCandidates(scope.row)">候选对比</el-button>
          <el-button link type="primary" size="small" @click="confirmCandidate(scope.row)">确认</el-button>
          <el-button link type="danger" size="small" @click="rejectItem(scope.row)">未匹配</el-button>
        </template></el-table-column>
      </el-table>
      <div class="actions"><el-button @click="stage=1">← 查看进度</el-button><el-button type="primary" @click="finalize(); stage=3">下一步:输出结果 →</el-button></div>
    </div>

    <!-- 第四步:输出结果 -->
    <div v-else class="panel">
      <h3>输出结果</h3>
      <div class="stats">
        <span>总行数 {{ finalTotal }}</span><span>自动匹配 {{ reviewSummary.automatic_matched ?? 0 }}</span><span>人工确认 {{ reviewSummary.confirmed ?? 0 }}</span><span>未匹配 {{ reviewSummary.unmatched ?? 0 }}</span><span>仍待确认 {{ reviewSummary.pending_review ?? 0 }}</span>
      </div>
      <el-alert v-if="!finalized && (reviewSummary.pending_review ?? 0) > 0" type="warning" :closable="false" title="仍有待确认行:可返回人工调整,或继续生成(这些行集团码为空)。"/>
      <el-alert v-if="finalized" type="success" :closable="false" title="最终 Excel 已生成:含「匹配摘要」「匹配结果(带状态色)」「TopN候选」「人工确认记录」四张表。"/>
      <div class="actions">
        <el-button @click="stage=2">← 人工调整</el-button>
        <el-button v-if="!finalized" type="primary" @click="finalize">一键生成匹配结果</el-button>
        <el-button v-else type="primary" @click="downloadResult">下载结果 Excel</el-button>
        <el-button v-if="task?.task_id" @click="router.push(`/tasks/${task.task_id}/evaluation`)">准确率验收</el-button>
      </div>
    </div>

    <el-drawer v-model="drawerVisible" title="候选对比" size="68%">
      <div v-if="drawerItem">
        <p class="drawer-source"><b>{{ drawerItem.source_id }}</b>　{{ Object.values(drawerItem.source_payload ?? {}).filter(v=>v).slice(0,6).join(' · ') }}</p>
        <el-tabs v-model="candidateIndex">
          <el-tab-pane v-for="(candidate,index) in candidates" :key="candidate.rank" :name="index" :label="`候选${candidate.rank} · ${candidate.score.toFixed(1)}分`"/>
        </el-tabs>
        <div v-if="currentCandidate">
          <p><b>集团码:</b>{{ currentCandidate.target_group_code }}</p>
          <el-table :data="currentCandidate.field_scores" size="small">
            <el-table-column prop="rule_id" label="规则" width="120"/>
            <el-table-column prop="source_value" label="源值" min-width="150"/>
            <el-table-column prop="target_value" label="目标值" min-width="150"/>
            <el-table-column label="得分" width="80"><template #default="scope">{{ (scope.row.score*100).toFixed(0) }}</template></el-table-column>
            <el-table-column label="状态" width="80"><template #default="scope"><el-tag size="small" :type="scope.row.conflict?'danger':'success'">{{ scope.row.conflict?'冲突':'正常' }}</el-tag></template></el-table-column>
          </el-table>
          <el-descriptions :column="2" size="small" border style="margin-top:10px">
            <el-descriptions-item v-for="(value,key) in currentCandidate.target_payload" :key="key" :label="String(key)">{{ value }}</el-descriptions-item>
          </el-descriptions>
        </div>
        <div class="actions">
          <el-button type="danger" @click="rejectFromDrawer">标记未匹配</el-button>
          <el-button type="primary" :disabled="!currentCandidate" @click="confirmFromDrawer">确认此候选</el-button>
        </div>
      </div>
    </el-drawer>
  </div>
</template>
