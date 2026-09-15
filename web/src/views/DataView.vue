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
type InspectionColumn = { header: string; business_hint?: string | null }

const route = useRoute()
const router = useRouter()
const allowedTabs = new Set(['catalogs', 'files', 'indexes'])
const activeTab = ref(allowedTabs.has(String(route.query.tab ?? '')) ? String(route.query.tab) : 'catalogs')
const catalogs = ref<CatalogRow[]>([])
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
    const [catalogResponse, fileResponse, indexResponse] = await Promise.all([
      api.get('/catalogs'),
      api.get('/files'),
      api.get('/indexes', { params: { limit: 200 } }),
    ])
    catalogs.value = catalogResponse.data ?? []
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
    const result = (await api.post(`/catalogs/${selectedCatalog.value.catalog_id}/versions`, {
      source_file_id: versionUploadRecord.value.file_id,
      group_code_column: versionGroupCodeColumn.value,
      activate: activateNewVersion.value,
    })).data
    ElMessage.success(activateNewVersion.value ? '新目录版本已创建并激活' : '新目录版本已创建，当前激活版本保持不变')
    versionDialogVisible.value = false
    await load()
    if (result.active) selectedCatalog.value = result
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

watch(activeTab, value => { void router.replace({ path: '/data', query: { tab: value } }) })
onMounted(load)
</script>

<template>
  <div>
    <div class="toolbar">
      <div>
        <h2>基础数据</h2>
        <p>统一管理集团码目录版本、上传文件和向量索引。目录版本不可覆盖，历史任务始终保留冻结版本。</p>
      </div>
      <el-button @click="load" :loading="loading">刷新</el-button>
    </div>

    <div class="panel">
      <el-tabs v-model="activeTab">
        <el-tab-pane label="集团码目录" name="catalogs">
          <div class="catalog-create">
            <div>
              <b>新增集团码目录</b>
              <p class="muted">新建目录时首个 READY 版本自动激活；后续可上传不可变新版本，并显式决定何时切换激活版本。</p>
            </div>
            <el-upload :auto-upload="false" :show-file-list="false" :on-change="uploadTarget">
              <el-button :loading="uploading">选择集团码文件</el-button>
            </el-upload>
          </div>
          <div v-if="uploadRecord" class="catalog-form">
            <el-input v-model="catalogName" placeholder="目录名称" />
            <el-select v-model="groupCodeColumn" placeholder="集团码字段">
              <el-option v-for="column in uploadColumns" :key="column" :label="column" :value="column" />
            </el-select>
            <span class="muted">{{ uploadRecord.original_name }}</span>
            <el-button type="primary" :loading="creating" :disabled="!catalogName||!groupCodeColumn" @click="createCatalog">创建目录</el-button>
          </div>
          <el-alert title="每一行都是一个不可变目录版本。激活只切换后续默认使用的版本，不修改已创建任务的 catalog_version_id。" type="info" :closable="false" style="margin-bottom:12px" />
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
          <el-alert title="索引由正式向量任务按 Target 指纹自动构建和复用；目录切换不会伪造索引 READY，新版本首次执行时按实际指纹决定构建或复用。" type="info" :closable="false" />
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
        <el-upload :auto-upload="false" :show-file-list="false" :on-change="uploadVersionTarget">
          <el-button :loading="versionUploading">选择新版本 Excel / CSV</el-button>
        </el-upload>
        <span v-if="versionUploadRecord" class="muted">{{ versionUploadRecord.original_name }}</span>
        <el-select v-if="versionColumns.length" v-model="versionGroupCodeColumn" placeholder="确认集团码字段">
          <el-option v-for="column in versionColumns" :key="column" :label="column" :value="column" />
        </el-select>
        <el-checkbox v-model="activateNewVersion">创建后立即激活</el-checkbox>
      </div>
      <template #footer><el-button @click="versionDialogVisible=false">取消</el-button><el-button type="primary" :loading="versionCreating" :disabled="!versionUploadRecord||!versionGroupCodeColumn" @click="createVersion">创建新版本</el-button></template>
    </el-dialog>
  </div>
</template>

<style scoped>
.catalog-create{display:flex;align-items:center;justify-content:space-between;gap:16px;margin-bottom:14px}.catalog-create p{margin:5px 0 0}.catalog-form{display:grid;grid-template-columns:minmax(220px,1fr) minmax(180px,260px) minmax(180px,1fr) auto;gap:12px;align-items:center;margin-bottom:18px}.version-form{display:flex;flex-direction:column;align-items:flex-start;gap:14px;margin-top:18px}.version-form .el-select{width:100%}.muted{color:#7b8494;font-size:13px}@media(max-width:900px){.catalog-form{grid-template-columns:1fr}}
</style>
