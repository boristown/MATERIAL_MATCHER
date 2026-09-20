<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../api'

type FileRecord = { file_id: string; original_name: string; sha256?: string; role?: string }
type ColumnInfo = { header: string; business_hint?: string | null; samples?: string[] }
type SheetInspection = {
  sheet_name: string
  recommended_header_row?: number
  row_count_estimate?: number
  column_count?: number
  columns?: ColumnInfo[]
  warnings?: string[]
}
type Inspection = {
  recommended_sheet?: string | null
  sheets?: SheetInspection[]
  warnings?: string[]
}
type ParsedPayload = {
  kind: 'source' | 'target'
  file: FileRecord
  inspection: Inspection
  columns: ColumnInfo[]
}

const props = withDefaults(defineProps<{
  source: FileRecord | null
  target: FileRecord | null
  sourceColumns: ColumnInfo[]
  targetColumns: ColumnInfo[]
  sourceIdColumn: string
  groupCodeColumn: string
  targetFiles?: FileRecord[]
  mode?: 'data' | 'template'
}>(), {
  targetFiles: () => [],
  mode: 'data',
})

const isTemplateMode = computed(() => props.mode === 'template')
const selectedTargetFiles = computed(() => props.targetFiles.length ? props.targetFiles : (props.target ? [props.target] : []))

const emit = defineEmits<{
  parsed: [payload: ParsedPayload]
  'update:sourceIdColumn': [value: string]
  'update:groupCodeColumn': [value: string]
  'remove-target': [fileId: string]
}>()

const uploading = ref<'source' | 'target' | ''>('')
const sourceInspection = ref<Inspection | null>(null)
const targetInspection = ref<Inspection | null>(null)
const loadedInspectionIds = ref<Record<'source' | 'target', string>>({ source: '', target: '' })

function recommendedSheet(inspection: Inspection | null): SheetInspection | null {
  if (!inspection?.sheets?.length) return null
  return inspection.sheets.find(sheet => sheet.sheet_name === inspection.recommended_sheet) ?? inspection.sheets[0] ?? null
}

const sourceSheet = computed(() => recommendedSheet(sourceInspection.value))
const targetSheet = computed(() => recommendedSheet(targetInspection.value))

function columnsFromInspection(inspection: Inspection): ColumnInfo[] {
  return recommendedSheet(inspection)?.columns ?? []
}

function previewColumns(sheet: SheetInspection | null): ColumnInfo[] {
  return (sheet?.columns ?? []).slice(0, 5)
}

function previewValues(column: ColumnInfo): string {
  const values = (column.samples ?? []).filter(value => String(value ?? '').trim()).slice(0, 2)
  return values.length ? values.join(' / ') : '—'
}

function allWarnings(inspection: Inspection | null): string[] {
  const sheet = recommendedSheet(inspection)
  return [...(inspection?.warnings ?? []), ...(sheet?.warnings ?? [])].filter(Boolean)
}

async function loadInspection(kind: 'source' | 'target', file: FileRecord | null): Promise<void> {
  if (!file?.file_id || loadedInspectionIds.value[kind] === file.file_id) return
  try {
    const response = (await api.get(`/files/${file.file_id}/inspection`)).data
    if (kind === 'source') sourceInspection.value = response.inspection ?? null
    else targetInspection.value = response.inspection ?? null
    loadedInspectionIds.value[kind] = file.file_id
  } catch {
    // 文件仍由父工作区持有；预览加载失败不阻断草稿恢复或任务执行。
  }
}

watch(() => props.source?.file_id, () => void loadInspection('source', props.source), { immediate: true })
watch(() => props.target?.file_id, () => void loadInspection('target', props.target), { immediate: true })

async function upload(kind: 'source' | 'target', selected: any): Promise<void> {
  if (!selected?.raw) return
  uploading.value = kind
  try {
    const form = new FormData()
    form.append('role', kind)
    form.append('file', selected.raw)
    const response = (await api.post('/files/upload', form)).data
    const inspection = (response.inspection ?? {}) as Inspection
    const payload: ParsedPayload = {
      kind,
      file: response.file as FileRecord,
      inspection,
      columns: columnsFromInspection(inspection),
    }
    if (kind === 'source') {
      sourceInspection.value = inspection
      loadedInspectionIds.value.source = payload.file.file_id
    } else {
      targetInspection.value = inspection
      loadedInspectionIds.value.target = payload.file.file_id
    }
    emit('parsed', payload)
    const label = isTemplateMode.value
      ? (kind === 'source' ? '客户物料模板' : '集团码模板')
      : (kind === 'source' ? '待匹配数据' : '集团码标准数据')
    ElMessage.success(`${label}解析完成，共识别 ${payload.columns.length} 个字段`)
  } catch (error) {
    ElMessage.error((error as Error).message || '文件上传解析失败')
  } finally {
    uploading.value = ''
  }
}
</script>

<template>
  <div class="dual-excel-grid">
    <section class="excel-upload-card source-card">
      <div class="excel-card-head">
        <div>
          <span class="side-badge">左侧</span>
          <h4>{{ isTemplateMode ? '客户物料模板' : '待匹配数据' }}</h4>
          <p>{{ isTemplateMode ? '上传客户侧 Excel 模板，系统自动识别字段' : '上传需要补充集团码的源 Excel' }}</p>
        </div>
        <el-tag v-if="source" type="success" size="small">已解析</el-tag>
      </div>
      <el-upload
        drag
        :auto-upload="false"
        :show-file-list="false"
        :on-change="(file:any) => upload('source', file)"
        accept=".xlsx,.xlsm,.csv"
        :disabled="Boolean(uploading)"
      >
        <div class="drop-content">
          <span class="upload-icon">⬆</span>
          <b>{{ source ? (isTemplateMode ? '重新上传客户物料模板' : '重新上传待匹配 Excel') : (isTemplateMode ? '拖入客户物料模板' : '拖入待匹配 Excel') }}</b>
          <small>{{ isTemplateMode ? '只需保留真实表头即可；上传后自动识别工作表、表头和字段' : '支持 .xlsx / .xlsm / .csv，上传后自动识别工作表、表头和字段' }}</small>
        </div>
      </el-upload>
      <div v-if="source" class="parsed-block">
        <div class="file-name" :title="source.original_name">{{ source.original_name }}</div>
        <div class="inspection-metrics">
          <span><em>工作表</em><b>{{ sourceSheet?.sheet_name ?? '—' }}</b></span>
          <span><em>表头</em><b>第 {{ sourceSheet?.recommended_header_row ?? '—' }} 行</b></span>
          <span><em>字段</em><b>{{ sourceSheet?.column_count ?? sourceColumns.length }}</b></span>
          <span><em>数据</em><b>{{ Number(sourceSheet?.row_count_estimate ?? 0).toLocaleString() }} 行</b></span>
        </div>
        <label class="column-picker">
          <span>
            {{ isTemplateMode ? '客户物料编码字段' : '客户物料编码列' }}
            <small v-if="isTemplateMode">用于唯一识别每条客户物料。系统会自动识别；未识别时只需在这里确认一次。</small>
          </span>
          <el-select
            :model-value="sourceIdColumn"
            filterable
            placeholder="系统未识别，请选择"
            @update:model-value="(value: unknown) => emit('update:sourceIdColumn', String(value ?? ''))"
          >
            <el-option v-for="column in sourceColumns" :key="column.header" :label="column.header" :value="column.header"/>
          </el-select>
        </label>
        <div v-if="previewColumns(sourceSheet).length" class="sample-preview">
          <div class="sample-title">示例数据</div>
          <div class="sample-grid">
            <div v-for="column in previewColumns(sourceSheet)" :key="column.header" class="sample-cell">
              <b>{{ column.header }}</b><span>{{ previewValues(column) }}</span>
            </div>
          </div>
        </div>
        <el-alert v-if="allWarnings(sourceInspection).length" type="warning" :closable="false" show-icon>
          <template #title>{{ allWarnings(sourceInspection)[0] }}</template>
        </el-alert>
      </div>
    </section>

    <div class="match-arrow" aria-hidden="true"><span>→</span><small>匹配</small></div>

    <section class="excel-upload-card target-card">
      <div class="excel-card-head">
        <div>
          <span class="side-badge">右侧</span>
          <h4>{{ isTemplateMode ? '集团码模板' : '集团码标准数据' }}</h4>
          <p>{{ isTemplateMode ? '上传集团码侧 Excel 模板，系统自动识别字段' : '可上传一个或多个集团码 Excel；多个文件会合并为同一候选池参与匹配' }}</p>
        </div>
        <el-tag v-if="selectedTargetFiles.length" type="success" size="small">{{ selectedTargetFiles.length > 1 ? `已选择 ${selectedTargetFiles.length} 个文件` : '已解析' }}</el-tag>
      </div>
      <el-upload
        drag
        :auto-upload="false"
        :show-file-list="false"
        :on-change="(file:any) => upload('target', file)"
        multiple
        accept=".xlsx,.xlsm,.csv"
        :disabled="Boolean(uploading)"
      >
        <div class="drop-content">
          <span class="upload-icon">⬆</span>
          <b>{{ selectedTargetFiles.length ? (isTemplateMode ? '继续添加 / 更换集团码模板' : '继续添加集团码 Excel') : (isTemplateMode ? '拖入集团码模板' : '拖入一个或多个集团码标准 Excel') }}</b>
          <small>{{ isTemplateMode ? '只需保留真实表头即可；上传后系统会自动识别可映射字段' : '普通方案上传 1 个文件；A007 等跨类目方案可同时选择多个文件，系统统一参与候选匹配' }}</small>
        </div>
      </el-upload>
      <div v-if="target" class="parsed-block">
        <div v-if="selectedTargetFiles.length > 1" class="target-file-list">
          <el-tag
            v-for="file in selectedTargetFiles"
            :key="file.file_id"
            closable
            effect="plain"
            @close="emit('remove-target', file.file_id)"
          >{{ file.original_name }}</el-tag>
        </div>
        <div v-else class="file-name" :title="selectedTargetFiles[0]?.original_name ?? target.original_name">{{ selectedTargetFiles[0]?.original_name ?? target.original_name }}</div>
        <div class="inspection-metrics">
          <span><em>工作表</em><b>{{ targetSheet?.sheet_name ?? '—' }}</b></span>
          <span><em>表头</em><b>第 {{ targetSheet?.recommended_header_row ?? '—' }} 行</b></span>
          <span><em>字段</em><b>{{ targetSheet?.column_count ?? targetColumns.length }}</b></span>
          <span><em>数据</em><b>{{ Number(targetSheet?.row_count_estimate ?? 0).toLocaleString() }} 行</b></span>
        </div>
        <label class="column-picker">
          <span>
            {{ isTemplateMode ? '集团码字段' : '集团码列' }}
            <small v-if="isTemplateMode">最终返回给客户的集团码所在列。系统会自动识别；未识别时只需在这里确认一次。</small>
          </span>
          <el-select
            :model-value="groupCodeColumn"
            filterable
            placeholder="系统未识别，请选择"
            @update:model-value="(value: unknown) => emit('update:groupCodeColumn', String(value ?? ''))"
          >
            <el-option v-for="column in targetColumns" :key="column.header" :label="column.header" :value="column.header"/>
          </el-select>
        </label>
        <div v-if="previewColumns(targetSheet).length" class="sample-preview">
          <div class="sample-title">示例数据</div>
          <div class="sample-grid">
            <div v-for="column in previewColumns(targetSheet)" :key="column.header" class="sample-cell">
              <b>{{ column.header }}</b><span>{{ previewValues(column) }}</span>
            </div>
          </div>
        </div>
        <el-alert v-if="allWarnings(targetInspection).length" type="warning" :closable="false" show-icon>
          <template #title>{{ allWarnings(targetInspection)[0] }}</template>
        </el-alert>
      </div>
    </section>
  </div>
</template>

<style scoped>
.dual-excel-grid {
  display: grid;
  grid-template-columns: minmax(0, 1fr) 58px minmax(0, 1fr);
  align-items: stretch;
  gap: 12px;
}
.excel-upload-card {
  min-width: 0;
  padding: 18px;
  border: 1px solid #dbe4ef;
  border-radius: 14px;
  background: linear-gradient(180deg, #ffffff 0%, #f8fafc 100%);
}
.excel-card-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  min-height: 74px;
}
.excel-card-head h4 {
  margin: 6px 0 3px;
  font-size: 17px;
  color: #172033;
}
.excel-card-head p {
  margin: 0;
  color: #64748b;
  font-size: 12px;
}
.side-badge {
  display: inline-flex;
  padding: 2px 8px;
  border-radius: 999px;
  background: #eef4ff;
  color: #315ec7;
  font-size: 11px;
  font-weight: 700;
}
.target-card .side-badge {
  background: #ecfdf3;
  color: #238050;
}
.drop-content {
  min-height: 126px;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 7px;
}
.drop-content .upload-icon {
  font-size: 27px;
  line-height: 1;
}
.drop-content b {
  font-size: 14px;
}
.drop-content small {
  max-width: 360px;
  color: #7b879a;
  line-height: 1.55;
}
.parsed-block {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding-top: 14px;
}
.target-file-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.target-file-list :deep(.el-tag) {
  max-width: 100%;
}
.file-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-weight: 700;
  color: #24324a;
}
.inspection-metrics {
  display: grid;
  grid-template-columns: repeat(4, minmax(0, 1fr));
  gap: 7px;
}
.inspection-metrics span {
  min-width: 0;
  padding: 8px 9px;
  border: 1px solid #e5eaf1;
  border-radius: 9px;
  background: #fff;
}
.inspection-metrics em,
.inspection-metrics b {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-style: normal;
}
.inspection-metrics em {
  color: #8490a3;
  font-size: 10.5px;
}
.inspection-metrics b {
  margin-top: 2px;
  color: #334155;
  font-size: 12px;
}
.column-picker {
  display: grid;
  grid-template-columns: 150px minmax(0, 1fr);
  align-items: center;
  gap: 10px;
  font-size: 12px;
  font-weight: 600;
  color: #475569;
}
.column-picker > span small {
  display: block;
  margin-top: 3px;
  color: #8a94a6;
  font-size: 10px;
  font-weight: 400;
  line-height: 1.4;
}
.sample-preview {
  padding: 10px;
  border: 1px solid #e6ebf2;
  border-radius: 10px;
  background: #fff;
}
.sample-title {
  margin-bottom: 7px;
  color: #64748b;
  font-size: 11px;
  font-weight: 700;
}
.sample-grid {
  display: grid;
  grid-template-columns: repeat(5, minmax(0, 1fr));
  gap: 6px;
}
.sample-cell {
  min-width: 0;
  padding: 7px;
  border-radius: 7px;
  background: #f6f8fb;
}
.sample-cell b,
.sample-cell span {
  display: block;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.sample-cell b {
  color: #334155;
  font-size: 10.5px;
}
.sample-cell span {
  margin-top: 3px;
  color: #7b879a;
  font-size: 10px;
}
.match-arrow {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  color: #4972ce;
}
.match-arrow span {
  display: grid;
  width: 38px;
  height: 38px;
  place-items: center;
  border-radius: 50%;
  background: #eef4ff;
  font-size: 24px;
}
.match-arrow small {
  margin-top: 5px;
  font-size: 10px;
  font-weight: 700;
}
@media (max-width: 1000px) {
  .dual-excel-grid {
    grid-template-columns: 1fr;
  }
  .match-arrow {
    min-height: 34px;
    transform: rotate(90deg);
  }
  .inspection-metrics {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
  .sample-grid {
    grid-template-columns: repeat(2, minmax(0, 1fr));
  }
}
</style>
