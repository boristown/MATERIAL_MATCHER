<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../api'
import {
  recommendCompositeAssignments,
  targetCompatibility,
  type ColumnInfo,
  type CompositeAssignment,
  type CompositeChildView,
  type CompositeTargetInput,
  type FileRecord,
} from '../compositeProfile'

type Inspection = { recommended_sheet?: string | null; sheets?: Array<{ sheet_name: string; columns?: ColumnInfo[] }> }

const props = defineProps<{
  source: FileRecord | null
  sourceColumns: ColumnInfo[]
  sourceIdColumn: string
  children: CompositeChildView[]
  targetInputs: CompositeTargetInput[]
  assignments: Record<string, CompositeAssignment>
}>()

const emit = defineEmits<{
  'source-parsed': [payload: { file: FileRecord; columns: ColumnInfo[]; inspection: Inspection }]
  'update:sourceIdColumn': [value: string]
  'update:targetInputs': [value: CompositeTargetInput[]]
  'update:assignments': [value: Record<string, CompositeAssignment>]
}>()

const uploading = ref<'source' | 'target' | ''>('')
const sourceInspection = ref<Inspection | null>(null)

function columnsFromInspection(inspection: Inspection): ColumnInfo[] {
  const sheet = inspection.sheets?.find(item => item.sheet_name === inspection.recommended_sheet) ?? inspection.sheets?.[0]
  return sheet?.columns ?? []
}

async function upload(kind: 'source' | 'target', selected: any): Promise<void> {
  if (!selected?.raw) return
  uploading.value = kind
  try {
    const form = new FormData()
    form.append('role', kind)
    form.append('file', selected.raw)
    const response = (await api.post('/files/upload', form)).data
    const inspection = (response.inspection ?? {}) as Inspection
    const columns = columnsFromInspection(inspection)
    if (kind === 'source') {
      sourceInspection.value = inspection
      emit('source-parsed', { file: response.file as FileRecord, columns, inspection })
      ElMessage.success(`SAP 待匹配文件解析完成，共识别 ${columns.length} 个字段`)
    } else {
      const input: CompositeTargetInput = { file: response.file as FileRecord, columns, inspection }
      const nextInputs = [...props.targetInputs.filter(item => item.file.file_id !== input.file.file_id), input]
      emit('update:targetInputs', nextInputs)
      emit('update:assignments', recommendCompositeAssignments(props.children, nextInputs, props.assignments))
      ElMessage.success(`集团文件「${input.file.original_name}」解析完成，共识别 ${columns.length} 个字段`)
    }
  } catch (error) {
    ElMessage.error((error as Error).message || '文件上传解析失败')
  } finally {
    uploading.value = ''
  }
}

function removeTarget(fileId: string): void {
  const nextInputs = props.targetInputs.filter(item => item.file.file_id !== fileId)
  const nextAssignments: Record<string, CompositeAssignment> = {}
  for (const [profileId, assignment] of Object.entries(props.assignments)) {
    if (assignment.file_id !== fileId) nextAssignments[profileId] = assignment
  }
  emit('update:targetInputs', nextInputs)
  emit('update:assignments', recommendCompositeAssignments(props.children, nextInputs, nextAssignments))
}

function onFileChange(child: CompositeChildView, fileId: string): void {
  const input = props.targetInputs.find(item => item.file.file_id === fileId)
  if (!input) return
  const headers = new Set(input.columns.map(column => column.header))
  const groupCode = child.group_code_field && headers.has(child.group_code_field)
    ? child.group_code_field
    : input.columns.find(column => column.business_hint === 'group_code')?.header ?? ''
  emit('update:assignments', {
    ...props.assignments,
    [child.profile_id]: { file_id: fileId, group_code_column: groupCode },
  })
}

function onGroupCodeChange(child: CompositeChildView, value: string): void {
  const current = props.assignments[child.profile_id]
  if (!current) return
  emit('update:assignments', {
    ...props.assignments,
    [child.profile_id]: { ...current, group_code_column: value, catalog_version_id: undefined },
  })
}

function inputOf(child: CompositeChildView): CompositeTargetInput | undefined {
  const fileId = props.assignments[child.profile_id]?.file_id
  return props.targetInputs.find(item => item.file.file_id === fileId)
}

function coverageText(child: CompositeChildView): string {
  const input = inputOf(child)
  if (!input) return '未分配'
  const result = targetCompatibility(child, input)
  if (!result.total) return '无已保存 schema，请人工确认'
  return `${result.matched}/${result.total} · ${Math.round(result.ratio * 100)}%`
}

function coverageType(child: CompositeChildView): 'success' | 'warning' | 'danger' | 'info' {
  const input = inputOf(child)
  if (!input) return 'danger'
  const result = targetCompatibility(child, input)
  if (!result.total) return 'info'
  if (result.ratio >= 0.9) return 'success'
  if (result.ratio >= 0.6) return 'warning'
  return 'danger'
}

const allAssigned = computed(() => props.children.length >= 2 && props.children.every(child => {
  const assignment = props.assignments[child.profile_id]
  return Boolean(assignment?.file_id && assignment?.group_code_column)
}))

watch(
  () => [props.children.map(child => `${child.profile_id}@${child.version_no}`).join('|'), props.targetInputs.map(input => input.file.file_id).join('|')],
  () => emit('update:assignments', recommendCompositeAssignments(props.children, props.targetInputs, props.assignments)),
)
</script>

<template>
  <div class="composite-upload">
    <el-alert
      type="info"
      :closable="false"
      title="跨类目方案会让每个子方案使用自己的集团文件独立计算，再统一排序候选。多个集团文件可以拥有完全不同的字段结构，不会被合并成同一张表。"
    />

    <div class="upload-grid">
      <section class="upload-card">
        <div class="card-head"><div><b>SAP 待匹配文件</b><p>本次任务只有一个源文件。</p></div><el-tag v-if="source" type="success" size="small">已解析</el-tag></div>
        <el-upload drag :auto-upload="false" :show-file-list="false" :on-change="(file:any) => upload('source', file)" accept=".xlsx,.xlsm,.csv" :disabled="Boolean(uploading)">
          <div class="upload-copy"><b>{{ source ? '重新上传 SAP 待匹配文件' : '上传 SAP 待匹配文件' }}</b><span>上传后自动识别字段</span></div>
        </el-upload>
        <label v-if="sourceColumns.length">
          <span>客户物料编码字段</span>
          <el-select :model-value="sourceIdColumn" filterable @update:model-value="(value: unknown) => emit('update:sourceIdColumn', String(value ?? ''))">
            <el-option v-for="column in sourceColumns" :key="column.header" :label="column.header" :value="column.header"/>
          </el-select>
        </label>
      </section>

      <section class="upload-card target-card">
        <div class="card-head"><div><b>集团目标文件</b><p>可连续上传多份，字段结构无需一致。</p></div><el-tag size="small">{{ targetInputs.length }} 份</el-tag></div>
        <el-upload drag multiple :auto-upload="false" :show-file-list="false" :on-change="(file:any) => upload('target', file)" accept=".xlsx,.xlsm,.csv" :disabled="Boolean(uploading)">
          <div class="upload-copy"><b>上传一份或多份集团文件</b><span>每份文件独立解析字段；可继续追加上传</span></div>
        </el-upload>
        <div v-if="targetInputs.length" class="file-chips">
          <el-tag v-for="input in targetInputs" :key="input.file.file_id" closable @close="removeTarget(input.file.file_id)">
            {{ input.file.original_name }} · {{ input.columns.length }} 字段
          </el-tag>
        </div>
      </section>
    </div>

    <div class="mapping-head">
      <div><b>子方案与本次集团文件对应关系</b><p>系统按子方案 target template schema 与上传文件表头的字段覆盖率自动推荐；你可以手工覆盖。</p></div>
      <el-tag :type="allAssigned ? 'success' : 'warning'">{{ allAssigned ? '映射完整' : '仍需确认' }}</el-tag>
    </div>

    <el-table :data="children" size="small" border>
      <el-table-column prop="name" label="子方案" min-width="180"/>
      <el-table-column label="版本" width="85"><template #default="scope">v{{ scope.row.version_no }}</template></el-table-column>
      <el-table-column label="本次集团文件" min-width="240"><template #default="scope">
        <el-select
          :model-value="assignments[scope.row.profile_id]?.file_id ?? ''"
          filterable
          placeholder="选择对应文件"
          style="width:100%"
          @update:model-value="(value: unknown) => onFileChange(scope.row, String(value ?? ''))"
        >
          <el-option v-for="input in targetInputs" :key="input.file.file_id" :label="input.file.original_name" :value="input.file.file_id"/>
        </el-select>
      </template></el-table-column>
      <el-table-column label="字段兼容情况" min-width="150"><template #default="scope">
        <el-tag :type="coverageType(scope.row)" size="small">{{ coverageText(scope.row) }}</el-tag>
      </template></el-table-column>
      <el-table-column label="集团码字段" min-width="180"><template #default="scope">
        <el-select
          :model-value="assignments[scope.row.profile_id]?.group_code_column ?? ''"
          filterable
          placeholder="请选择"
          style="width:100%"
          :disabled="!inputOf(scope.row)"
          @update:model-value="(value: unknown) => onGroupCodeChange(scope.row, String(value ?? ''))"
        >
          <el-option v-for="column in (inputOf(scope.row)?.columns ?? [])" :key="column.header" :label="column.header" :value="column.header"/>
        </el-select>
      </template></el-table-column>
    </el-table>
  </div>
</template>

<style scoped>
.composite-upload { display:flex; flex-direction:column; gap:16px; }
.upload-grid { display:grid; grid-template-columns:minmax(0,.8fr) minmax(0,1.2fr); gap:16px; }
.upload-card { border:1px solid var(--mm-line); border-radius:12px; padding:16px; background:#fbfcfe; min-width:0; }
.card-head,.mapping-head { display:flex; justify-content:space-between; align-items:flex-start; gap:12px; margin-bottom:12px; }
.card-head b,.mapping-head b { font-size:15px; }
.card-head p,.mapping-head p { margin:4px 0 0; color:var(--mm-muted); font-size:12px; line-height:1.55; }
.upload-copy { min-height:88px; display:flex; flex-direction:column; justify-content:center; gap:6px; }
.upload-copy span { color:var(--mm-muted); font-size:12px; }
.upload-card label { display:grid; grid-template-columns:130px 1fr; align-items:center; gap:10px; margin-top:12px; font-size:12px; font-weight:600; }
.file-chips { display:flex; flex-wrap:wrap; gap:8px; margin-top:12px; }
.mapping-head { margin:2px 0 -4px; }
@media (max-width: 900px) { .upload-grid { grid-template-columns:1fr; } }
</style>
