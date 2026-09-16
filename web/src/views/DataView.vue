<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '../api'

type CatalogRow = {
  catalog_id: string
  version_id: string
  name: string
  source_file_id: string
  group_code_column: string
  status: string
  active: number
  created_at: string
}
type FileRow = {
  file_id: string
  role: string
  original_name: string
  size_bytes: number
  status: string
  created_at: string
}
type IndexRow = {
  index_id: string
  catalog_version_id: string
  status: string
  created_at: string
  metadata?: Record<string, any>
}
type DictionaryRow = {
  dictionary_id: string
  name: string
  latest_version: number
  latest_sha256: string
  entry_count: number
  updated_at: string
}
type DictionaryVersion = {
  version_no: number
  sha256: string
  document: { mapping: Record<string, string>; case_sensitive: boolean }
  created_at: string
}
type MappingEditorRow = { source: string; target: string }
type InspectionColumn = { header: string; business_hint?: string | null }
type TagType = '' | 'success' | 'warning' | 'info' | 'danger'

const route = useRoute()
const router = useRouter()
const businessTabs = new Set(['catalogs', 'dictionaries'])
const requestedTab = String(route.query.tab ?? '')
const activeTab = ref(businessTabs.has(requestedTab) ? requestedTab : 'catalogs')
const currentRole = ref('')
const canMaintain = computed(() => currentRole.value === 'admin' || currentRole.value === 'operator')

const catalogs = ref<CatalogRow[]>([])
const dictionaries = ref<DictionaryRow[]>([])
const files = ref<FileRow[]>([])
const indexes = ref<IndexRow[]>([])
const loading = ref(false)
const technicalLoading = ref(false)
const technicalLoaded = ref(false)
const advancedSections = ref<string[]>([])

const uploading = ref(false)
const creating = ref(false)
const uploadRecord = ref<any>(null)
const uploadColumns = ref<string[]>([])
const catalogName = ref('')
const groupCodeColumn = ref('')

const versionDialogVisible = ref(false)
const selectedCatalog = ref<CatalogRow | null>(null)
const versionUploading = ref(false)
const versionCreating = ref(false)
const versionUploadRecord = ref<any>(null)
const versionColumns = ref<string[]>([])
const versionGroupCodeColumn = ref('')
const activateNewVersion = ref(false)
const activatingVersionId = ref('')

const dictionaryDialogVisible = ref(false)
const dictionaryHistoryVisible = ref(false)
const selectedDictionary = ref<DictionaryRow | null>(null)
const dictionaryName = ref('')
const dictionaryCaseSensitive = ref(true)
const dictionaryRows = ref<MappingEditorRow[]>([])
const dictionaryVersions = ref<DictionaryVersion[]>([])
const dictionarySaving = ref(false)

const catalogCount = computed(() => new Set(catalogs.value.map(row => row.catalog_id)).size)
const activeCatalogCount = computed(() => catalogs.value.filter(row => Boolean(row.active)).length)
const catalogRows = computed(() => [...catalogs.value].sort((left, right) => {
  if (Boolean(left.active) !== Boolean(right.active)) return Number(right.active) - Number(left.active)
  return Date.parse(right.created_at || '') - Date.parse(left.created_at || '')
}))

function humanBytes(value: number): string {
  const bytes = Number(value || 0)
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`
  return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`
}
function formatDateTime(value?: string | null): string {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  const pad = (part: number) => String(part).padStart(2, '0')
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}
function statusLabel(status: string): string {
  const labels: Record<string, string> = {
    READY: '可使用',
    UPLOADED: '已上传',
    PROCESSING: '处理中',
    PENDING: '待处理',
    FAILED: '处理失败',
    ACTIVE: '使用中',
    COMPLETED: '已完成',
  }
  return labels[String(status || '').toUpperCase()] ?? status ?? '-'
}
function statusTagType(status: string): TagType {
  const normalized = String(status || '').toUpperCase()
  if (normalized === 'READY' || normalized === 'ACTIVE' || normalized === 'COMPLETED') return 'success'
  if (normalized === 'FAILED') return 'danger'
  if (normalized === 'PROCESSING' || normalized === 'PENDING') return 'warning'
  return 'info'
}
function fileRoleLabel(role: string): string {
  const labels: Record<string, string> = { target: '集团码目录来源', source: '待匹配源数据', supplement: '补充数据' }
  return labels[role] ?? role
}
function indexRows(row: IndexRow): number | string {
  return row.metadata?.stats?.row_count ?? row.metadata?.index_metadata?.row_count ?? '-'
}
function indexAlgorithm(row: IndexRow): string {
  return row.metadata?.algorithm_version ?? row.metadata?.index_metadata?.algorithm ?? '-'
}
function catalogVersionNumber(row: CatalogRow): number {
  const versions = catalogs.value
    .filter(item => item.catalog_id === row.catalog_id)
    .sort((left, right) => Date.parse(left.created_at || '') - Date.parse(right.created_at || ''))
  const index = versions.findIndex(item => item.version_id === row.version_id)
  return index >= 0 ? index + 1 : 1
}
function catalogVersionLabel(row: CatalogRow): string {
  return `第 ${catalogVersionNumber(row)} 版`
}
function columnsFromInspection(inspection: any): InspectionColumn[] {
  const sheet = inspection?.sheets?.find((item: any) => item.sheet_name === inspection.recommended_sheet)
  return sheet?.columns ?? []
}
async function loadCurrentRole(): Promise<void> {
  try {
    currentRole.value = String((await api.get('/auth/me')).data?.role ?? '')
  } catch {
    currentRole.value = ''
  }
}
async function loadBusinessAssets(): Promise<void> {
  loading.value = true
  try {
    const [catalogResponse, dictionaryResponse] = await Promise.all([
      api.get('/catalogs'),
      api.get('/dictionaries'),
    ])
    catalogs.value = catalogResponse.data ?? []
    dictionaries.value = dictionaryResponse.data ?? []
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    loading.value = false
  }
}
async function loadTechnicalAssets(): Promise<void> {
  if (!canMaintain.value) return
  technicalLoading.value = true
  try {
    const [fileResponse, indexResponse] = await Promise.all([
      api.get('/files'),
      api.get('/indexes', { params: { limit: 200 } }),
    ])
    files.value = fileResponse.data ?? []
    indexes.value = indexResponse.data?.items ?? []
    technicalLoaded.value = true
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    technicalLoading.value = false
  }
}
async function load(): Promise<void> {
  await loadBusinessAssets()
  if (canMaintain.value && technicalLoaded.value) await loadTechnicalAssets()
}
async function handleAdvancedChange(names: string | string[]): Promise<void> {
  const values = Array.isArray(names) ? names : [names]
  if (values.includes('technical') && !technicalLoaded.value) await loadTechnicalAssets()
}
async function uploadTarget(selected: any): Promise<void> {
  if (!canMaintain.value) return
  uploading.value = true
  try {
    const form = new FormData()
    form.append('role', 'target')
    form.append('file', selected.raw)
    const response = (await api.post('/files/upload', form)).data
    uploadRecord.value = response.file
    const columns = columnsFromInspection(response.inspection)
    uploadColumns.value = columns.map(column => column.header)
    groupCodeColumn.value = columns.find(column => column.business_hint === 'group_code')?.header ?? uploadColumns.value[0] ?? ''
    if (!catalogName.value) catalogName.value = selected.name?.replace(/\.(xlsx|xlsm|csv)$/i, '') || '集团码目录'
    ElMessage.success('文件已读取，请确认目录名称和集团码字段')
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    uploading.value = false
  }
}
async function createCatalog(): Promise<void> {
  if (!canMaintain.value || !uploadRecord.value?.file_id || !catalogName.value.trim() || !groupCodeColumn.value) return
  creating.value = true
  try {
    await api.post('/catalogs', {
      name: catalogName.value.trim(),
      source_file_id: uploadRecord.value.file_id,
      group_code_column: groupCodeColumn.value,
    })
    ElMessage.success('集团码目录已创建并设为当前使用版本')
    uploadRecord.value = null
    uploadColumns.value = []
    catalogName.value = ''
    groupCodeColumn.value = ''
    await loadBusinessAssets()
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    creating.value = false
  }
}
function openVersionDialog(row: CatalogRow): void {
  if (!canMaintain.value) return
  selectedCatalog.value = row
  versionUploadRecord.value = null
  versionColumns.value = []
  versionGroupCodeColumn.value = row.group_code_column
  activateNewVersion.value = false
  versionDialogVisible.value = true
}
async function uploadVersionTarget(selected: any): Promise<void> {
  if (!canMaintain.value) return
  versionUploading.value = true
  try {
    const form = new FormData()
    form.append('role', 'target')
    form.append('file', selected.raw)
    const response = (await api.post('/files/upload', form)).data
    versionUploadRecord.value = response.file
    const columns = columnsFromInspection(response.inspection)
    versionColumns.value = columns.map(column => column.header)
    const previous = selectedCatalog.value?.group_code_column ?? ''
    versionGroupCodeColumn.value = versionColumns.value.includes(previous)
      ? previous
      : columns.find(column => column.business_hint === 'group_code')?.header ?? versionColumns.value[0] ?? ''
    ElMessage.success('新版本文件已读取，请确认集团码字段')
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    versionUploading.value = false
  }
}
async function createVersion(): Promise<void> {
  if (!canMaintain.value || !selectedCatalog.value || !versionUploadRecord.value?.file_id || !versionGroupCodeColumn.value) return
  versionCreating.value = true
  try {
    await api.post(`/catalogs/${selectedCatalog.value.catalog_id}/versions`, {
      source_file_id: versionUploadRecord.value.file_id,
      group_code_column: versionGroupCodeColumn.value,
      activate: activateNewVersion.value,
    })
    ElMessage.success(activateNewVersion.value ? '新版本已创建并切换为当前版本' : '新版本已创建，当前使用版本保持不变')
    versionDialogVisible.value = false
    await loadBusinessAssets()
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    versionCreating.value = false
  }
}
async function activateVersion(row: CatalogRow): Promise<void> {
  if (!canMaintain.value || row.active || row.status !== 'READY') return
  try {
    await ElMessageBox.confirm(
      `切换后，新建匹配任务会使用“${row.name}”${catalogVersionLabel(row)}。已经创建的历史任务仍保持原版本，不受影响。`,
      `设为当前使用版本`,
      { confirmButtonText: '确认切换', cancelButtonText: '取消', type: 'warning' },
    )
  } catch {
    return
  }
  activatingVersionId.value = row.version_id
  try {
    await api.post(`/catalogs/${row.catalog_id}/versions/${row.version_id}/activate`)
    ElMessage.success('已切换当前使用版本')
    await loadBusinessAssets()
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    activatingVersionId.value = ''
  }
}
function mappingFromRows(): Record<string, string> {
  const mapping: Record<string, string> = {}
  for (const row of dictionaryRows.value) {
    const source = row.source.trim()
    if (!source) continue
    mapping[source] = row.target.trim()
  }
  return mapping
}
function newDictionary(): void {
  if (!canMaintain.value) return
  selectedDictionary.value = null
  dictionaryName.value = ''
  dictionaryCaseSensitive.value = true
  dictionaryRows.value = [{ source: '', target: '' }]
  dictionaryDialogVisible.value = true
}
async function newDictionaryVersion(row: DictionaryRow): Promise<void> {
  if (!canMaintain.value) return
  try {
    const detail = (await api.get(`/dictionaries/${row.dictionary_id}`)).data
    selectedDictionary.value = row
    dictionaryName.value = row.name
    dictionaryCaseSensitive.value = detail.latest?.document?.case_sensitive ?? true
    dictionaryRows.value = Object.entries(detail.latest?.document?.mapping ?? {}).map(([source, target]) => ({ source, target: String(target) }))
    if (!dictionaryRows.value.length) dictionaryRows.value = [{ source: '', target: '' }]
    dictionaryDialogVisible.value = true
  } catch (error) {
    ElMessage.error((error as Error).message)
  }
}
async function saveDictionary(): Promise<void> {
  const mapping = mappingFromRows()
  if (!canMaintain.value || !Object.keys(mapping).length || (!selectedDictionary.value && !dictionaryName.value.trim())) return
  dictionarySaving.value = true
  try {
    if (selectedDictionary.value) {
      const result = (await api.post(`/dictionaries/${selectedDictionary.value.dictionary_id}/versions`, {
        mapping,
        case_sensitive: dictionaryCaseSensitive.value,
      })).data
      ElMessage.success(`业务字典第 ${result.version_no} 版已创建`)
    } else {
      await api.post('/dictionaries', {
        name: dictionaryName.value.trim(),
        mapping,
        case_sensitive: dictionaryCaseSensitive.value,
      })
      ElMessage.success('业务字典已创建')
    }
    dictionaryDialogVisible.value = false
    await loadBusinessAssets()
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    dictionarySaving.value = false
  }
}
async function showDictionaryHistory(row: DictionaryRow): Promise<void> {
  try {
    selectedDictionary.value = row
    dictionaryVersions.value = (await api.get(`/dictionaries/${row.dictionary_id}/versions`)).data ?? []
    dictionaryHistoryVisible.value = true
  } catch (error) {
    ElMessage.error((error as Error).message)
  }
}

watch(activeTab, value => {
  void router.replace({ path: '/data', query: { tab: value } })
})
onMounted(async () => {
  await loadCurrentRole()
  await loadBusinessAssets()
})
</script>

<template>
  <div class="data-view">
    <div class="toolbar data-view__header">
      <div>
        <span class="data-view__eyebrow">业务基础数据</span>
        <h2>基础数据</h2>
        <p>维护匹配所依赖的集团码标准和业务词义。这里的变更会影响后续新建任务，因此每次调整都会保留历史版本。</p>
      </div>
      <el-button @click="load" :loading="loading || technicalLoading">刷新</el-button>
    </div>

    <section class="data-overview" aria-label="基础数据说明">
      <article class="data-overview__item data-overview__item--primary">
        <span class="data-overview__step">01</span>
        <div>
          <strong>集团码目录</strong>
          <p>维护“最终要匹配到什么集团码”的标准目录。当前使用版本将作为新任务的匹配目标。</p>
        </div>
        <em>{{ catalogCount }} 套目录 · {{ activeCatalogCount }} 个当前版本</em>
      </article>
      <article class="data-overview__item">
        <span class="data-overview__step">02</span>
        <div>
          <strong>业务字典</strong>
          <p>维护同义词、简称和规范值映射，例如把不同写法统一成业务认可的标准表达。</p>
        </div>
        <em>{{ dictionaries.length }} 个字典</em>
      </article>
    </section>

    <div class="panel data-business-panel">
      <div class="data-business-panel__heading">
        <div>
          <h3>业务资产</h3>
          <p>日常业务维护只需要关注以下两类数据；技术文件和索引信息不参与业务操作。</p>
        </div>
        <el-tag v-if="!canMaintain" type="info" effect="plain">只读查看</el-tag>
      </div>

      <el-tabs v-model="activeTab" class="data-tabs">
        <el-tab-pane label="集团码目录" name="catalogs">
          <div class="asset-intro">
            <div>
              <b>集团码标准目录</b>
              <p>上传标准集团码表后，确认哪一列是集团码。后续更新请创建新版本，不会覆盖历史任务使用的数据。</p>
            </div>
            <el-upload v-if="canMaintain" :auto-upload="false" :show-file-list="false" :on-change="uploadTarget">
              <el-button type="primary" :loading="uploading">上传并新建目录</el-button>
            </el-upload>
          </div>

          <div v-if="uploadRecord && canMaintain" class="catalog-form data-inline-form">
            <div class="data-field">
              <label>目录名称</label>
              <el-input v-model="catalogName" placeholder="例如：集团标准物料目录" />
            </div>
            <div class="data-field">
              <label>集团码所在字段</label>
              <el-select v-model="groupCodeColumn" placeholder="请选择字段">
                <el-option v-for="column in uploadColumns" :key="column" :label="column" :value="column" />
              </el-select>
            </div>
            <div class="data-upload-file">
              <span>已读取文件</span>
              <b>{{ uploadRecord.original_name }}</b>
            </div>
            <el-button type="primary" :loading="creating" :disabled="!catalogName || !groupCodeColumn" @click="createCatalog">确认创建</el-button>
          </div>

          <div class="business-note">
            <b>为什么要保留版本？</b>
            <span>切换“当前使用版本”只影响之后新建的匹配任务，已经运行过的任务仍使用当时的数据，可追溯且不会被新数据改变。</span>
          </div>

          <el-table :data="catalogRows" v-loading="loading" empty-text="还没有集团码目录。维护人员可先上传集团码标准表创建第一套目录。">
            <el-table-column prop="name" label="目录名称" min-width="200" />
            <el-table-column label="版本" width="120">
              <template #default="scope">
                <span class="version-label">{{ catalogVersionLabel(scope.row) }}</span>
                <el-tag v-if="scope.row.active" size="small" type="success">当前</el-tag>
              </template>
            </el-table-column>
            <el-table-column prop="group_code_column" label="集团码字段" min-width="150" />
            <el-table-column label="可用状态" width="120">
              <template #default="scope"><el-tag :type="statusTagType(scope.row.status)" effect="plain">{{ statusLabel(scope.row.status) }}</el-tag></template>
            </el-table-column>
            <el-table-column label="版本时间" min-width="160">
              <template #default="scope">{{ formatDateTime(scope.row.created_at) }}</template>
            </el-table-column>
            <el-table-column v-if="canMaintain" label="操作" min-width="190" fixed="right">
              <template #default="scope">
                <el-button v-if="scope.row.active" link type="primary" @click="openVersionDialog(scope.row)">上传新版本</el-button>
                <el-button v-if="!scope.row.active && scope.row.status === 'READY'" link type="success" :loading="activatingVersionId === scope.row.version_id" @click="activateVersion(scope.row)">设为当前版本</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>

        <el-tab-pane label="业务字典" name="dictionaries">
          <div class="asset-intro">
            <div>
              <b>同义词与规范值</b>
              <p>把业务中含义相同但写法不同的词统一起来。字典只有在匹配方案明确引用时才生效，不会自动改变所有任务。</p>
            </div>
            <el-button v-if="canMaintain" type="primary" @click="newDictionary">新建业务字典</el-button>
          </div>

          <div class="business-note">
            <b>版本如何生效？</b>
            <span>方案或任务会记录实际使用的字典版本。创建新版本不会回写历史结果，便于之后解释“当时为什么这样匹配”。</span>
          </div>

          <el-table :data="dictionaries" v-loading="loading" empty-text="还没有业务字典。可按需要建立同义词、简称或规范值映射。">
            <el-table-column prop="name" label="字典名称" min-width="220" />
            <el-table-column label="当前版本" width="120"><template #default="scope">第 {{ scope.row.latest_version }} 版</template></el-table-column>
            <el-table-column prop="entry_count" label="映射规则" width="120"><template #default="scope">{{ scope.row.entry_count }} 条</template></el-table-column>
            <el-table-column label="最近更新" min-width="170"><template #default="scope">{{ formatDateTime(scope.row.updated_at) }}</template></el-table-column>
            <el-table-column label="操作" :width="canMaintain ? 220 : 100" fixed="right">
              <template #default="scope">
                <el-button v-if="canMaintain" link type="primary" @click="newDictionaryVersion(scope.row)">创建新版本</el-button>
                <el-button link @click="showDictionaryHistory(scope.row)">查看历史</el-button>
              </template>
            </el-table-column>
          </el-table>
        </el-tab-pane>
      </el-tabs>
    </div>

    <section v-if="canMaintain" class="technical-zone">
      <div class="technical-zone__heading">
        <div>
          <span class="technical-zone__label">高级信息</span>
          <h3>技术资产与运行信息</h3>
          <p>仅用于管理员/操作员排查上传文件和向量索引状态。日常业务维护无需关注，默认收起且不会提前加载。</p>
        </div>
      </div>
      <el-collapse v-model="advancedSections" @change="handleAdvancedChange">
        <el-collapse-item name="technical">
          <template #title>
            <span class="technical-collapse-title"><b>展开技术信息</b><em>文件资产 · 向量索引 · 技术标识</em></span>
          </template>
          <div class="technical-content" v-loading="technicalLoading">
            <div class="technical-block">
              <div class="technical-block__title"><b>文件资产</b><span>平台接收过的文件记录，仅用于追踪数据来源和排障。</span></div>
              <el-table :data="files" empty-text="暂无文件资产">
                <el-table-column prop="original_name" label="文件名" min-width="220" />
                <el-table-column label="用途" min-width="150"><template #default="scope">{{ fileRoleLabel(scope.row.role) }}</template></el-table-column>
                <el-table-column label="大小" width="110"><template #default="scope">{{ humanBytes(scope.row.size_bytes) }}</template></el-table-column>
                <el-table-column label="状态" width="110"><template #default="scope">{{ statusLabel(scope.row.status) }}</template></el-table-column>
                <el-table-column label="上传时间" min-width="160"><template #default="scope">{{ formatDateTime(scope.row.created_at) }}</template></el-table-column>
                <el-table-column prop="file_id" label="技术标识" min-width="200" show-overflow-tooltip />
              </el-table>
            </div>

            <div class="technical-block">
              <div class="technical-block__title"><b>向量索引</b><span>由匹配任务自动构建和复用，一般不需要手工维护。</span></div>
              <el-table :data="indexes" empty-text="暂无向量索引">
                <el-table-column label="状态" width="110"><template #default="scope"><el-tag :type="statusTagType(scope.row.status)" effect="plain">{{ statusLabel(scope.row.status) }}</el-tag></template></el-table-column>
                <el-table-column label="索引数据量" width="130"><template #default="scope">{{ indexRows(scope.row) }}</template></el-table-column>
                <el-table-column label="创建时间" min-width="160"><template #default="scope">{{ formatDateTime(scope.row.created_at) }}</template></el-table-column>
                <el-table-column label="算法信息" min-width="170"><template #default="scope">{{ indexAlgorithm(scope.row) }}</template></el-table-column>
                <el-table-column prop="catalog_version_id" label="目录版本标识" min-width="210" show-overflow-tooltip />
                <el-table-column prop="index_id" label="索引技术标识" min-width="210" show-overflow-tooltip />
              </el-table>
            </div>
          </div>
        </el-collapse-item>
      </el-collapse>
    </section>

    <el-dialog v-model="versionDialogVisible" :title="selectedCatalog ? `上传新版本：${selectedCatalog.name}` : '上传目录新版本'" width="680px">
      <div class="dialog-explain">新版本不会覆盖旧版本。你可以先创建并检查，确认后再切换；也可以勾选“创建后立即设为当前版本”。</div>
      <div class="version-form">
        <el-upload :auto-upload="false" :show-file-list="false" :on-change="uploadVersionTarget"><el-button :loading="versionUploading">选择新版本 Excel / CSV</el-button></el-upload>
        <span v-if="versionUploadRecord" class="muted">已读取：{{ versionUploadRecord.original_name }}</span>
        <div v-if="versionColumns.length" class="data-field data-field--wide">
          <label>集团码所在字段</label>
          <el-select v-model="versionGroupCodeColumn" placeholder="确认集团码字段"><el-option v-for="column in versionColumns" :key="column" :label="column" :value="column" /></el-select>
        </div>
        <el-checkbox v-model="activateNewVersion">创建后立即设为当前使用版本</el-checkbox>
      </div>
      <template #footer>
        <el-button @click="versionDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="versionCreating" :disabled="!versionUploadRecord || !versionGroupCodeColumn" @click="createVersion">创建新版本</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="dictionaryDialogVisible" :title="selectedDictionary ? `创建新版本：${selectedDictionary.name}` : '新建业务字典'" width="760px">
      <div class="dialog-explain">一条映射表示“左侧业务写法 → 右侧规范写法”。保存后会形成独立版本，不会改写已经运行的历史任务。</div>
      <el-form label-width="110px" class="dictionary-form">
        <el-form-item label="字典名称"><el-input v-model="dictionaryName" :disabled="Boolean(selectedDictionary)" placeholder="例如：材质简称规范化" /></el-form-item>
        <el-form-item label="区分大小写"><el-switch v-model="dictionaryCaseSensitive" /><span class="field-help">关闭后，ABC 与 abc 会按相同写法处理。</span></el-form-item>
        <el-form-item label="映射规则">
          <div class="mapping-editor">
            <div v-for="(row, index) in dictionaryRows" :key="index" class="mapping-row">
              <el-input v-model="row.source" placeholder="原写法 / 同义词" />
              <span>→</span>
              <el-input v-model="row.target" placeholder="规范写法" />
              <el-button link type="danger" @click="dictionaryRows.splice(index, 1)">删除</el-button>
            </div>
            <el-button link type="primary" @click="dictionaryRows.push({ source: '', target: '' })">+ 添加一条映射</el-button>
          </div>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dictionaryDialogVisible = false">取消</el-button>
        <el-button type="primary" :loading="dictionarySaving" :disabled="!Object.keys(mappingFromRows()).length || (!selectedDictionary && !dictionaryName.trim())" @click="saveDictionary">{{ selectedDictionary ? '创建新版本' : '创建字典' }}</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="dictionaryHistoryVisible" :title="selectedDictionary ? `版本历史：${selectedDictionary.name}` : '字典版本历史'" width="720px">
      <p class="history-explain">历史版本用于追溯已有任务，不会因新增版本而被覆盖。</p>
      <el-table :data="dictionaryVersions" empty-text="暂无历史版本">
        <el-table-column label="版本" width="110"><template #default="scope">第 {{ scope.row.version_no }} 版</template></el-table-column>
        <el-table-column label="映射规则" width="120"><template #default="scope">{{ Object.keys(scope.row.document?.mapping ?? {}).length }} 条</template></el-table-column>
        <el-table-column label="大小写规则" width="130"><template #default="scope">{{ scope.row.document?.case_sensitive ? '区分大小写' : '不区分大小写' }}</template></el-table-column>
        <el-table-column label="创建时间" min-width="170"><template #default="scope">{{ formatDateTime(scope.row.created_at) }}</template></el-table-column>
      </el-table>
    </el-dialog>
  </div>
</template>

<style scoped src="../styles/pages/data.css"></style>
