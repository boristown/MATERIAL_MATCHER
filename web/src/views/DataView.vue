<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
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
  created_by?: string
  created_at: string
}
type MappingRow = { source: string; target: string; checked?: boolean }
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

const selectedId = ref('')
const selectedName = ref('')
const currentVersion = ref(0)
const currentUpdated = ref('')
const creatingNew = ref(false)
const newName = ref('')
const rows = ref<MappingRow[]>([])
const baseRows = ref<string>('')
const baseVersion = ref(0)
const caseSensitive = ref(true)
const baseCaseSensitive = ref(true)
const searchKeyword = ref('')
const saving = ref(false)
const historyVisible = ref(false)
const historyVersions = ref<DictionaryVersion[]>([])

const selected = computed(() => dictionaries.value.find(item => item.dictionary_id === selectedId.value) ?? null)
const dirty = computed(() => serializeRows() !== baseRows.value || caseSensitive.value !== baseCaseSensitive.value || creatingNew.value)
const hasChanges = computed(() => serializeRows() !== baseRows.value || caseSensitive.value !== baseCaseSensitive.value)
const mappingCount = computed(() => Object.keys(mappingFromRows()).length)
const canonicalGroups = computed(() => {
  const counts = new Map<string, number>()
  for (const row of rows.value) {
    const target = row.target.trim()
    if (!target) continue
    counts.set(target, (counts.get(target) ?? 0) + 1)
  }
  return [...counts.entries()]
    .filter(([, count]) => count > 1)
    .map(([canonical, count]) => ({ canonical, count }))
    .sort((a, b) => b.count - a.count)
    .slice(0, 6)
})
const visibleRows = computed(() => {
  const keyword = searchKeyword.value.trim().toLowerCase()
  return rows.value
    .map((row, index) => ({ row, index }))
    .filter(({ row }) => !keyword || row.source.toLowerCase().includes(keyword) || row.target.toLowerCase().includes(keyword))
})
const checkedCount = computed(() => rows.value.filter(row => row.checked).length)
const pageAllChecked = computed(() => visibleRows.value.length > 0 && visibleRows.value.every(({ row }) => Boolean(row.checked)))
const pageSomeChecked = computed(() => !pageAllChecked.value && visibleRows.value.some(({ row }) => Boolean(row.checked)))
function togglePageAll(checked: boolean): void {
  for (const { row } of visibleRows.value) row.checked = checked
}
async function removeCheckedRows(): Promise<void> {
  const count = checkedCount.value
  if (!count) {
    ElMessage.warning('请先勾选要删除的同义词规则')
    return
  }
  try {
    await ElMessageBox.confirm(
      `将删除已勾选的 ${count} 条同义词规则。点击“确认删除”后请在“保存修改”生成新的不可变版本；历史任务仍使用当时版本，不会被改变。`,
      `批量删除 ${count} 条`,
      { type: 'warning', confirmButtonText: `确认删除 ${count} 条`, cancelButtonText: '取消' },
    )
  } catch {
    return
  }
  rows.value = rows.value.filter(row => !row.checked)
  if (!rows.value.length) rows.value.push({ source: '', target: '' })
}

function serializeRows(): string {
  return JSON.stringify(rows.value.map(row => [row.source.trim(), row.target.trim()]))
}
function mappingFromRows(): Record<string, string> {
  const mapping: Record<string, string> = {}
  for (const row of rows.value) {
    const source = row.source.trim()
    if (!source) continue
    mapping[source] = row.target.trim()
  }
  return mapping
}
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
    if (!selectedId.value && dictionaries.value.length) await openForEdit(dictionaries.value[0])
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    loading.value = false
  }
}
async function openForEdit(row: DictionaryRow): Promise<void> {
  try {
    const detail = (await api.get(`/dictionaries/${row.dictionary_id}`)).data
    const document = detail.latest?.document ?? {}
    creatingNew.value = false
    selectedId.value = row.dictionary_id
    selectedName.value = row.name
    currentVersion.value = Number(detail.latest?.version_no ?? row.latest_version ?? 0)
    currentUpdated.value = row.updated_at
    baseVersion.value = currentVersion.value
    caseSensitive.value = Boolean(document.case_sensitive ?? true)
    baseCaseSensitive.value = caseSensitive.value
    rows.value = Object.entries((document.mapping ?? {}) as Record<string, string>).map(([source, target]) => ({ source, target: String(target) }))
    baseRows.value = serializeRows()
    searchKeyword.value = ''
  } catch (error) {
    ElMessage.error((error as Error).message)
  }
}
function switchDictionary(dictionaryId: string): void {
  const row = dictionaries.value.find(item => item.dictionary_id === dictionaryId)
  if (row) void openForEdit(row)
}
function startCreate(): void {
  if (!canMaintain.value) return
  creatingNew.value = true
  selectedId.value = ''
  selectedName.value = ''
  currentVersion.value = 0
  currentUpdated.value = ''
  baseVersion.value = 0
  newName.value = ''
  caseSensitive.value = true
  baseCaseSensitive.value = true
  rows.value = [{ source: '', target: '' }]
  baseRows.value = '[]'
  searchKeyword.value = ''
}
function addMappingRow(): void {
  searchKeyword.value = ''
  rows.value.push({ source: '', target: '' })
}
function removeMappingRow(index: number): void {
  rows.value.splice(index, 1)
  if (!rows.value.length) rows.value.push({ source: '', target: '' })
}
function revertChanges(): void {
  if (creatingNew.value) {
    if (dictionaries.value.length) void openForEdit(dictionaries.value[0])
    else startCreate()
    return
  }
  if (selected.value) void openForEdit(selected.value)
}
async function saveSynonyms(): Promise<void> {
  const mapping = mappingFromRows()
  if (!canMaintain.value || !Object.keys(mapping).length) return
  if (creatingNew.value && !newName.value.trim()) {
    ElMessage.warning('请填写同义词表名称')
    return
  }
  saving.value = true
  try {
    if (creatingNew.value) {
      const created = (await api.post('/dictionaries', { name: newName.value.trim(), mapping, case_sensitive: caseSensitive.value })).data
      ElMessage.success(`已保存为第 ${created.latest?.version_no ?? 1} 版`)
      await loadBusiness()
      const createdRow = dictionaries.value.find(item => item.dictionary_id === created.dictionary_id)
      if (createdRow) await openForEdit(createdRow)
    } else {
      const result = (await api.post(`/dictionaries/${selectedId.value}/versions`, {
        mapping,
        case_sensitive: caseSensitive.value,
        base_version_no: baseVersion.value,
      })).data
      ElMessage.success(`已保存为第 ${result.version_no} 版`)
      currentVersion.value = Number(result.version_no)
      baseVersion.value = currentVersion.value
      await loadBusiness()
      const refreshed = dictionaries.value.find(item => item.dictionary_id === selectedId.value)
      if (refreshed) {
        currentUpdated.value = refreshed.updated_at
        baseRows.value = serializeRows()
        baseCaseSensitive.value = caseSensitive.value
      }
    }
  } catch (error: any) {
    const code = String(error?.response?.data?.error?.code ?? error?.code ?? '')
    if (code === 'DICTIONARY_VERSION_CONFLICT') {
      ElMessage.warning(String(error?.response?.data?.error?.message ?? '同义词已被其他人更新，请刷新后基于最新版本重新编辑'))
      await loadBusiness()
      if (selected.value) await openForEdit(selected.value)
    } else {
      ElMessage.error((error as Error).message)
    }
  } finally {
    saving.value = false
  }
}
async function showHistory(): Promise<void> {
  if (!selectedId.value) return
  try {
    historyVersions.value = (await api.get(`/dictionaries/${selectedId.value}/versions`)).data ?? []
    historyVisible.value = true
  } catch (error) {
    ElMessage.error((error as Error).message)
  }
}
async function refresh(): Promise<void> {
  await loadBusiness()
  if (technicalLoaded.value) await loadAdvanced(true)
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
async function handleAdvancedChange(names: string | string[]): Promise<void> {
  const values = Array.isArray(names) ? names : [names]
  if (values.includes('technical')) await loadAdvanced()
}

onMounted(async () => {
  await loadCurrentRole()
  await loadBusiness()
  if (!dictionaries.value.length && canMaintain.value) startCreate()
})
</script>

<template>
  <div class="data-view">
    <div class="toolbar data-view__header">
      <div>
        <span class="data-view__eyebrow">业务维护</span>
        <h2>同义词配置 <el-tag class="syn-mode-tag" type="primary" effect="plain" size="small">写法归一化</el-tag></h2>
        <p>将物料中的不同写法统一为标准写法后再参与匹配。源数据和集团码标准数据都会使用同一套归一化规则。修改保存后自动形成新版本，不影响历史任务。</p>
      </div>
      <el-button @click="refresh" :loading="loading || technicalLoading">刷新</el-button>
    </div>

    <section class="dictionary-guide" aria-label="同义词说明">
      <div>
        <strong>什么时候需要同义词？</strong>
        <p>当同一种物料、厂家或规格存在简称、俗称或不同写法时，在这里登记"其他写法 → 标准写法"，匹配前两侧都会先归一，命中更稳。</p>
      </div>
      <div>
        <strong>不会影响历史结果</strong>
        <p>每条规则是单向归一：只把左侧写法转成右侧标准写法，不会反向扩大范围。保存后自动生成新版本，已运行任务仍使用当时版本，便于追溯。</p>
      </div>
      <em>{{ dictionaries.length }} 张同义词表</em>
    </section>

    <div class="panel data-business-panel" v-loading="loading">
      <div class="data-business-panel__heading">
        <div>
          <h3>当前同义词配置</h3>
          <p>直接在列表中维护；同义词只有在任务规则明确引用时才生效，不会自动改变所有匹配任务。</p>
        </div>
        <div class="heading-actions">
          <el-tag v-if="!canMaintain" type="info" effect="plain">只读查看</el-tag>
          <el-tag v-else-if="dirty" type="warning" effect="light">有未保存的修改</el-tag>
          <el-button v-if="canMaintain && !creatingNew" plain @click="startCreate">新建同义词表</el-button>
        </div>
      </div>

      <el-radio-group v-if="dictionaries.length > 1 && !creatingNew" class="syn-switch" :model-value="selectedId" @change="(value: unknown) => switchDictionary(String(value))">
        <el-radio-button v-for="item in dictionaries" :key="item.dictionary_id" :value="item.dictionary_id">{{ item.name }}</el-radio-button>
      </el-radio-group>

      <div class="syn-meta">
        <span v-if="creatingNew">同义词表：<b>新建</b></span>
        <span v-else-if="selectedId">
          同义词表：<b>{{ selectedName }}</b>
          · 当前版本：<b>第 {{ currentVersion }} 版</b>
          · 共 {{ mappingCount }} 条
          · 最近更新：{{ formatDateTime(currentUpdated) }}
        </span>
        <el-button v-if="selectedId && !creatingNew" link type="primary" @click="showHistory">查看历史</el-button>
      </div>

      <div v-if="creatingNew" class="syn-name">
        <span>同义词表名称</span>
        <el-input v-model="newName" maxlength="120" placeholder="例如：物料名称同义词" class="syn-name__input" :disabled="!canMaintain" />
      </div>

      <div class="syn-settings">
        <span class="syn-settings__title">匹配设置</span>
        <label class="syn-settings__item">
          <span>区分大小写</span>
          <el-switch v-model="caseSensitive" :disabled="!canMaintain" />
          <em>关闭后，ABC 与 abc 按相同写法处理。</em>
        </label>
      </div>

      <div class="syn-example">
        <strong>例如</strong>
        <span class="syn-example__pair"><code>光耦</code><i>→</i><code>光电耦合器</code></span>
        <span class="syn-example__pair"><code>光耦合集成电路</code><i>→</i><code>光电耦合器</code></span>
        <em>匹配时两边都会先转换成标准写法，再进行比较。</em>
      </div>

      <div class="syn-toolbar">
        <el-input v-model="searchKeyword" clearable placeholder="搜索同义词（其他写法或标准写法）" class="syn-search" />
        <div class="syn-toolbar__actions">
          <el-button v-if="canMaintain" type="danger" plain :disabled="!checkedCount" @click="removeCheckedRows">删除已选 {{ checkedCount }} 条</el-button>
          <el-button v-if="canMaintain" :disabled="!dirty" @click="revertChanges">放弃修改</el-button>
          <el-button v-if="canMaintain" type="primary" plain @click="addMappingRow">+ 添加一条</el-button>
          <el-button v-if="canMaintain" type="primary" :loading="saving" :disabled="!mappingCount || !dirty" @click="saveSynonyms">保存修改</el-button>
        </div>
      </div>

      <div class="syn-grid" :class="{ 'is-readonly': !canMaintain }">
        <div class="syn-grid__head">
          <span class="syn-check-head">
            <el-checkbox
              v-if="canMaintain"
              :model-value="pageAllChecked"
              :indeterminate="pageSomeChecked"
              :disabled="!visibleRows.length"
              aria-label="本页全选或取消全选"
              @change="(value: boolean) => togglePageAll(Boolean(value))"
            />
          </span>
          <span>其他写法</span>
          <span class="syn-arrow" aria-hidden="true"></span>
          <span>标准写法</span>
          <span class="syn-actions-head">操作</span>
        </div>
        <div v-for="{ row, index } in visibleRows" :key="index" class="syn-grid__row">
          <span class="syn-check">
            <el-checkbox v-if="canMaintain" v-model="row.checked" :aria-label="`选择同义词 ${row.source || '(新行)'}`" />
          </span>
          <el-input v-model="row.source" placeholder="例如：光耦" :disabled="!canMaintain" />
          <span class="syn-arrow" aria-hidden="true">→</span>
          <el-input v-model="row.target" placeholder="例如：光电耦合器" :disabled="!canMaintain" />
          <span class="syn-actions">
            <el-button v-if="canMaintain" link type="danger" @click="removeMappingRow(index)">删除</el-button>
          </span>
        </div>
        <p v-if="!visibleRows.length && rows.length" class="syn-empty">没有匹配“{{ searchKeyword }}”的同义词。</p>
        <p v-if="!rows.length" class="syn-empty">还没有同义词，点击“+ 添加一条”开始维护。</p>
      </div>
      <p v-if="canonicalGroups.length" class="syn-groups">
        <span class="syn-groups__label">标准写法聚合</span>
        <el-tag v-for="group in canonicalGroups" :key="group.canonical" type="info" effect="plain" size="small">{{ group.canonical }} ← {{ group.count }} 种写法</el-tag>
      </p>
      <p class="syn-save-note">保存后将形成新的同义词版本，历史任务不会受到影响。</p>
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

    <el-dialog v-model="historyVisible" :title="`同义词版本历史：${selectedName}`" width="820px">
      <p class="history-explain">历史版本仅供查看，不可修改；已运行的任务始终使用当时的版本。</p>
      <el-table :data="historyVersions" empty-text="暂无历史版本">
        <el-table-column type="expand">
          <template #default="scope">
            <div class="history-detail">
              <div class="history-detail__head"><span>其他写法</span><span>→</span><span>标准写法</span></div>
              <div v-for="(value, key) in scope.row.document?.mapping ?? {}" :key="key" class="history-detail__row">
                <span>{{ key }}</span><span>→</span><span>{{ value }}</span>
              </div>
            </div>
          </template>
        </el-table-column>
        <el-table-column label="版本" width="110"><template #default="scope">第 {{ scope.row.version_no }} 版</template></el-table-column>
        <el-table-column label="映射条数" width="110"><template #default="scope">{{ Object.keys(scope.row.document?.mapping ?? {}).length }} 条</template></el-table-column>
        <el-table-column label="大小写规则" width="130"><template #default="scope">{{ scope.row.document?.case_sensitive ? '区分大小写' : '不区分大小写' }}</template></el-table-column>
        <el-table-column label="创建账号" min-width="120"><template #default="scope">{{ scope.row.created_by || '-' }}</template></el-table-column>
        <el-table-column label="创建时间" min-width="170"><template #default="scope">{{ formatDateTime(scope.row.created_at) }}</template></el-table-column>
      </el-table>
    </el-dialog>
  </div>
</template>

<style scoped src="../styles/pages/data.css"></style>
