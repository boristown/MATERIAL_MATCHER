<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
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
    ElMessage.success('集团码目录已创建')
    uploadRecord.value = null
    uploadColumns.value = []
    catalogName.value = ''
    groupCodeColumn.value = ''
    await load()
  } catch (error) { ElMessage.error((error as Error).message) }
  finally { creating.value = false }
}

watch(activeTab, value => { void router.replace({ path: '/data', query: { tab: value } }) })
onMounted(load)
</script>

<template>
  <div>
    <div class="toolbar">
      <div>
        <h2>基础数据</h2>
        <p>统一查看集团码目录、上传文件和向量索引。这里只管理真实运行资产，不提供不会被执行引擎消费的“装饰性配置”。</p>
      </div>
      <el-button @click="load" :loading="loading">刷新</el-button>
    </div>

    <div class="panel">
      <el-tabs v-model="activeTab">
        <el-tab-pane label="集团码目录" name="catalogs">
          <div class="catalog-create">
            <div>
              <b>新增集团码目录</b>
              <p class="muted">先上传 Target Excel/CSV，再确认集团码字段。当前创建的是一个新的目录资产；目录版本升级/激活将在下一阶段继续补齐。</p>
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
          <el-table :data="catalogs" v-loading="loading" empty-text="尚无集团码目录">
            <el-table-column prop="name" label="目录名称" min-width="180" />
            <el-table-column prop="version_id" label="版本ID" min-width="220" show-overflow-tooltip />
            <el-table-column prop="group_code_column" label="集团码字段" min-width="150" />
            <el-table-column prop="status" label="状态" width="100" />
            <el-table-column label="激活" width="90"><template #default="scope"><el-tag :type="scope.row.active ? 'success' : 'info'">{{ scope.row.active ? '是' : '否' }}</el-tag></template></el-table-column>
            <el-table-column prop="created_at" label="创建时间" min-width="190" />
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
          <el-alert title="索引由正式向量任务按 Target 指纹自动构建和复用；本页只显示真实持久化状态，不手工伪造 READY。" type="info" :closable="false" />
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
  </div>
</template>

<style scoped>
.catalog-create{display:flex;align-items:center;justify-content:space-between;gap:16px;margin-bottom:14px}.catalog-create p{margin:5px 0 0}.catalog-form{display:grid;grid-template-columns:minmax(220px,1fr) minmax(180px,260px) minmax(180px,1fr) auto;gap:12px;align-items:center;margin-bottom:18px}.muted{color:#7b8494;font-size:13px}@media(max-width:900px){.catalog-form{grid-template-columns:1fr}}
</style>
