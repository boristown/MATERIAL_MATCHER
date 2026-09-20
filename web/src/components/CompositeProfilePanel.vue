<script setup lang="ts">
import { computed, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../api'
import {
  getPublishedProfileVersion,
  type ColumnInfo,
  type CompositeChildView,
  type FileRecord,
} from '../compositeProfile'

type ProfileRow = { profile_id: string; name: string; latest_published_version?: number | null }
type Inspection = { recommended_sheet?: string | null; sheets?: Array<{ sheet_name: string; columns?: ColumnInfo[] }> }

const props = defineProps<{
  profiles: ProfileRow[]
  children: CompositeChildView[]
  source: FileRecord | null
  sourceColumns: ColumnInfo[]
  sourceIdColumn: string
  editingProfileId?: string
}>()

const emit = defineEmits<{
  'update:children': [value: CompositeChildView[]]
  'source-parsed': [payload: { file: FileRecord; columns: ColumnInfo[]; inspection: Inspection }]
  'update:sourceIdColumn': [value: string]
}>()

const uploading = ref(false)
const selectedIds = computed({
  get: () => props.children.map(child => child.profile_id),
  set: value => void updateSelection(value),
})

function columnsFromInspection(inspection: Inspection): ColumnInfo[] {
  const sheet = inspection.sheets?.find(item => item.sheet_name === inspection.recommended_sheet) ?? inspection.sheets?.[0]
  return sheet?.columns ?? []
}

async function uploadSource(selected: any): Promise<void> {
  if (!selected?.raw) return
  uploading.value = true
  try {
    const form = new FormData()
    form.append('role', 'source')
    form.append('file', selected.raw)
    const response = (await api.post('/files/upload', form)).data
    const inspection = (response.inspection ?? {}) as Inspection
    const columns = columnsFromInspection(inspection)
    emit('source-parsed', { file: response.file as FileRecord, columns, inspection })
    ElMessage.success(`SAP 客户模板解析完成，共识别 ${columns.length} 个字段`)
  } catch (error) {
    ElMessage.error((error as Error).message || 'SAP 客户模板解析失败')
  } finally {
    uploading.value = false
  }
}

async function updateSelection(ids: string[]): Promise<void> {
  const next: CompositeChildView[] = []
  for (const profileId of ids) {
    const existing = props.children.find(child => child.profile_id === profileId)
    if (existing) {
      next.push(existing)
      continue
    }
    try {
      next.push(await getPublishedProfileVersion(profileId))
    } catch (error) {
      ElMessage.warning((error as Error).message)
    }
  }
  emit('update:children', next)
}

const candidates = computed(() =>
  props.profiles.filter(item =>
    item.profile_id !== props.editingProfileId
    && Number(item.latest_published_version ?? 0) > 0,
  ),
)
</script>

<template>
  <div class="composite-editor">
    <el-alert
      type="info"
      :closable="false"
      title="跨类目方案会使用所选子方案分别计算，并将候选结果统一排序。各子方案继续维护自己的字段映射、权重和归一化规则；这里不会合并文件结构。"
    />
    <div class="editor-grid">
      <section class="source-template-card">
        <div class="card-head">
          <div><b>SAP 客户模板</b><p>只识别 A007 自己的源文件字段，不需要集团模板。</p></div>
          <el-tag v-if="sourceColumns.length" type="success" size="small">已识别 {{ sourceColumns.length }} 字段</el-tag>
        </div>
        <el-upload
          drag
          :auto-upload="false"
          :show-file-list="false"
          :on-change="uploadSource"
          accept=".xlsx,.xlsm,.csv"
          :disabled="uploading"
        >
          <div class="upload-copy">
            <b>{{ source ? '重新上传 SAP 客户模板' : '上传 SAP 客户模板' }}</b>
            <span>仅用于识别字段，不作为任务数据保存。</span>
          </div>
        </el-upload>
        <label v-if="sourceColumns.length">
          <span>客户物料编码字段</span>
          <el-select
            :model-value="sourceIdColumn"
            filterable
            placeholder="请选择源数据唯一标识字段"
            @update:model-value="(value: unknown) => emit('update:sourceIdColumn', String(value ?? ''))"
          >
            <el-option v-for="column in sourceColumns" :key="column.header" :label="column.header" :value="column.header"/>
          </el-select>
        </label>
      </section>

      <section class="children-card">
        <div class="card-head">
          <div><b>子方案集合</b><p>只能选择已发布的普通方案；选择时冻结当前发布版本。</p></div>
          <el-tag :type="children.length >= 2 ? 'success' : 'warning'" size="small">{{ children.length }} 个</el-tag>
        </div>
        <el-select
          v-model="selectedIds"
          multiple
          filterable
          collapse-tags
          collapse-tags-tooltip
          placeholder="选择两个或更多已发布普通方案"
          style="width:100%"
        >
          <el-option
            v-for="item in candidates"
            :key="item.profile_id"
            :value="item.profile_id"
            :label="`${item.name} · v${item.latest_published_version}`"
          />
        </el-select>
        <el-table v-if="children.length" :data="children" size="small" class="child-table">
          <el-table-column prop="name" label="子方案" min-width="180"/>
          <el-table-column label="冻结版本" width="100"><template #default="scope"><el-tag size="small">v{{ scope.row.version_no }}</el-tag></template></el-table-column>
          <el-table-column label="目标模板字段" min-width="220"><template #default="scope">
            {{ scope.row.target_fields.length ? scope.row.target_fields.join('、') : '未保存模板 schema，任务时按子方案规则字段检查' }}
          </template></el-table-column>
        </el-table>
      </section>
    </div>
  </div>
</template>

<style scoped>
.composite-editor { display:flex; flex-direction:column; gap:16px; }
.editor-grid { display:grid; grid-template-columns:minmax(280px,.8fr) minmax(420px,1.2fr); gap:16px; }
.source-template-card,.children-card { border:1px solid var(--mm-line); border-radius:12px; padding:16px; background:#fbfcfe; min-width:0; }
.card-head { display:flex; justify-content:space-between; gap:12px; margin-bottom:12px; }
.card-head b { font-size:15px; }
.card-head p { margin:4px 0 0; color:var(--mm-muted); font-size:12px; line-height:1.5; }
.upload-copy { min-height:88px; display:flex; flex-direction:column; justify-content:center; gap:6px; }
.upload-copy span { color:var(--mm-muted); font-size:12px; }
.source-template-card label { display:grid; grid-template-columns:130px 1fr; gap:10px; align-items:center; margin-top:12px; font-size:12px; font-weight:600; }
.child-table { margin-top:12px; }
@media (max-width: 900px) { .editor-grid { grid-template-columns:1fr; } }
</style>
