<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../api'

type CatalogRow = {
  catalog_id: string
  version_id: string
  name: string
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
type TagType = '' | 'success' | 'warning' | 'info' | 'danger'

const currentRole = ref('')
const canMaintain = computed(() => currentRole.value === 'admin' || currentRole.value === 'operator')
const isAdmin = computed(() => currentRole.value === 'admin')

const dictionaries = ref<DictionaryRow[]>([])
const catalogs = ref<CatalogRow[]>([])
const files = ref<FileRow[]>([])
const indexes = ref<IndexRow[]>([])
const loading = ref(false)
const technicalLoading = ref(false)
const technicalLoaded = ref(false)
const advancedSections = ref<string[]>([])

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
    BUILDING: '构建中',
  }
  return labels[String(status || '').toUpperCase()] ?? status ?? '-'
}
function statusTagType(status: string): TagType {
  const normalized = String(status || '').toUpperCase()
  if (normalized === 'READY' || normalized === 'ACTIVE' || normalized === 'COMPLETED') return 'success'
  if (normalized === 'FAILED') return 'danger'
  if (normalized === 'PROCESSING' || normalized === 'PENDING' || normalized === 'BUILDING') return 'warning'
  return 'info'
}
function fileRoleLabel(role: string): string {
  const labels: Record<string, string> = { target: '目标集团码数据', source: '源数据', supplement: '补充数据' }
  return labels[role] ?? role
}
function indexRows(row: IndexRow): number | string {
  return row.metadata?.stats?.row_count ?? row.metadata?.index_metadata?.row_count ?? '-'
}
function indexAlgorithm(row: IndexRow): string {
  return row.metadata?.algorithm_version ?? row.metadata?.index_metadata?.algorithm ?? '-'
}

async function loadCurrentRole(): Promise<void> {
  try {
    currentRole.value = String((await api.get('/auth/me')).data?.role ?? '')
  } catch {
    currentRole.value = ''
  }
}
async function loadBusiness(): Promise<void> {
  loading.value = true
  try {
    dictionaries.value = (await api.get('/dictionaries')).data ?? []
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    loading.value = false
  }
}
async function loadAdvanced(force = false): Promise<void> {
  if (!isAdmin.value || (technicalLoaded.value && !force)) return
  technicalLoading.value = true
  try {
    const [catalogResponse, fileResponse, indexResponse] = await Promise.all([
      api.get('/catalogs'),
      api.get('/files'),
      api.get('/indexes', { params: { limit: 200 } }),
    ])
    catalogs.value = catalogResponse.data ?? []
    files.value = fileResponse.data ?? []
    indexes.value = indexResponse.data?.items ?? []
    technicalLoaded.value = true
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    technicalLoading.value = false
  }
}
async function refresh(): Promise<void> {
  await loadBusiness()
  if (technicalLoaded.value) await loadAdvanced(true)
}
async function handleAdvancedChange(names: string | string[]): Promise<void> {
  const values = Array.isArray(names) ? names : [names]
  if (values.includes('technical')) await loadAdvanced()
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
    await loadBusiness()
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

onMounted(async () => {
  await loadCurrentRole()
  await loadBusiness()
})
</script>

<template>
  <div class="data-view">
    <div class="toolbar data-view__header">
      <div>
        <span class="data-view__eyebrow">业务维护</span>
        <h2>业务字典</h2>
        <p>日常匹配任务无需预先维护集团码目录。源 Excel 与目标集团码 Excel 请直接在“第一步 · 数据上传”中选择，平台会自动管理文件与索引。</p>
      </div>
      <el-button @click="refresh" :loading="loading || technicalLoading">刷新</el-button>
    </div>

    <section class="dictionary-guide" aria-label="业务字典说明">
      <div>
        <strong>什么时候需要业务字典？</strong>
        <p>当同一种材质、规格或业务术语存在简称、同义词或不同写法时，可在这里统一成标准表达。</p>
      </div>
      <div>
        <strong>不会影响历史结果</strong>
        <p>每次修改都会形成新版本；已经运行的任务仍保留当时使用的规则，便于追溯。</p>
      </div>
      <em>{{ dictionaries.length }} 个字典</em>
    </section>

    <div class="panel data-business-panel">
      <div class="data-business-panel__heading">
        <div>
          <h3>同义词与规范值</h3>
          <p>字典只有在任务规则明确引用时才生效，不会自动改变所有匹配任务。</p>
        </div>
        <div class="heading-actions">
          <el-tag v-if="!canMaintain" type="info" effect="plain">只读查看</el-tag>
          <el-button v-if="canMaintain" type="primary" @click="newDictionary">新建业务字典</el-button>
        </div>
      </div>

      <el-table :data="dictionaries" v-loading="loading" empty-text="还没有业务字典。只有存在同义词、简称或规范值需求时才需要建立。">
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
    </div>

    <section v-if="isAdmin" class="technical-zone">
      <div class="technical-zone__heading">
        <div>
          <span class="technical-zone__label">管理员高级信息</span>
          <h3>平台自动管理的数据资产</h3>
          <p>以下内容仅用于兼容历史任务和排障。普通业务用户无需理解目录版本、文件资产或向量索引。</p>
        </div>
      </div>
      <el-collapse v-model="advancedSections" @change="handleAdvancedChange">
        <el-collapse-item name="technical">
          <template #title>
            <span class="technical-collapse-title"><b>展开高级信息</b><em>历史集团码版本 · 文件记录 · 向量索引</em></span>
          </template>
          <div class="technical-content" v-loading="technicalLoading">
            <div class="technical-block">
              <div class="technical-block__title"><b>历史集团码版本</b><span>仅用于兼容既有任务；新任务在第一步直接上传目标 Excel。</span></div>
              <el-table :data="catalogs" empty-text="暂无历史集团码版本">
                <el-table-column prop="name" label="名称" min-width="220" />
                <el-table-column prop="group_code_column" label="集团码字段" min-width="150" />
                <el-table-column label="状态" width="120"><template #default="scope"><el-tag :type="statusTagType(scope.row.status)" effect="plain">{{ statusLabel(scope.row.status) }}</el-tag></template></el-table-column>
                <el-table-column label="当前使用" width="100"><template #default="scope">{{ scope.row.active ? '是' : '否' }}</template></el-table-column>
                <el-table-column label="创建时间" min-width="160"><template #default="scope">{{ formatDateTime(scope.row.created_at) }}</template></el-table-column>
              </el-table>
            </div>

            <div class="technical-block">
              <div class="technical-block__title"><b>文件记录</b><span>平台自动保存的数据来源记录，不需要业务人员手工维护。</span></div>
              <el-table :data="files" empty-text="暂无文件记录">
                <el-table-column prop="original_name" label="文件名" min-width="220" />
                <el-table-column label="用途" min-width="150"><template #default="scope">{{ fileRoleLabel(scope.row.role) }}</template></el-table-column>
                <el-table-column label="大小" width="110"><template #default="scope">{{ humanBytes(scope.row.size_bytes) }}</template></el-table-column>
                <el-table-column label="状态" width="110"><template #default="scope">{{ statusLabel(scope.row.status) }}</template></el-table-column>
                <el-table-column label="上传时间" min-width="160"><template #default="scope">{{ formatDateTime(scope.row.created_at) }}</template></el-table-column>
              </el-table>
            </div>

            <div class="technical-block">
              <div class="technical-block__title"><b>向量索引</b><span>由平台自动创建和复用，仅在排查性能或构建失败时查看。</span></div>
              <el-table :data="indexes" empty-text="暂无向量索引">
                <el-table-column label="状态" width="110"><template #default="scope"><el-tag :type="statusTagType(scope.row.status)" effect="plain">{{ statusLabel(scope.row.status) }}</el-tag></template></el-table-column>
                <el-table-column label="索引数据量" width="130"><template #default="scope">{{ indexRows(scope.row) }}</template></el-table-column>
                <el-table-column label="创建时间" min-width="160"><template #default="scope">{{ formatDateTime(scope.row.created_at) }}</template></el-table-column>
                <el-table-column label="算法信息" min-width="180"><template #default="scope">{{ indexAlgorithm(scope.row) }}</template></el-table-column>
              </el-table>
            </div>
          </div>
        </el-collapse-item>
      </el-collapse>
    </section>

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
