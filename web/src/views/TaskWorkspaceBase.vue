<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '../api'
import DualExcelUploadPanel from '../components/DualExcelUploadPanel.vue'
import FieldMappingCanvas from '../components/FieldMappingCanvas.vue'
import { setActiveWorkspaceStep, type WorkspaceStep } from '../workspaceStage'

type FileRecord = { file_id: string; original_name: string; sha256?: string; role?: string }
type ColumnInfo = { header: string; business_hint?: string | null; samples?: string[] }
type ParsedWorkbookPayload = { kind: 'source' | 'target'; file: FileRecord; inspection: any; columns: ColumnInfo[] }
type FieldSide = { fields: string[]; combine: 'concat' | 'coalesce' | 'best_of'; separator: string; pipeline: Array<Record<string, unknown>> }
type Rule = { id: string; source: FieldSide; target: FieldSide; matcher: string; weight: number; critical: boolean; matcher_options: Record<string, unknown> }
type ProfileRow = { profile_id: string; name: string; latest_published_version?: number | null; updated_at?: string }
type ProfileVersion = { version_no: number; status: string; sha256?: string; document: Record<string, any> }
type ProfileDetail = { profile_id: string; name: string; draft?: ProfileVersion | null; latest_published?: ProfileVersion | null }
type WorkbenchItem = { source_row_id: string; source_id: string; source_payload: Record<string, unknown>; top1_group_code?: string | null; top1_score: number; second_score: number; score_gap: number; critical_conflict: boolean; current_status?: string }
type FieldScore = { rule_id: string; score: number; weight: number; source_value: string; target_value: string; critical: boolean; conflict: boolean }
type Candidate = { rank: number; target_group_code: string; score: number; critical_conflict: boolean; target_payload: Record<string, unknown>; field_scores: FieldScore[] }

const route = useRoute(), router = useRouter()
const profileQueryId = computed(() => typeof route.query.profile === 'string' ? route.query.profile : '')
const isProfileEditorMode = computed(() => route.query.edit === '1' && !route.params.taskId)
const isProfileTaskCreateMode = computed(() => !isProfileEditorMode.value && Boolean(profileQueryId.value) && !route.params.taskId)

/* ---------- 阶段 ---------- */
const stage = ref(0) // 0数据上传与配置 1计算 2人工调整 3输出结果
const stageTitles = ['数据上传', '计算', '人工调整', '输出结果']

/* ---------- 配置:方案与数据 ---------- */
const name = ref('')
const profiles = ref<ProfileRow[]>([])
const appliedProfile = ref<{ id: string; version: number } | null>(null)
const editingProfileId = ref('')
const editingProfileHasDraft = ref(false)
const editingProfilePublishedVersion = ref<number | null>(null)
const editingProfileOriginalName = ref('')
const profileTaskMeta = ref<{ name: string; version: number; sha256: string } | null>(null)
const profilePicker = ref('')
const source = ref<FileRecord | null>(null)
const sourceColumns = ref<ColumnInfo[]>([])
const sourceIdColumn = ref('')
const targetMode = ref<'existing' | 'upload'>('upload')
const target = ref<FileRecord | null>(null)
const targetColumns = ref<ColumnInfo[]>([])
const groupCodeColumn = ref('')
const catalogs = ref<any[]>([])
const catalogVersionId = ref('')
const draftId = ref('')
const draftSaveState = ref<'idle' | 'saving' | 'saved' | 'error'>('idle')
const restoringWorkspace = ref(true)
const busy = ref(false)
const embeddingReady = ref(false)
let draftSaveTimer: number | undefined
let draftSaveInFlight = false
let draftSaveQueued = false
let lastDraftSignature = ''

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
const documentBase = ref<Record<string, any>>({})
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
const pendingSource = ref<string | null>(null)

const srcHeaders = computed(() => sourceColumns.value.map(column => column.header))
const tgtHeaders = computed(() => targetColumns.value.map(column => column.header))
const idCandidateColumns = computed(() => srcHeaders.value.filter(header => header !== sourceIdColumn.value))

function uniqueFields(values: Array<string | null | undefined>): string[] {
  return [...new Set(values.map(value => String(value ?? '').trim()).filter(Boolean))]
}
const profileSourceFields = computed(() => uniqueFields([
  sourceIdColumn.value,
  filterField.value,
  scopeSourceField.value,
  ...rules.value.flatMap(rule => rule.source.fields),
]))
const profileTargetFields = computed(() => uniqueFields([
  scopeTargetField.value,
  ...rules.value.flatMap(rule => rule.target.fields),
]))
const profileTaskIssues = computed(() => {
  if (!isProfileTaskCreateMode.value) return [] as string[]
  const issues: string[] = []
  if (!source.value) issues.push('请先上传本次待匹配数据')
  if (!target.value) issues.push('请上传本次集团码标准数据')
  if (target.value && !groupCodeColumn.value) issues.push('请确认集团码所在列')
  if (source.value) {
    const sourceSet = new Set(srcHeaders.value)
    const requiredSource = uniqueFields([
      sourceIdColumn.value,
      filterEnabled.value ? filterField.value : '',
      scopeMode.value !== 'GLOBAL' ? scopeSourceField.value : '',
      ...rules.value.flatMap(rule => rule.source.fields),
    ])
    const missing = requiredSource.filter(field => !sourceSet.has(field))
    if (missing.length) issues.push(`待匹配数据缺少方案字段: ${missing.join('、')}`)
  }
  if (target.value && targetColumns.value.length) {
    const targetSet = new Set(tgtHeaders.value)
    const requiredTarget = uniqueFields([
      scopeMode.value !== 'GLOBAL' ? scopeTargetField.value : '',
      ...rules.value.flatMap(rule => rule.target.fields),
    ])
    const missing = requiredTarget.filter(field => !targetSet.has(field))
    if (missing.length) issues.push(`集团码标准数据缺少方案字段: ${missing.join('、')}`)
  }
  if (!rules.value.length) issues.push('已发布方案没有字段映射规则')
  if (!sourceIdColumn.value) issues.push('已发布方案未配置源数据标识字段')
  return [...new Set(issues)]
})
const profileTaskValid = computed(() => Boolean(name.value.trim()) && Boolean(appliedProfile.value) && configValid.value && profileTaskIssues.value.length === 0)
const profileFilterSummary = computed(() => {
  if (!filterEnabled.value || !filterField.value || !filterValues.value.length) return '不过滤'
  return `${filterField.value} ${filterMode.value === 'exclude' ? '排除' : '包含'} ${filterValues.value.join('、')}`
})
const profileScopeSummary = computed(() => ({ GLOBAL: '全库匹配', STRICT: '同组匹配', MAPPED: '分类映射' }[scopeMode.value] ?? scopeMode.value))
const draftStateLabel = computed(() => ({ idle: '草稿待保存', saving: '草稿保存中…', saved: '草稿已保存', error: '草稿保存失败' }[draftSaveState.value]))

function cloneDocument<T>(value: T): T {
  return JSON.parse(JSON.stringify(value ?? {})) as T
}

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
  ElMessage.success(`已根据字段语义自动生成 ${out.length} 条映射，可继续人工调整`)
}

function defaultRule(): Rule {
  const sField = sourceColumns.value.find(column => column.header !== sourceIdColumn.value)?.header ?? srcHeaders.value[0] ?? ''
  const tField = targetColumns.value.find(column => column.header !== groupCodeColumn.value)?.header ?? tgtHeaders.value[0] ?? ''
  return makeRule(sField ? [sField] : [], tField ? [tField] : [], 'hybrid', 100)
}
function addProfileRule(): void {
  rules.value.push(makeRule([], [], 'hybrid', rules.value.length ? 20 : 100))
}

function onSourceChip(header: string): void {
  pendingSource.value = pendingSource.value === header ? null : header
}
function onTargetChip(header: string): void {
  const sourceField = pendingSource.value
  if (!sourceField) { ElMessage.info('请先点击左侧源字段，再点击右侧目标字段完成连线'); return }
  const existing = rules.value.find(rule => rule.source.fields.includes(sourceField) && rule.target.fields.includes(header))
  if (existing) { ElMessage.warning('该连线已存在'); pendingSource.value = null; return }
  rules.value.push(makeRule([sourceField], [header], 'hybrid', rules.value.length ? 20 : 100))
  normalizeWeights()
  pendingSource.value = null
}
function removeRule(ruleId: string): void {
  const index = rules.value.findIndex(rule => rule.id === ruleId)
  if (index >= 0) rules.value.splice(index, 1)
}
function ruleSideLabel(side: FieldSide): string {
  return side.fields.join(side.combine === 'coalesce' ? ' / ' : ' + ')
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
    const preserveProfileField = isProfileTaskCreateMode.value && Boolean(appliedProfile.value) && Boolean(sourceIdColumn.value)
    if (!preserveProfileField && (!sourceIdColumn.value || !columns.some(column => column.header === sourceIdColumn.value))) {
      sourceIdColumn.value = findHint(columns, 'source_id') || columns[0]?.header || ''
    }
    if (!filterField.value && !isProfileTaskCreateMode.value) filterField.value = findHint(columns, 'material_group') || findHint(columns, 'material_type') || ''
  } else {
    target.value = response.file
    targetColumns.value = columns
    if (!groupCodeColumn.value || !columns.some(column => column.header === groupCodeColumn.value)) {
      groupCodeColumn.value = findHint(columns, 'group_code') || columns[0]?.header || ''
    }
  }
}
function onWorkbookParsed(payload: ParsedWorkbookPayload): void {
  const columns = payload.columns ?? []
  if (payload.kind === 'source') {
    source.value = payload.file
    sourceColumns.value = columns
    const preserveProfileField = isProfileTaskCreateMode.value && Boolean(appliedProfile.value) && Boolean(sourceIdColumn.value) && columns.some(column => column.header === sourceIdColumn.value)
    if (!preserveProfileField) sourceIdColumn.value = findHint(columns, 'source_id') || columns[0]?.header || ''
    if (!filterField.value && !isProfileTaskCreateMode.value) filterField.value = findHint(columns, 'material_group') || findHint(columns, 'material_type') || ''
  } else {
    target.value = payload.file
    targetColumns.value = columns
    groupCodeColumn.value = findHint(columns, 'group_code') || columns[0]?.header || ''
    targetMode.value = 'upload'
    catalogVersionId.value = ''
  }
  if (source.value && target.value && !rules.value.length) autoMap()
}
function onSourceIdColumnChange(value: string): void {
  sourceIdColumn.value = value
}
function onGroupCodeColumnChange(value: string): void {
  groupCodeColumn.value = value
  targetMode.value = 'upload'
  catalogVersionId.value = ''
}
async function loadCatalogs(selectCurrent = false): Promise<void> {
  catalogs.value = ((await api.get('/catalogs')).data ?? []).filter((item: any) => item.status === 'READY')
    .sort((a: any, b: any) => Number(b.active) - Number(a.active) || String(b.created_at).localeCompare(String(a.created_at)))
  if (selectCurrent && catalogVersionId.value) await selectCatalog(catalogVersionId.value)
}
async function selectCatalog(versionId: string, preferredTargetFileId = ''): Promise<void> {
  let catalog = catalogs.value.find((item: any) => item.version_id === versionId)
  if (!catalog) {
    try { catalog = (await api.get(`/catalogs/versions/${versionId}`)).data } catch { return }
  }
  groupCodeColumn.value = String(catalog.group_code_column ?? groupCodeColumn.value)
  const targetFileId = preferredTargetFileId || String(catalog.source_file_id ?? '')
  if (!targetFileId) return
  try { await loadFileColumns(targetFileId, 'target') } catch (error) {
    if (preferredTargetFileId && catalog.source_file_id && String(catalog.source_file_id) !== preferredTargetFileId) {
      await loadFileColumns(String(catalog.source_file_id), 'target')
    } else ElMessage.error((error as Error).message)
  }
}
async function loadProfiles(): Promise<void> {
  try { profiles.value = (await api.get('/profiles')).data ?? [] } catch { profiles.value = [] }
}
async function getProfileDetail(profileId: string): Promise<ProfileDetail> {
  return (await api.get(`/profiles/${profileId}`)).data as ProfileDetail
}
async function applyProfile(profileId: string): Promise<void> {
  if (!profileId) return
  const detail = await getProfileDetail(profileId)
  const published = detail.latest_published
  if (!published) { ElMessage.warning('该方案尚未发布，不能用于开始匹配'); return }
  loadDocument(published.document ?? {})
  appliedProfile.value = { id: profileId, version: Number(published.version_no) }
  ElMessage.success(`已应用方案「${detail.name}」v${published.version_no}，字段映射与阈值已载入`)
}
async function loadProfileForEdit(profileId: string): Promise<void> {
  const detail = await getProfileDetail(profileId)
  editingProfileId.value = profileId
  editingProfileOriginalName.value = detail.name
  editingProfileHasDraft.value = Boolean(detail.draft)
  editingProfilePublishedVersion.value = detail.latest_published ? Number(detail.latest_published.version_no) : null
  name.value = detail.name
  const editable = detail.draft ?? detail.latest_published
  loadDocument(editable?.document ?? {})
}
async function loadPublishedProfileForTask(profileId: string): Promise<void> {
  const detail = await getProfileDetail(profileId)
  const published = detail.latest_published
  if (!published) throw new Error('该方案尚未发布，请先在匹配方案配置中发布后再开始匹配')
  profilePicker.value = profileId
  loadDocument(published.document ?? {})
  appliedProfile.value = { id: profileId, version: Number(published.version_no) }
  profileTaskMeta.value = { name: detail.name, version: Number(published.version_no), sha256: String(published.sha256 ?? '') }
  name.value = `${detail.name} - 匹配任务`
}
function loadDocument(document: any): void {
  const value = document && typeof document === 'object' ? cloneDocument(document) : {}
  documentBase.value = value
  rules.value = Array.isArray(value.rules) ? cloneDocument(value.rules) : []
  sourceIdColumn.value = String(value.source_id_column ?? '')
  scopeMode.value = value.scope_mode ?? 'GLOBAL'
  scopeSourceField.value = String(value.scope?.source_field ?? '')
  scopeTargetField.value = String(value.scope?.target_field ?? '')
  successThreshold.value = Number(value.decision?.success_threshold ?? 88)
  reviewThreshold.value = Number(value.decision?.review_threshold ?? 75)
  topN.value = Number(value.decision?.top_n ?? 5)
  thrSuccess.value = successThreshold.value
  thrReview.value = reviewThreshold.value
  retrievalMaxLength.value = Number(value.retrieval?.max_length ?? 256)
  retrievalDocument.value = { ...(value.retrieval ?? {}) }
  const flt = value.source_filter
  filterEnabled.value = Boolean(flt?.field)
  filterField.value = String(flt?.field ?? '')
  filterValues.value = Array.isArray(flt?.values) ? flt.values.map(String) : []
  filterMode.value = flt?.mode === 'exclude' ? 'exclude' : 'include'
  advanced.value = false
}
function workspaceTargetFromDocument(document: any): { fileId: string; groupCodeColumn: string } {
  const state = document?.advanced?.workspace_target
  if (!state || typeof state !== 'object') return { fileId: '', groupCodeColumn: '' }
  return {
    fileId: String(state.file_id ?? ''),
    groupCodeColumn: String(state.group_code_column ?? ''),
  }
}
function documentBody(includeWorkspaceTarget = true): Record<string, unknown> {
  const base = cloneDocument(documentBase.value)
  const baseScope = base.scope && typeof base.scope === 'object' ? base.scope : {}
  const baseDecision = base.decision && typeof base.decision === 'object' ? base.decision : {}
  const baseAdvanced = base.advanced && typeof base.advanced === 'object' ? cloneDocument(base.advanced) : {}
  delete baseAdvanced.workspace_target
  if (includeWorkspaceTarget && target.value) {
    baseAdvanced.workspace_target = {
      file_id: target.value.file_id,
      group_code_column: groupCodeColumn.value || null,
    }
  }
  const retrieval = {
    mode: 'auto', provider: 'onnx_local', model_id: 'BAAI/bge-base-zh-v1.5', dimensions: 768, precision: 'fp32', retrieval_top_k: 200, oversample: 4,
    ...(base.retrieval && typeof base.retrieval === 'object' ? base.retrieval : {}),
    ...(retrievalDocument.value ?? {}),
    max_length: retrievalMaxLength.value,
  }
  return {
    ...base,
    source_id_column: sourceIdColumn.value || null,
    scope_mode: scopeMode.value,
    scope: { ...baseScope, source_field: scopeSourceField.value || null, target_field: scopeTargetField.value || null },
    source_filter: filterEnabled.value && filterField.value && filterValues.value.length ? { field: filterField.value, values: filterValues.value, mode: filterMode.value, match: 'exact' } : null,
    rules: cloneDocument(rules.value),
    decision: {
      ...baseDecision,
      success_threshold: successThreshold.value,
      review_enabled: typeof baseDecision.review_enabled === 'boolean' ? baseDecision.review_enabled : true,
      review_threshold: reviewThreshold.value,
      top_n: topN.value,
    },
    retrieval,
    advanced: baseAdvanced,
  }
}
const configValid = computed(() => Boolean(source.value) && Boolean(sourceIdColumn.value) && Boolean(target.value && groupCodeColumn.value) && rules.value.length > 0 && reviewThreshold.value < successThreshold.value)

async function persistProfileDraft(showMessage = true): Promise<string | null> {
  const profileName = name.value.trim()
  if (!profileName) { ElMessage.warning('请输入方案名称'); return null }
  const body = documentBody(false)
  let profileId = editingProfileId.value
  if (!profileId) {
    const created = (await api.post('/profiles', { name: profileName, document: body })).data
    profileId = String(created.profile_id)
    editingProfileId.value = profileId
    editingProfileOriginalName.value = profileName
    editingProfileHasDraft.value = true
    await router.replace({ path: '/tasks/new', query: { profile: profileId, edit: '1' } })
  } else {
    if (profileName !== editingProfileOriginalName.value) {
      await api.patch(`/profiles/${profileId}`, { name: profileName })
      editingProfileOriginalName.value = profileName
    }
    await api.put(`/profiles/${profileId}/draft`, body)
    editingProfileHasDraft.value = true
  }
  documentBase.value = cloneDocument(body)
  if (showMessage) ElMessage.success('方案草稿已保存到后台')
  return profileId
}
async function saveProfileDraft(): Promise<void> {
  busy.value = true
  try { await persistProfileDraft(true) } catch (error) { ElMessage.error((error as Error).message ?? '保存草稿失败') } finally { busy.value = false }
}
async function publishProfileChanges(): Promise<void> {
  busy.value = true
  try {
    const profileId = await persistProfileDraft(false)
    if (!profileId) return
    await api.post(`/profiles/${profileId}/validate`)
    const published = (await api.post(`/profiles/${profileId}/publish`)).data
    await loadProfiles()
    await loadProfileForEdit(profileId)
    ElMessage.success(`方案已发布为 v${published.version_no}；历史发布版本保持不可变，已有任务不受影响`)
  } catch (error) { ElMessage.error((error as Error).message ?? '发布失败') } finally { busy.value = false }
}

function buildDraftPayload(catalogVersion: string | null = catalogVersionId.value || null): Record<string, unknown> {
  return {
    name: name.value.trim() || '未命名匹配任务',
    source_file_id: source.value?.file_id ?? null,
    catalog_version_id: catalogVersion,
    template_profile_id: appliedProfile.value?.id ?? null,
    template_profile_version: appliedProfile.value?.version ?? null,
    config_document: documentBody(true),
  }
}

async function ensureDraft(): Promise<void> {
  if (draftId.value) return
  const draft = (await api.post('/task-drafts', { name: name.value.trim() || '未命名匹配任务' })).data
  draftId.value = String(draft.draft_id)
  if (!route.params.taskId && route.query.draft !== draftId.value) {
    await router.replace({ path: route.path, query: { ...route.query, draft: draftId.value } })
  }
}

async function resolveCatalogVersionForDraft(): Promise<string | null> {
  if (!target.value || !groupCodeColumn.value) return null
  await loadCatalogs(false)
  let existing = catalogs.value.find((item: any) => item.source_file_id === target.value!.file_id && item.group_code_column === groupCodeColumn.value)
  if (!existing && target.value.sha256) {
    try {
      const fileRows = (await api.get('/files')).data ?? []
      const equivalentFileIds = new Set(
        fileRows
          .filter((item: any) => item.role === 'target' && item.sha256 === target.value!.sha256)
          .map((item: any) => String(item.file_id)),
      )
      existing = catalogs.value.find((item: any) => equivalentFileIds.has(String(item.source_file_id)) && item.group_code_column === groupCodeColumn.value)
    } catch { /* SHA 复用失败时退化为新建后台版本 */ }
  }
  if (existing) {
    catalogVersionId.value = String(existing.version_id)
    return catalogVersionId.value
  }
  const catalog = (await api.post('/catalogs', {
    name: `${name.value.trim() || '任务'}-自动标准数据`,
    source_file_id: target.value.file_id,
    group_code_column: groupCodeColumn.value,
  })).data
  catalogVersionId.value = String(catalog.version_id)
  await loadCatalogs(false)
  return catalogVersionId.value
}

async function persistWorkspaceDraft(): Promise<void> {
  if (restoringWorkspace.value || isProfileEditorMode.value || route.params.taskId || stage.value !== 0) return
  if (draftSaveInFlight) { draftSaveQueued = true; return }
  draftSaveInFlight = true
  try {
    await ensureDraft()
    const versionId = await resolveCatalogVersionForDraft()
    const payload = buildDraftPayload(versionId)
    const signature = JSON.stringify(payload)
    if (signature === lastDraftSignature) {
      draftSaveState.value = 'saved'
      return
    }
    draftSaveState.value = 'saving'
    await api.patch(`/task-drafts/${draftId.value}`, payload)
    lastDraftSignature = signature
    draftSaveState.value = 'saved'
  } catch {
    draftSaveState.value = 'error'
  } finally {
    draftSaveInFlight = false
    if (draftSaveQueued) {
      draftSaveQueued = false
      window.setTimeout(() => void persistWorkspaceDraft(), 0)
    }
  }
}

function scheduleDraftPersist(): void {
  if (restoringWorkspace.value || isProfileEditorMode.value || route.params.taskId || stage.value !== 0) return
  if (draftSaveTimer) window.clearTimeout(draftSaveTimer)
  draftSaveState.value = draftId.value ? 'idle' : draftSaveState.value
  draftSaveTimer = window.setTimeout(() => void persistWorkspaceDraft(), 300)
}

async function saveConfig(): Promise<void> {
  await ensureDraft()
  const versionId = await resolveCatalogVersionForDraft()
  if (!source.value || !target.value || !versionId) throw new Error('请先上传左侧待匹配 Excel 和右侧集团码标准 Excel')
  const payload = buildDraftPayload(versionId)
  await api.patch(`/task-drafts/${draftId.value}`, payload)
  await api.put(`/task-drafts/${draftId.value}/data`, {
    source_file_id: source.value.file_id,
    catalog_version_id: versionId,
    template_profile_id: appliedProfile.value?.id ?? null,
    template_profile_version: appliedProfile.value?.version ?? null,
  })
  await api.put(`/task-drafts/${draftId.value}/rules`, documentBody(true))
  lastDraftSignature = JSON.stringify(payload)
  draftSaveState.value = 'saved'
}
async function saveAsProfile(): Promise<void> {
  if (!rules.value.length) { ElMessage.warning('请先完成字段映射'); return }
  try {
    const { value } = await ElMessageBox.prompt('方案名称(发布后不可变,后续匹配可直接复用)', '存为匹配方案', { inputValue: name.value || '', confirmButtonText: '校验并发布', cancelButtonText: '取消' })
    const created = (await api.post('/profiles', { name: value.trim() || `方案-${Date.now()}`, document: documentBody(false) })).data
    await api.post(`/profiles/${created.profile_id}/validate`)
    await api.post(`/profiles/${created.profile_id}/publish`)
    await loadProfiles()
    ElMessage.success('方案已发布，可在第一步“数据上传”中选择此方案并上传数据')
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
  if (isProfileTaskCreateMode.value && profileTaskIssues.value.length) { ElMessage.warning(profileTaskIssues.value[0]); return }
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
const phaseLabel = computed(() => ({ INDEX: '正在准备标准数据（首次处理可能稍慢，后续可直接复用）', RETRIEVE: '候选召回', RERANK: '实时逐条匹配与精细评分', PERSIST: '结果持久化', DONE: '已完成', WAITING: '等待调度', FAILED: '失败', RECOVERING: '恢复中' }[String(progress.value?.current_phase ?? '')] ?? '准备中'))
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
async function finalize(): Promise<boolean> {
  await loadReviewSummary()
  let allow = false
  if (Number(reviewSummary.value.pending_review ?? 0) > 0) {
    try { await ElMessageBox.confirm(`仍有 ${reviewSummary.value.pending_review} 条待确认。继续生成后这些行集团码为空。`, '生成最终结果', { confirmButtonText: '继续生成', cancelButtonText: '返回处理', type: 'warning' }); allow = true } catch { return false }
  }
  try {
    await api.post(`/tasks/${task.value.task_id}/finalize`, { allow_unresolved_review: allow })
    task.value = (await api.get(`/tasks/${task.value.task_id}`)).data
    finalized.value = true
    await loadReviewSummary()
    ElMessage.success('最终结果已生成(含匹配摘要与样式)')
    return true
  } catch (error) {
    ElMessage.error((error as Error).message)
    return false
  }
}
async function finalizeAndOpenResults(): Promise<void> {
  if (await finalize()) stage.value = 3
}
function downloadResult(): void { window.location.href = `/api/tasks/${task.value.task_id}/result` }

/* ---------- 恢复 ---------- */
async function restoreDraft(id: string): Promise<void> {
  const draft = (await api.get(`/task-drafts/${id}`)).data
  draftId.value = String(draft.draft_id)
  name.value = String(draft.name ?? '')
  const configDocument = draft.config_document ?? {}
  loadDocument(configDocument)
  const workspaceTarget = workspaceTargetFromDocument(configDocument)
  if (draft.source_file_id) await loadFileColumns(String(draft.source_file_id), 'source')
  if (draft.catalog_version_id) {
    catalogVersionId.value = String(draft.catalog_version_id)
    targetMode.value = 'upload'
    if (workspaceTarget.groupCodeColumn) groupCodeColumn.value = workspaceTarget.groupCodeColumn
    await selectCatalog(catalogVersionId.value, workspaceTarget.fileId)
  } else if (workspaceTarget.fileId) {
    if (workspaceTarget.groupCodeColumn) groupCodeColumn.value = workspaceTarget.groupCodeColumn
    await loadFileColumns(workspaceTarget.fileId, 'target')
  }
  if (draft.template_profile_id) {
    const profileId = String(draft.template_profile_id)
    const version = Number(draft.template_profile_version ?? 1)
    appliedProfile.value = { id: profileId, version }
    profilePicker.value = profileId
    try {
      const detail = await getProfileDetail(profileId)
      profileTaskMeta.value = { name: detail.name, version, sha256: '' }
    } catch { /* 草稿本身仍可恢复 */ }
  }
  lastDraftSignature = JSON.stringify(buildDraftPayload())
  draftSaveState.value = 'saved'
  stage.value = 0
}
async function restoreTask(taskId: string): Promise<void> {
  task.value = (await api.get(`/tasks/${taskId}`)).data
  name.value = task.value.name
  const configDocument = task.value.config_snapshot ?? {}
  loadDocument(configDocument)
  const workspaceTarget = workspaceTargetFromDocument(configDocument)
  if (task.value.source_file_id) await loadFileColumns(String(task.value.source_file_id), 'source').catch(() => undefined)
  if (task.value.catalog_version_id) {
    catalogVersionId.value = String(task.value.catalog_version_id)
    if (workspaceTarget.groupCodeColumn) groupCodeColumn.value = workspaceTarget.groupCodeColumn
    await selectCatalog(catalogVersionId.value, workspaceTarget.fileId).catch(() => undefined)
  }
  if (task.value.status === 'COMPLETED') { await enterStage2Or3() }
  else if (task.value.status === 'FAILED') { stage.value = 1 }
  else { stage.value = 1; startPolling() }
}

function syncWorkspaceStep(value = stage.value): void {
  setActiveWorkspaceStep((value + 1) as WorkspaceStep)
}

watch(stage, value => syncWorkspaceStep(value))
watch([
  name,
  source,
  catalogVersionId,
  targetMode,
  target,
  groupCodeColumn,
  appliedProfile,
  sourceIdColumn,
  rules,
  scopeMode,
  scopeSourceField,
  scopeTargetField,
  filterEnabled,
  filterField,
  filterValues,
  filterMode,
  successThreshold,
  reviewThreshold,
  topN,
  retrievalMaxLength,
  retrievalDocument,
  documentBase,
], scheduleDraftPersist, { deep: true })

onMounted(async () => {
  try {
    try {
      const status = (await api.get('/system/vector-status')).data
      embeddingReady.value = Boolean(status.embedding?.ready)
    } catch { embeddingReady.value = false }
    await loadProfiles()
    if (!isProfileEditorMode.value) await loadCatalogs(false)
    if (route.params.taskId) { await restoreTask(String(route.params.taskId)).catch(() => router.push('/tasks')); return }
    const draft = typeof route.query.draft === 'string' ? route.query.draft : ''
    if (draft) { await restoreDraft(draft).catch(() => undefined); return }
    const profileParam = profileQueryId.value
    if (isProfileEditorMode.value) {
      if (profileParam) {
        try { await loadProfileForEdit(profileParam) }
        catch (error) { ElMessage.error((error as Error).message ?? '方案加载失败'); await router.push('/profiles') }
      } else {
        editingProfileId.value = ''
        editingProfileHasDraft.value = false
        editingProfilePublishedVersion.value = null
        editingProfileOriginalName.value = ''
        name.value = ''
        loadDocument({})
      }
      return
    }
    if (profileParam) {
      try { await loadPublishedProfileForTask(profileParam) }
      catch (error) { ElMessage.error((error as Error).message ?? '已发布方案加载失败'); await router.push('/profiles') }
    }
  } finally {
    restoringWorkspace.value = false
    syncWorkspaceStep()
  }
})
onBeforeUnmount(() => {
  stopPolling()
  if (searchTimer) window.clearTimeout(searchTimer)
  if (draftSaveTimer) window.clearTimeout(draftSaveTimer)
  if (!restoringWorkspace.value && stage.value === 0 && !isProfileEditorMode.value && !route.params.taskId) void persistWorkspaceDraft()
  setActiveWorkspaceStep(null)
})
</script>

<template>
  <div class="wizard" :class="{ 'profile-editor-mode': isProfileEditorMode, 'profile-task-mode': isProfileTaskCreateMode }">
    <div class="toolbar workspace-toolbar">
      <div>
        <h2>{{ stage === 0 ? '第一步 · 数据上传' : stage === 1 ? '第二步 · 进度监控' : stage === 2 ? '第三步 · 人工调整' : '第四步 · 输出结果' }}</h2>
        <p v-if="isProfileEditorMode"><b>匹配方案配置</b> · {{ editingProfileId ? `编辑方案「${name || '未命名方案'}」` : '新建匹配方案' }}；这里只维护字段映射、匹配规则和默认参数，不会启动匹配。</p>
        <p v-else-if="isProfileTaskCreateMode"><b>数据上传</b> · 已选方案「{{ profileTaskMeta?.name ?? name ?? '—' }}」；上传本次左右两份 Excel，已发布方案作为初始配置，开始匹配前仍可调整映射、权重和阈值。</p>
        <p v-else-if="stage === 0"><b>数据上传与匹配设置</b>：上传两份 Excel → 确认字段映射 → 设置匹配方式与阈值 → 开始匹配</p>
        <p v-else><b>{{ task?.scheme_name || name || '未命名方案' }}</b> · {{ stage === 1 ? '匹配计算进行中，进度与中间结果实时更新。' : stage === 2 ? '集中处理需要人工确认的记录。' : '确认无误后生成并下载最终结果 Excel。' }}</p>
      </div>
      <div class="toolbar-actions">
        <el-tag v-if="!isProfileEditorMode && draftId" size="small" :type="draftSaveState === 'error' ? 'danger' : draftSaveState === 'saved' ? 'success' : 'info'">{{ draftStateLabel }}</el-tag>
        <template v-if="isProfileEditorMode">
          <el-tag v-if="editingProfileHasDraft" type="warning">后端草稿</el-tag>
          <el-tag v-else-if="editingProfilePublishedVersion" type="success">基于已发布 v{{ editingProfilePublishedVersion }}</el-tag>
          <el-tag v-else type="info">新方案</el-tag>
          <el-button @click="router.push('/profiles')">返回方案列表</el-button>
          <el-button :loading="busy" @click="saveProfileDraft">保存草稿</el-button>
          <el-button type="primary" :loading="busy" @click="publishProfileChanges">{{ editingProfilePublishedVersion ? '校验并发布新版本' : '校验并发布' }}</el-button>
        </template>
        <template v-else-if="isProfileTaskCreateMode">
          <el-button @click="router.push('/profiles')">更换方案</el-button>
        </template>
        <template v-else>
          <el-select v-model="profilePicker" placeholder="选用已发布方案…" clearable filterable style="width:280px" @change="applyProfile">
            <el-option v-for="item in profiles" :key="item.profile_id" :value="item.profile_id" :label="`${item.name}${item.latest_published_version ? ' · v' + item.latest_published_version : ''}`"/>
          </el-select>
          <el-button @click="saveAsProfile">存为新方案</el-button>
        </template>
      </div>
    </div>
    <el-steps v-if="!isProfileEditorMode && !isProfileTaskCreateMode" :active="stage" align-center finish-status="success" class="stage-steps">
      <el-step v-for="(title, index) in stageTitles" :key="title" :title="`${index + 1}. ${title}`" :status="index < stage ? 'success' : index === stage ? 'process' : 'wait'"/>
    </el-steps>

    <!-- 第一步:数据上传与配置 -->
    <template v-if="stage === 0">
      <div v-if="isProfileTaskCreateMode" class="panel profile-template-summary">
        <div class="section-head">
          <div>
            <h3 style="margin:0">已应用匹配方案</h3>
            <p class="profile-template-name">{{ profileTaskMeta?.name ?? '—' }} <el-tag type="success" size="small">v{{ profileTaskMeta?.version ?? appliedProfile?.version }}</el-tag></p>
          </div>
        </div>
        <div class="profile-summary-grid">
          <div><span>字段规则</span><b>{{ rules.length }} 条</b></div>
          <div><span>自动匹配阈值</span><b>{{ successThreshold }} 分</b></div>
          <div><span>人工确认下限</span><b>{{ reviewThreshold }} 分</b></div>
          <div><span>匹配范围</span><b>{{ profileScopeSummary }}</b></div>
          <div class="wide"><span>源数据过滤</span><b>{{ profileFilterSummary }}</b></div>
        </div>
        <el-alert type="info" :closable="false" title="这是本次匹配的初始配置；后续调整只作用于本次匹配，不会修改已发布方案。"/>
      </div>

      <div v-if="!isProfileEditorMode" class="panel step1-data-panel">
        <div class="section-head step1-heading">
          <div>
            <h3 style="margin:0">数据上传</h3>
            <p class="step1-subtitle">只需要告诉系统“左边这份数据，要和右边这份集团码标准数据匹配”。其余准备工作由系统自动完成。</p>
          </div>
        </div>
        <div class="task-name-row">
          <label>任务名称</label>
          <el-input v-model="name" maxlength="120" show-word-limit placeholder="例如：2026年9月集团码匹配"/>
        </div>
        <DualExcelUploadPanel
          :source="source"
          :target="target"
          :source-columns="sourceColumns"
          :target-columns="targetColumns"
          :source-id-column="sourceIdColumn"
          :group-code-column="groupCodeColumn"
          @parsed="onWorkbookParsed"
          @update:sourceIdColumn="onSourceIdColumnChange"
          @update:groupCodeColumn="onGroupCodeColumnChange"
        />
        <template v-if="isProfileTaskCreateMode">
          <el-alert v-if="profileTaskIssues.length" class="profile-compatibility-alert" type="warning" :closable="false" title="当前两份数据与方案配置还需要确认">
            <div class="compatibility-list"><div v-for="issue in profileTaskIssues" :key="issue">• {{ issue }}</div></div>
          </el-alert>
          <el-alert v-else-if="source && target" class="profile-compatibility-alert" type="success" :closable="false" title="字段兼容检查通过，可继续确认映射和匹配设置。"/>
        </template>
      </div>

      <div class="panel">
        <div v-if="isProfileEditorMode" class="profile-editor-meta">
          <label><span>方案名称</span><el-input v-model="name" maxlength="120" show-word-limit placeholder="输入可复用方案名称"/></label>
          <label><span>客户物料标识字段</span><el-select v-model="sourceIdColumn" filterable allow-create default-first-option placeholder="输入或选择字段名"><el-option v-for="field in profileSourceFields" :key="field" :label="field" :value="field"/></el-select></label>
        </div>
        <div class="section-head">
          <div>
            <h3 style="margin:0">{{ isProfileEditorMode ? '字段映射与权重' : '② 字段映射' }}</h3>
            <p v-if="!isProfileEditorMode" class="section-note">系统会自动推荐映射；点击左侧字段再点击右侧字段可快速连线，也可在下方规则中直接选择多个字段实现多对一 / 一对多。</p>
          </div>
          <div>
            <el-button v-if="isProfileEditorMode" size="small" type="primary" plain @click="addProfileRule">＋ 添加字段映射</el-button>
            <template v-else>
              <el-button size="small" type="primary" plain :disabled="!sourceColumns.length || !targetColumns.length" @click="autoMap">自动推荐映射</el-button>
              <el-button size="small" :disabled="!sourceColumns.length || !targetColumns.length" @click="rules.push(defaultRule()); normalizeWeights()">手动加一条</el-button>
            </template>
          </div>
        </div>
        <template v-if="!isProfileEditorMode">
          <div v-if="!sourceColumns.length || !targetColumns.length" class="canvas-empty">
            <el-empty description="先在上方上传左右两份 Excel，字段清单会自动解析到这里" :image-size="70"/>
          </div>
          <FieldMappingCanvas
            v-else
            :source-columns="sourceColumns"
            :target-columns="targetColumns"
            :rules="rules"
            :source-id-column="sourceIdColumn"
            :group-code-column="groupCodeColumn"
            :pending-source="pendingSource"
            @source-click="onSourceChip"
            @target-click="onTargetChip"
          />
        </template>
        <el-empty v-if="isProfileEditorMode && !rules.length" description="尚无字段映射。添加后填写客户字段、集团字段、匹配方式和权重。" :image-size="64"/>
        <el-table v-if="rules.length" :data="rules" row-key="id" size="small" class="rules-table">
          <el-table-column label="源字段" min-width="200"><template #default="scope">
            <el-select v-if="isProfileEditorMode" v-model="scope.row.source.fields" multiple filterable allow-create default-first-option placeholder="客户字段"><el-option v-for="field in profileSourceFields" :key="field" :label="field" :value="field"/></el-select>
            <el-select v-else v-model="scope.row.source.fields" multiple filterable placeholder="选择一个或多个源字段"><el-option v-for="field in idCandidateColumns" :key="field" :label="field" :value="field"/></el-select>
          </template></el-table-column>
          <el-table-column label="" width="46"><template #default>➜</template></el-table-column>
          <el-table-column label="目标字段" min-width="200"><template #default="scope">
            <el-select v-if="isProfileEditorMode" v-model="scope.row.target.fields" multiple filterable allow-create default-first-option placeholder="集团字段"><el-option v-for="field in profileTargetFields" :key="field" :label="field" :value="field"/></el-select>
            <el-select v-else v-model="scope.row.target.fields" multiple filterable placeholder="选择一个或多个目标字段"><el-option v-for="field in tgtHeaders.filter(field => field !== groupCodeColumn)" :key="field" :label="field" :value="field"/></el-select>
          </template></el-table-column>
          <el-table-column label="匹配方式" width="150"><template #default="scope">
            <el-select v-model="scope.row.matcher" size="small">
              <el-option label="完全一致" value="exact"/><el-option label="包含" value="contains"/><el-option label="模糊相似" value="fuzzy"/><el-option label="综合(字符+语义)" value="hybrid"/><el-option :label="embeddingReady?'语义相似(bge)':'语义(模型未就绪)'" value="semantic" :disabled="!embeddingReady"/>
            </el-select>
          </template></el-table-column>
          <el-table-column label="权重" width="130"><template #default="scope"><el-input-number v-model="scope.row.weight" size="small" :min="0" :max="100" controls-position="right"/></template></el-table-column>
          <el-table-column v-if="isProfileEditorMode" label="冲突阻断" width="90"><template #default="scope"><el-switch v-model="scope.row.critical" size="small"/></template></el-table-column>
          <el-table-column label="" width="60"><template #default="scope"><el-button link type="danger" size="small" @click="removeRule(scope.row.id)">删除</el-button></template></el-table-column>
        </el-table>
      </div>

      <div class="panel">
        <h3>{{ isProfileEditorMode ? '过滤、匹配范围与阈值' : '③ 匹配设置' }}</h3>
        <div class="filter-row">
          <el-switch v-model="filterEnabled"/><span>仅处理满足条件的源数据行</span>
          <template v-if="filterEnabled">
            <el-select v-model="filterField" placeholder="字段" style="width:180px" filterable :allow-create="isProfileEditorMode" default-first-option>
              <el-option v-for="column in (isProfileEditorMode ? profileSourceFields : srcHeaders)" :key="column" :label="column" :value="column"/>
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
        <template v-if="isProfileEditorMode">
          <h4 class="click" @click="advanced=!advanced">高级配置{{ advanced ? ' ▲' : ' ▼' }}</h4>
          <div v-if="advanced" class="threshold">
            <span>max_length</span>
            <el-select v-model="retrievalMaxLength" style="width:110px"><el-option :value="128" label="128"/><el-option :value="192" label="192"/><el-option :value="256" label="256"/><el-option :value="512" label="512"/></el-select>
            <span class="muted">匹配范围</span>
            <el-select v-model="scopeMode" style="width:150px"><el-option label="全库匹配" value="GLOBAL"/><el-option label="同组匹配" value="STRICT"/><el-option label="分类映射" value="MAPPED"/></el-select>
            <template v-if="scopeMode!=='GLOBAL'">
              <el-select v-model="scopeSourceField" filterable allow-create default-first-option placeholder="源分类字段" style="width:160px"><el-option v-for="column in profileSourceFields" :key="column" :label="column" :value="column"/></el-select>
              <el-select v-model="scopeTargetField" filterable allow-create default-first-option placeholder="目标分类字段" style="width:160px"><el-option v-for="column in profileTargetFields" :key="column" :label="column" :value="column"/></el-select>
            </template>
          </div>
        </template>
        <div class="actions">
          <template v-if="isProfileEditorMode">
            <el-button :loading="busy" @click="saveProfileDraft">保存草稿</el-button>
            <el-button type="primary" :loading="busy" :disabled="reviewThreshold >= successThreshold" @click="publishProfileChanges">{{ editingProfilePublishedVersion ? '校验并发布新版本' : '校验并发布' }}</el-button>
          </template>
          <template v-else>
            <el-button :loading="busy" :disabled="!configValid" @click="dryRun">试算 100 条</el-button>
            <el-button type="primary" :loading="busy" :disabled="!configValid" @click="start">开始匹配 →</el-button>
          </template>
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
        <el-button :type="filterMode2==='conflict'?'primary':'default'" size="small" @click="filterMode2='conflict';loadWorkbench()">重要信息冲突</el-button>
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
      <div class="actions"><el-button @click="stage=1">← 查看进度</el-button><el-button type="primary" @click="finalizeAndOpenResults">下一步:输出结果 →</el-button></div>
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

<style scoped>
.workspace-toolbar {
  gap: 20px;
  align-items: flex-start;
}
.workspace-toolbar > div:first-child {
  min-width: 0;
  flex: 1 1 auto;
}
.toolbar-actions {
  display: flex;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 8px;
  max-width: 100%;
}
.toolbar-actions :deep(.el-button + .el-button) {
  margin-left: 0;
}
.step1-data-panel {
  overflow: visible;
}
.step1-heading {
  margin-bottom: 16px;
}
.step1-subtitle,
.section-note {
  margin: 6px 0 0;
  color: var(--mm-muted);
  font-size: 12.5px;
  line-height: 1.65;
}
.profile-compatibility-alert {
  margin-top: 14px;
}
.task-name-row {
  display: grid;
  grid-template-columns: 100px minmax(0, 520px);
  align-items: center;
  gap: 12px;
  margin: 4px 0 18px;
}
.task-name-row label,
.profile-editor-meta label > span {
  font-size: 13px;
  font-weight: 600;
  color: #475569;
}
.profile-template-name {
  display: flex;
  gap: 8px;
  align-items: center;
  margin: 8px 0 0;
  font-size: 17px;
  font-weight: 700;
}
.profile-summary-grid {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 10px;
  margin: 14px 0;
}
.profile-summary-grid > div {
  min-width: 0;
  padding: 12px 14px;
  border: 1px solid var(--mm-line);
  border-radius: 10px;
  background: #f8fafc;
}
.profile-summary-grid .wide {
  grid-column: span 4;
}
.profile-summary-grid span,
.profile-summary-grid b {
  display: block;
}
.profile-summary-grid span {
  color: var(--mm-muted);
  font-size: 11.5px;
}
.profile-summary-grid b {
  margin-top: 4px;
  font-size: 13.5px;
  overflow-wrap: anywhere;
}
.profile-editor-meta {
  display: grid;
  grid-template-columns: minmax(280px, 1fr) minmax(260px, 0.75fr);
  gap: 16px;
  padding-bottom: 18px;
  margin-bottom: 18px;
  border-bottom: 1px solid var(--mm-line);
}
.profile-editor-meta label {
  display: flex;
  flex-direction: column;
  gap: 7px;
  min-width: 0;
}
.compatibility-list {
  padding-top: 6px;
  line-height: 1.8;
}
.profile-editor-mode .panel,
.profile-task-mode .panel {
  max-width: 1180px;
}
@media (max-width: 980px) {
  .workspace-toolbar {
    flex-direction: column;
  }
  .toolbar-actions {
    justify-content: flex-start;
  }
  .profile-summary-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .profile-summary-grid .wide {
    grid-column: span 2;
  }
  .profile-editor-meta,
  .task-name-row {
    grid-template-columns: 1fr;
  }
}
</style>
