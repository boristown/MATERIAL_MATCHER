<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { api } from '../api'

type FileRecord = { file_id: string; original_name: string }
type InspectionColumn = { header: string; business_hint?: string | null }
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

const route = useRoute()
const router = useRouter()
const draftId = ref('')
const name = ref('')
const existingDraft = ref(false)
const source = ref<FileRecord | null>(null)
const sourceColumns = ref<string[]>([])
const sourceIdColumn = ref('')
const target = ref<FileRecord | null>(null)
const targetColumns = ref<string[]>([])
const groupCodeColumn = ref('')
const targetMode = ref<'existing' | 'upload'>('existing')
const catalogs = ref<CatalogRow[]>([])
const catalogVersionId = ref('')
const busy = ref(false)
const loading = ref(false)

const readyCatalogs = computed(() =>
  catalogs.value
    .filter(item => item.status === 'READY')
    .sort((left, right) => Number(right.active) - Number(left.active) || right.created_at.localeCompare(left.created_at)),
)
const selectedCatalog = computed(() => readyCatalogs.value.find(item => item.version_id === catalogVersionId.value) ?? null)
const canContinue = computed(() => {
  if (!name.value.trim() || !source.value || !sourceIdColumn.value) return false
  if (targetMode.value === 'existing') return Boolean(selectedCatalog.value)
  return Boolean(target.value && groupCodeColumn.value)
})

function columnsFromInspection(inspection: any): InspectionColumn[] {
  return inspection?.sheets?.find((item: any) => item.sheet_name === inspection.recommended_sheet)?.columns ?? []
}
function findHint(columns: InspectionColumn[], hint: string): string {
  return columns.find(column => column.business_hint === hint)?.header ?? ''
}
async function loadFile(fileId: string, kind: 'source' | 'target'): Promise<void> {
  const response = (await api.get(`/files/${fileId}/inspection`)).data
  const columns = columnsFromInspection(response.inspection)
  if (kind === 'source') {
    source.value = response.file
    sourceColumns.value = columns.map(column => column.header)
    if (!sourceIdColumn.value) sourceIdColumn.value = findHint(columns, 'source_id') || sourceColumns.value[0] || ''
  } else {
    target.value = response.file
    targetColumns.value = columns.map(column => column.header)
    if (!groupCodeColumn.value) groupCodeColumn.value = findHint(columns, 'group_code') || targetColumns.value[0] || ''
  }
}
async function loadCatalogs(): Promise<void> {
  catalogs.value = (await api.get('/catalogs')).data ?? []
  if (!catalogVersionId.value) {
    const current = readyCatalogs.value.find(item => item.active) ?? readyCatalogs.value[0]
    catalogVersionId.value = current?.version_id ?? ''
  }
}
async function selectCatalog(versionId: string): Promise<void> {
  const catalog = readyCatalogs.value.find(item => item.version_id === versionId)
  if (!catalog) return
  groupCodeColumn.value = catalog.group_code_column
  try { await loadFile(catalog.source_file_id, 'target') }
  catch (error) { ElMessage.error((error as Error).message) }
}
async function restoreDraft(id: string): Promise<void> {
  const draft = (await api.get(`/task-drafts/${id}`)).data
  draftId.value = draft.draft_id
  name.value = draft.name
  existingDraft.value = true
  if (Number(draft.current_step ?? 1) >= 2 && draft.source_file_id && draft.catalog_version_id) {
    await router.replace({ path: '/tasks/workspace', query: { draft: draft.draft_id } })
    return
  }
  if (draft.source_file_id) await loadFile(String(draft.source_file_id), 'source')
  if (draft.catalog_version_id) {
    catalogVersionId.value = String(draft.catalog_version_id)
    targetMode.value = 'existing'
    await selectCatalog(catalogVersionId.value)
  }
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
      sourceColumns.value = columns.map((column) => column.header)
      sourceIdColumn.value = findHint(columns, 'source_id') || sourceColumns.value[0] || ''
    } else {
      target.value = response.file
      targetColumns.value = columns.map((column) => column.header)
      groupCodeColumn.value = findHint(columns, 'group_code') || targetColumns.value[0] || ''
      targetMode.value = 'upload'
    }
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    busy.value = false
  }
}
function defaultRule(): Record<string, unknown> {
  const sourceField = sourceColumns.value.find(column => column !== sourceIdColumn.value) ?? sourceColumns.value[0] ?? ''
  const targetField = targetColumns.value.find(column => column !== groupCodeColumn.value) ?? targetColumns.value[0] ?? ''
  return {
    id: 'rule_1',
    source: { fields: sourceField ? [sourceField] : [], combine: 'concat', separator: ' ', pipeline: [] },
    target: { fields: targetField ? [targetField] : [], combine: 'concat', separator: ' ', pipeline: [] },
    matcher: 'fuzzy', weight: 80, critical: false, matcher_options: {},
  }
}
async function continueToRules(): Promise<void> {
  if (!canContinue.value || !source.value) return
  busy.value = true
  try {
    if (!draftId.value) {
      const draft = (await api.post('/task-drafts', { name: name.value.trim() })).data
      draftId.value = draft.draft_id
    }
    let versionId = catalogVersionId.value
    if (targetMode.value === 'upload') {
      if (!target.value || !groupCodeColumn.value) return
      const catalog = (await api.post('/catalogs', {
        name: `${name.value.trim()}-集团码目录`,
        source_file_id: target.value.file_id,
        group_code_column: groupCodeColumn.value,
      })).data
      versionId = catalog.version_id
    } else {
      const catalog = selectedCatalog.value
      if (!catalog) return
      groupCodeColumn.value = catalog.group_code_column
      if (!target.value || target.value.file_id !== catalog.source_file_id) await loadFile(catalog.source_file_id, 'target')
    }
    await api.put(`/task-drafts/${draftId.value}/data`, {
      source_file_id: source.value.file_id,
      catalog_version_id: versionId,
      template_profile_id: null,
      template_profile_version: null,
    })
    const current = (await api.get(`/task-drafts/${draftId.value}`)).data.config_document ?? {}
    const document = {
      ...current,
      source_id_column: sourceIdColumn.value,
      rules: Array.isArray(current.rules) && current.rules.length ? current.rules : [defaultRule()],
    }
    await api.put(`/task-drafts/${draftId.value}/rules`, document)
    await router.push({ path: '/tasks/workspace', query: { draft: draftId.value } })
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    busy.value = false
  }
}

onMounted(async () => {
  loading.value = true
  try {
    await loadCatalogs()
    const draft = typeof route.query.draft === 'string' ? route.query.draft : ''
    if (draft) await restoreDraft(draft)
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    loading.value = false
  }
})
</script>

<template>
  <div v-loading="loading">
    <div class="toolbar"><div><h2>{{ name || '新建匹配任务' }}</h2><p>选择数据 → 确认匹配规则 → 比对计算 → 人工处理 → 生成结果。</p></div></div>
    <el-steps :active="0"><el-step title="选择数据"/><el-step title="确认匹配规则"/><el-step title="比对计算"/><el-step title="人工处理"/><el-step title="生成结果"/></el-steps>
    <div class="panel">
      <h3>1. 选择数据</h3>
      <el-form label-width="130px">
        <el-form-item label="任务名称"><el-input v-model="name" :disabled="existingDraft" placeholder="任务名称" /></el-form-item>
        <el-form-item label="客户物料数据"><div class="inline-row"><el-upload :auto-upload="false" :show-file-list="false" :on-change="(file:any)=>upload('source',file)"><el-button>选择 Source Excel / CSV</el-button></el-upload><span class="muted">{{ source?.original_name || '尚未选择' }}</span></div></el-form-item>
        <el-form-item v-if="sourceColumns.length" label="客户物料编码列"><el-select v-model="sourceIdColumn" style="width:360px"><el-option v-for="column in sourceColumns" :key="column" :label="column" :value="column"/></el-select></el-form-item>
        <el-divider />
        <el-form-item label="集团码数据来源"><el-radio-group v-model="targetMode"><el-radio-button value="existing">选择已有目录</el-radio-button><el-radio-button value="upload">上传新 Target</el-radio-button></el-radio-group></el-form-item>
        <template v-if="targetMode==='existing'">
          <el-form-item label="集团码目录"><el-select v-model="catalogVersionId" filterable placeholder="选择 READY 目录版本" style="width:560px" @change="selectCatalog"><el-option v-for="item in readyCatalogs" :key="item.version_id" :value="item.version_id" :label="`${item.name}${item.active ? ' · 当前版本' : ''} · ${item.group_code_column} · ${item.version_id.slice(0,8)}`" /></el-select></el-form-item>
          <el-alert v-if="selectedCatalog" :title="`将冻结目录版本 ${selectedCatalog.version_id}；后续即使基础数据切换 active，本任务也不会漂移。`" type="info" :closable="false" />
          <el-empty v-else description="尚无 READY 集团码目录，可切换到“上传新 Target”创建首个目录" :image-size="72" />
        </template>
        <template v-else>
          <el-form-item label="集团码文件"><div class="inline-row"><el-upload :auto-upload="false" :show-file-list="false" :on-change="(file:any)=>upload('target',file)"><el-button>选择 Target Excel / CSV</el-button></el-upload><span class="muted">{{ target?.original_name || '尚未选择' }}</span></div></el-form-item>
          <el-form-item v-if="targetColumns.length" label="集团码列"><el-select v-model="groupCodeColumn" style="width:360px"><el-option v-for="column in targetColumns" :key="column" :label="column" :value="column"/></el-select></el-form-item>
          <el-alert title="继续后会创建一个新的集团码目录及首个不可变版本，并将该 version_id 冻结到任务草稿。" type="info" :closable="false" />
        </template>
      </el-form>
      <div class="actions"><el-button type="primary" :loading="busy" :disabled="!canContinue" @click="continueToRules">下一步：确认匹配规则</el-button></div>
    </div>
  </div>
</template>

<style scoped>
.inline-row{display:flex;align-items:center;gap:12px;flex-wrap:wrap}.muted{color:#7b8494;font-size:13px}.actions{display:flex;justify-content:flex-end;margin-top:20px}
</style>
