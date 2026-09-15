<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
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

const route = useRoute()
const router = useRouter()
const allowedTabs = new Set(['catalogs', 'dictionaries', 'files', 'indexes'])
const activeTab = ref(allowedTabs.has(String(route.query.tab ?? '')) ? String(route.query.tab) : 'catalogs')
const catalogs = ref<CatalogRow[]>([])
const dictionaries = ref<DictionaryRow[]>([])
const files = ref<FileRow[]>([])
const indexes = ref<IndexRow[]>([])
const loading = ref(false)
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

function humanBytes(value: number): string {
  const bytes = Number(value || 0)
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  if (bytes < 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`
  return `${(bytes / 1024 / 1024 / 1024).toFixed(2)} GB`
}
function indexRows(row: IndexRow): number | string {
  return row.metadata?.stats?.row_count ?? row.metadata?.index_metadata?.row_count ?? '-'
}
function indexAlgorithm(row: IndexRow): string {
  return row.metadata?.algorithm_version ?? row.metadata?.index_metadata?.algorithm ?? '-'
}
function columnsFromInspection(inspection: any): InspectionColumn[] {
  const sheet = inspection?.sheets?.find((item: any) => item.sheet_name === inspection.recommended_sheet)
  return sheet?.columns ?? []
}
async function load(): Promise<void> {
  loading.value = true
  try {
    const [catalogResponse, dictionaryResponse, fileResponse, indexResponse] = await Promise.all([
      api.get('/catalogs'),
      api.get('/dictionaries'),
      api.get('/files'),
      api.get('/indexes', { params: { limit: 200 } }),
    ])
    catalogs.value = catalogResponse.data ?? []
    dictionaries.value = dictionaryResponse.data ?? []
    files.value = fileResponse.data ?? []
    indexes.value = indexResponse.data?.items ?? []
  } catch (error) { ElMessage.error((error as Error).message) }
  finally { loading.value = false }
}
async function uploadTarget(selected: any): Promise<void> {
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
    ElMessage.success('集团码文件上传完成，请确认集团码字段后创建目录')
    await load()
  } catch (error) { ElMessage.error((error as Error).message) }
  finally { uploading.value = false }
}
async function createCatalog(): Promise<void> {
  if (!uploadRecord.value?.file_id || !catalogName.value.trim() || !groupCodeColumn.value) return
  creating.value = true
  try {
    await api.post('/catalogs', {
      name: catalogName.value.trim(),
      source_file_id: uploadRecord.value.file_id,
      group_code_column: groupCodeColumn.value,
    })
    ElMessage.success('集团码目录已创建，首个版本已自动激活')
    uploadRecord.value = null
    uploadColumns.value = []
    catalogName.value = ''
    groupCodeColumn.value = ''
    await load()
  } catch (error) { ElMessage.error((error as Error).message) }
  finally { creating.value = false }
}
function openVersionDialog(row: CatalogRow): void {
  selectedCatalog.value = row
  versionUploadRecord.value = null
  versionColumns.value = []
  versionGroupCodeColumn.value = row.group_code_column
  activateNewVersion.value = false
  versionDialogVisible.value = true
}
async function uploadVersionTarget(selected: any): Promise<void> {
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
    ElMessage.success('新版本文件上传完成，请确认集团码字段')
    await load()
  } catch (error) { ElMessage.error((error as Error).message) }
  finally { versionUploading.value = false }
}
async function createVersion(): Promise<void> {
  if (!selectedCatalog.value || !versionUploadRecord.value?.file_id || !versionGroupCodeColumn.value) return
  versionCreating.value = true
  try {
    await api.post(`/catalogs/${selectedCatalog.value.catalog_id}/versions`, {
      source_file_id: versionUploadRecord.value.file_id,
      group_code_column: versionGroupCodeColumn.value,
      activate: activateNewVersion.value,
    })
    ElMessage.success(activateNewVersion.value ? '新目录版本已创建并激活' : '新目录版本已创建，当前激活版本保持不变')
    versionDialogVisible.value = false
    await load()
  } catch (error) { ElMessage.error((error as Error).message) }
  finally { versionCreating.value = false }
}
async function activateVersion(row: CatalogRow): Promise<void> {
  if (row.active || row.status !== 'READY') return
  try {
    await ElMessageBox.confirm(
      `激活版本 ${row.version_id.slice(0, 12)}… 后，同目录当前激活版本会自动停用。历史任务仍引用原冻结版本。`,
      `激活“${row.name}”目录版本`,
      { confirmButtonText: '确认激活', cancelButtonText: '取消', type: 'warning' },
    )
  } catch { return }
  activatingVersionId.value = row.version_id
  try {
    await api.post(`/catalogs/${row.catalog_id}/versions/${row.version_id}/activate`)
    ElMessage.success('目录版本已激活')
    await load()
  } catch (error) { ElMessage.error((error as Error).message) }
  finally { activatingVersionId.value = '' }
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
  selectedDictionary.value = null
  dictionaryName.value = ''
  dictionaryCaseSensitive.value = true
  dictionaryRows.value = [{ source: '', target: '' }]
  dictionaryDialogVisible.value = true
}
async function newDictionaryVersion(row: DictionaryRow): Promise<void> {
  try {
    const detail = (await api.get(`/dictionaries/${row.dictionary_id}`)).data
    selectedDictionary.value = row
    dictionaryName.value = row.name
    dictionaryCaseSensitive.value = detail.latest?.document?.case_sensitive ?? true
    dictionaryRows.value = Object.entries(detail.latest?.document?.mapping ?? {}).map(([source, target]) => ({ source, target: String(target) }))
    if (!dictionaryRows.value.length) dictionaryRows.value = [{ source: '', target: '' }]
    dictionaryDialogVisible.value = true
  } catch (error) { ElMessage.error((error as Error).message) }
}
async function saveDictionary(): Promise<void> {
  const mapping = mappingFromRows()
  if (!Object.keys(mapping).length || (!selectedDictionary.value && !dictionaryName.value.trim())) return
  dictionarySaving.value = true
  try {
    if (selectedDictionary.value) {
      const result = (await api.post(`/dictionaries/${selectedDictionary.value.dictionary_id}/versions`, {
        mapping,
        case_sensitive: dictionaryCaseSensitive.value,
      })).data
      ElMessage.success(`业务字典新版本 v${result.version_no} 已创建`)
    } else {
      await api.post('/dictionaries', {
        name: dictionaryName.value.trim(),
        mapping,
        case_sensitive: dictionaryCaseSensitive.value,
      })
      ElMessage.success('业务字典已创建')
    }
    dictionaryDialogVisible.value = false
    await load()
  } catch (error) { ElMessage.error((error as Error).message) }
  finally { dictionarySaving.value = false }
}
async function showDictionaryHistory(row: DictionaryRow): Promise<void> {
  try {
    selectedDictionary.value = row
    dictionaryVersions.value = (await api.get(`/dictionaries/${row.dictionary_id}/versions`)).data ?? []
    dictionaryHistoryVisible.value = true
  } catch (error) { ElMessage.error((error as Error).message) }
}

watch(activeTab, value => { void router.replace({ path: '/data', query: { tab: value } }) })
onMounted(load)
</script>

<template>
  <div>
    <div class="toolbar">
      <div>
        <h2>基础数据</h2>
        <p>统一管理集团码目录、业务字典、上传文件和向量索引。所有会影响匹配的资产都使用不可变版本。</p>
      </div>
      <el-button @click="load" :loading="loading">刷新</el-button>
    </div>

    <div class="panel">
      <el-tabs v-model="activeTab">
        <el-tab-pane label="集团码目录" name="catalogs">
          <div class="catalog-create">
            <div><b>新增集团码目录</b><p class="muted">新建目录时首个 READY 版本自动激活；后续可上传不可变新版本，并显式决定何时切换。</p></div>
            <el-upload :auto-upload="false" :show-file-list="false" :on-change="uploadTarget"><el-button :loading="uploading">选择集团码文件</el-button></el-upload>
          </div>
          <div v-if="uploadRecord" class="catalog-form">
            <el-input v-model="catalogName" placeholder="目录名称" />
            <el-select v-model="groupCodeColumn" placeholder="集团码字段"><el-option v-for="column in uploadColumns" :key="column" :label="column" :value="column" /></el-select>
            <span class="muted">{{ uploadRecord.original_name }}</span>
            <el-button type="primary" :loading="creating" :disabled="!catalogName||!groupCodeColumn" @click="createCatalog">创建目录</el-button>
          </div>
          <el-alert title="每一行都是一个不可变目录版本。任务选择版本后会冻结 version_id，不随以后 active 切换漂移。" type="info" :closable="false" style="margin-bottom:12px" />
          <el-table :data="catalogs" v-loading="loading" empty-text="尚无集团码目录">
            <el-table-column prop="name" label="目录名称" min-width="170" />
            <el-table-column label="版本ID" min-width="180"><template #default="scope"><code>{{ scope.row.version_id.slice(0, 12) }}…</code></template></el-table-column>
            <el-table-column prop="group_code_column" label="集团码字段" min-width="130" />
            <el-table-column prop="status" label="状态" width="100" />
            <el-table-column label="激活" width="90"><template #default="scope"><el-tag :type="scope.row.active ? 'success' : 'info'">{{ scope.row.active ? '当前' : '否' }}</el-tag></template></el-table-column>
            <el-table-column prop="created_at" label="创建时间" min-width="175" />
            <el-table-column label="操作" min-width="190"><template #default="scope"><el-button v-if="scope.row.active" link type="primary" @click="openVersionDialog(scope.row)">上传新版本</el-button><el-button v-if="!scope.row.active && scope.row.status==='READY'" link type="success" :loading="activatingVersionId===scope.row.version_id" @click="activateVersion(scope.row)">激活</el-button></template></el-table-column>
          </el-table>
        </el-tab-pane>

        <el-tab-pane label="业务字典" name="dictionaries">
          <div class="catalog-create">
            <div><b>同义词 / 规范值字典</b><p class="muted">字典只有在规则显式配置 dictionary_map 时才生效；系统不会偷偷做同义词替换。</p></div>
            <el-button type="primary" @click="newDictionary">新建业务字典</el-button>
          </div>
          <el-alert title="发布任务或方案时会冻结 dictionary_id、version_no、SHA-256 和该版本映射内容；新增字典版本不会改变历史结果。" type="info" :closable="false" style="margin-bottom:12px" />
          <el-table :data="dictionaries" v-loading="loading" empty-text="尚无业务字典">
            <el-table-column prop="name" label="字典名称" min-width="180" />
            <el-table-column label="最新版本" width="100"><template #default="scope">v{{ scope.row.latest_version }}</template></el-table-column>
            <el-table-column prop="entry_count" label="映射条目" width="110" />
            <el-table-column label="SHA-256" min-width="180"><template #default="scope"><code>{{ scope.row.latest_sha256?.slice(0, 16) }}…</code></template></el-table-column>
            <el-table-column prop="updated_at" label="更新时间" min-width="180" />
            <el-table-column label="操作" width="190"><template #default="scope"><el-button link type="primary" @click="newDictionaryVersion(scope.row)">创建新版本</el-button><el-button link @click="showDictionaryHistory(scope.row)">历史</el-button></template></el-table-column>
          </el-table>
        </el-tab-pane>

        <el-tab-pane label="文件资产" name="files">
          <el-table :data="files" v-loading="loading" empty-text="尚无文件资产">
            <el-table-column prop="original_name" label="文件名" min-width="220" />
            <el-table-column prop="role" label="用途" width="120" />
            <el-table-column label="大小" width="120"><template #default="scope">{{ humanBytes(scope.row.size_bytes) }}</template></el-table-column>
            <el-table-column prop="status" label="状态" width="110" />
            <el-table-column prop="file_id" label="File ID" min-width="220" show-overflow-tooltip />
            <el-table-column prop="created_at" label="上传时间" min-width="190" />
          </el-table>
        </el-tab-pane>

        <el-tab-pane label="向量索引" name="indexes">
          <el-alert title="索引由正式向量任务按 Target 指纹自动构建和复用；目录或字典处理语义变化后，指纹会随冻结配置变化。" type="info" :closable="false" />
          <el-table :data="indexes" v-loading="loading" empty-text="尚无向量索引" style="margin-top:14px">
            <el-table-column prop="index_id" label="Index ID" min-width="250" show-overflow-tooltip />
            <el-table-column prop="catalog_version_id" label="目录版本" min-width="220" show-overflow-tooltip />
            <el-table-column prop="status" label="状态" width="110" />
            <el-table-column label="行数" width="120"><template #default="scope">{{ indexRows(scope.row) }}</template></el-table-column>
            <el-table-column label="算法" min-width="180"><template #default="scope">{{ indexAlgorithm(scope.row) }}</template></el-table-column>
            <el-table-column prop="created_at" label="创建时间" min-width="190" />
          </el-table>
        </el-tab-pane>
      </el-tabs>
    </div>

    <el-dialog v-model="versionDialogVisible" :title="selectedCatalog ? `上传新版本：${selectedCatalog.name}` : '上传目录新版本'" width="680px">
      <el-alert title="新版本会创建新的 version_id，不覆盖当前版本。勾选立即激活时，当前版本只会变为非激活，历史任务不受影响。" type="info" :closable="false" />
      <div class="version-form">
        <el-upload :auto-upload="false" :show-file-list="false" :on-change="uploadVersionTarget"><el-button :loading="versionUploading">选择新版本 Excel / CSV</el-button></el-upload>
        <span v-if="versionUploadRecord" class="muted">{{ versionUploadRecord.original_name }}</span>
        <el-select v-if="versionColumns.length" v-model="versionGroupCodeColumn" placeholder="确认集团码字段"><el-option v-for="column in versionColumns" :key="column" :label="column" :value="column" /></el-select>
        <el-checkbox v-model="activateNewVersion">创建后立即激活</el-checkbox>
      </div>
      <template #footer><el-button @click="versionDialogVisible=false">取消</el-button><el-button type="primary" :loading="versionCreating" :disabled="!versionUploadRecord||!versionGroupCodeColumn" @click="createVersion">创建新版本</el-button></template>
    </el-dialog>

    <el-dialog v-model="dictionaryDialogVisible" :title="selectedDictionary ? `创建新版本：${selectedDictionary.name}` : '新建业务字典'" width="760px">
      <el-form label-width="110px">
        <el-form-item label="字典名称"><el-input v-model="dictionaryName" :disabled="Boolean(selectedDictionary)" /></el-form-item>
        <el-form-item label="大小写敏感"><el-switch v-model="dictionaryCaseSensitive" /></el-form-item>
        <el-form-item label="映射">
          <div class="mapping-editor">
            <div v-for="(row,index) in dictionaryRows" :key="index" class="mapping-row"><el-input v-model="row.source" placeholder="原值 / 同义词"/><span>→</span><el-input v-model="row.target" placeholder="规范值"/><el-button link type="danger" @click="dictionaryRows.splice(index,1)">删除</el-button></div>
            <el-button link @click="dictionaryRows.push({source:'',target:''})">+ 添加映射</el-button>
          </div>
        </el-form-item>
      </el-form>
      <el-alert title="规则可选择 exact（整值映射）或 replace（文本内替换）；未显式引用本字典的规则完全不受影响。" type="info" :closable="false" />
      <template #footer><el-button @click="dictionaryDialogVisible=false">取消</el-button><el-button type="primary" :loading="dictionarySaving" :disabled="!Object.keys(mappingFromRows()).length||(!selectedDictionary&&!dictionaryName.trim())" @click="saveDictionary">{{ selectedDictionary ? '创建新版本' : '创建字典' }}</el-button></template>
    </el-dialog>

    <el-dialog v-model="dictionaryHistoryVisible" :title="selectedDictionary ? `版本历史：${selectedDictionary.name}` : '字典版本历史'" width="760px">
      <el-table :data="dictionaryVersions">
        <el-table-column label="版本" width="80"><template #default="scope">v{{ scope.row.version_no }}</template></el-table-column>
        <el-table-column label="条目" width="90"><template #default="scope">{{ Object.keys(scope.row.document?.mapping ?? {}).length }}</template></el-table-column>
        <el-table-column label="大小写" width="100"><template #default="scope">{{ scope.row.document?.case_sensitive ? '敏感' : '不敏感' }}</template></el-table-column>
        <el-table-column label="SHA-256" min-width="200"><template #default="scope"><code>{{ scope.row.sha256.slice(0,20) }}…</code></template></el-table-column>
        <el-table-column prop="created_at" label="创建时间" min-width="180" />
      </el-table>
    </el-dialog>
  </div>
</template>

<style scoped>
.catalog-create{display:flex;align-items:center;justify-content:space-between;gap:16px;margin-bottom:14px}.catalog-create p{margin:5px 0 0}.catalog-form{display:grid;grid-template-columns:minmax(220px,1fr) minmax(180px,260px) minmax(180px,1fr) auto;gap:12px;align-items:center;margin-bottom:18px}.version-form{display:flex;flex-direction:column;align-items:flex-start;gap:14px;margin-top:18px}.version-form .el-select{width:100%}.mapping-editor{width:100%;display:flex;flex-direction:column;gap:10px}.mapping-row{display:grid;grid-template-columns:1fr auto 1fr auto;gap:8px;align-items:center}.muted{color:#7b8494;font-size:13px}@media(max-width:900px){.catalog-form{grid-template-columns:1fr}.mapping-row{grid-template-columns:1fr}}
</style>
