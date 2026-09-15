<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { api } from '../api'

type InspectionColumn = { header: string; business_hint?: string | null }
type TruthFile = { file_id: string; original_name: string }
type EvaluationMetrics = {
  truth_rows: number
  evaluated_rows: number
  truth_coverage: number
  top1_accuracy: number
  final_accuracy: number
  human_accuracy_gain: number
  automatic_rows: number
  automatic_accuracy: number
  review_rows: number
  review_rate: number
  unmatched_rows: number
  unmatched_rate: number
  resolved_rate: number
  candidate_recall_at: Record<string, number>
}
type EvaluationRun = {
  run_id: string
  task_id: string
  truth_file_id: string
  key_mode: string
  key_column: string
  expected_column: string
  metrics: EvaluationMetrics
  created_at: string
}
type EvaluationItem = {
  truth_key: string
  expected_group_code: string
  matched_task_row: number
  source_id?: string | null
  original_status?: string | null
  current_status?: string | null
  top1_group_code?: string | null
  final_group_code?: string | null
  top1_score?: number | null
  top1_correct: number
  final_correct: number
  expected_candidate_rank?: number | null
}

const route = useRoute()
const router = useRouter()
const taskId = computed(() => String(route.params.taskId || ''))
const task = ref<any>(null)
const truthFile = ref<TruthFile | null>(null)
const truthColumns = ref<string[]>([])
const keyColumn = ref('')
const expectedColumn = ref('')
const keyMode = ref<'source_id' | 'source_row_id'>('source_id')
const busy = ref(false)
const loading = ref(false)
const latest = ref<EvaluationRun | null>(null)
const history = ref<EvaluationRun[]>([])
const errors = ref<EvaluationItem[]>([])

function columnsFromInspection(inspection: any): InspectionColumn[] {
  return inspection.sheets.find((item: any) => item.sheet_name === inspection.recommended_sheet)?.columns ?? []
}
function percent(value: number | null | undefined): string {
  return value == null ? '-' : `${(Number(value) * 100).toFixed(1)}%`
}
function chooseColumns(columns: InspectionColumn[]): void {
  const headers = columns.map(column => column.header)
  truthColumns.value = headers
  keyColumn.value = columns.find(column => column.business_hint === 'source_id')?.header
    ?? headers.find(header => /物料.*号|编码|source/i.test(header))
    ?? headers[0]
    ?? ''
  expectedColumn.value = columns.find(column => column.business_hint === 'group_code')?.header
    ?? headers.find(header => header !== keyColumn.value && /集团码|group.*code/i.test(header))
    ?? headers.find(header => header !== keyColumn.value)
    ?? ''
}

async function loadEvaluation(runId: string): Promise<void> {
  const response = await api.get(`/evaluations/${runId}`, { params: { include_items: true, only_errors: true, limit: 500 } })
  latest.value = response.data
  errors.value = response.data.items ?? []
}

async function refresh(): Promise<void> {
  if (!taskId.value) return
  loading.value = true
  try {
    const [taskResponse, historyResponse] = await Promise.all([
      api.get(`/tasks/${taskId.value}`),
      api.get(`/tasks/${taskId.value}/evaluations`),
    ])
    task.value = taskResponse.data
    history.value = historyResponse.data ?? []
    if (history.value.length) await loadEvaluation(history.value[0].run_id)
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    loading.value = false
  }
}

async function uploadTruth(selected: any): Promise<void> {
  busy.value = true
  try {
    const form = new FormData()
    form.append('role', 'supplement')
    form.append('file', selected.raw)
    const response = (await api.post('/files/upload', form)).data
    truthFile.value = response.file
    chooseColumns(columnsFromInspection(response.inspection))
    ElMessage.success('标注表已上传，请确认验收字段。')
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    busy.value = false
  }
}

async function runEvaluation(): Promise<void> {
  if (!truthFile.value || !keyColumn.value || !expectedColumn.value || !taskId.value) return
  busy.value = true
  try {
    const response = await api.post(`/tasks/${taskId.value}/evaluations`, {
      truth_file_id: truthFile.value.file_id,
      key_column: keyColumn.value,
      expected_group_code_column: expectedColumn.value,
      key_mode: keyMode.value,
    })
    await loadEvaluation(response.data.run_id)
    history.value = (await api.get(`/tasks/${taskId.value}/evaluations`)).data ?? []
    ElMessage.success('准确率验收完成；验收只生成报告，不修改任务结果。')
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    busy.value = false
  }
}

onMounted(refresh)
</script>

<template>
  <div v-loading="loading">
    <div class="toolbar">
      <div>
        <h2>准确率验收</h2>
        <p>{{ task?.name || taskId }}｜用人工确认或历史正确集团码衡量任务结果，不修改原任务。</p>
      </div>
      <el-button @click="router.push(`/tasks/${taskId}`)">返回任务</el-button>
    </div>

    <div class="panel">
      <h3>1. 上传业务真值</h3>
      <el-alert title="标注表只用于验收。至少包含一个源记录标识列和一个正确集团码列；推荐使用客户物料编码作为验收键。" type="info" :closable="false" />
      <div class="actions">
        <el-upload :auto-upload="false" :show-file-list="false" :on-change="uploadTruth">
          <el-button :loading="busy">选择 Excel / CSV 标注表</el-button>
        </el-upload>
        <span v-if="truthFile">{{ truthFile.original_name }}</span>
      </div>
      <div v-if="truthColumns.length" class="threshold">
        <span>验收键模式</span>
        <el-select v-model="keyMode" style="width:180px">
          <el-option label="客户物料编码 source_id" value="source_id" />
          <el-option label="任务行号 source_row_id" value="source_row_id" />
        </el-select>
        <span>标注表验收键列</span>
        <el-select v-model="keyColumn" style="width:180px"><el-option v-for="column in truthColumns" :key="column" :label="column" :value="column" /></el-select>
        <span>正确集团码列</span>
        <el-select v-model="expectedColumn" style="width:180px"><el-option v-for="column in truthColumns" :key="column" :label="column" :value="column" /></el-select>
        <el-button type="primary" :loading="busy" :disabled="!truthFile||!keyColumn||!expectedColumn" @click="runEvaluation">运行验收</el-button>
      </div>
    </div>

    <div v-if="latest" class="panel">
      <div class="section-head"><h3>2. 最新验收结果</h3><span class="muted">{{ latest.created_at }}</span></div>
      <el-descriptions :column="4" border>
        <el-descriptions-item label="标注覆盖">{{ percent(latest.metrics.truth_coverage) }}（{{ latest.metrics.evaluated_rows }}/{{ latest.metrics.truth_rows }}）</el-descriptions-item>
        <el-descriptions-item label="原始 Top1 准确率">{{ percent(latest.metrics.top1_accuracy) }}</el-descriptions-item>
        <el-descriptions-item label="最终准确率">{{ percent(latest.metrics.final_accuracy) }}</el-descriptions-item>
        <el-descriptions-item label="人工处理增益">{{ percent(latest.metrics.human_accuracy_gain) }}</el-descriptions-item>
        <el-descriptions-item label="自动匹配准确率">{{ percent(latest.metrics.automatic_accuracy) }}（{{ latest.metrics.automatic_rows }} 条）</el-descriptions-item>
        <el-descriptions-item label="Review率">{{ percent(latest.metrics.review_rate) }}（{{ latest.metrics.review_rows }} 条）</el-descriptions-item>
        <el-descriptions-item label="未匹配率">{{ percent(latest.metrics.unmatched_rate) }}（{{ latest.metrics.unmatched_rows }} 条）</el-descriptions-item>
        <el-descriptions-item label="最终有结果率">{{ percent(latest.metrics.resolved_rate) }}</el-descriptions-item>
        <el-descriptions-item label="候选 Recall@1">{{ percent(latest.metrics.candidate_recall_at?.['1']) }}</el-descriptions-item>
        <el-descriptions-item label="候选 Recall@3">{{ percent(latest.metrics.candidate_recall_at?.['3']) }}</el-descriptions-item>
        <el-descriptions-item label="候选 Recall@5">{{ percent(latest.metrics.candidate_recall_at?.['5']) }}</el-descriptions-item>
        <el-descriptions-item label="候选 Recall@10">{{ percent(latest.metrics.candidate_recall_at?.['10']) }}</el-descriptions-item>
      </el-descriptions>
      <p class="muted">Top1 准确率衡量规则/模型原始选择；最终准确率包含人工确认结果；候选 Recall 衡量正确集团码是否进入候选列表。标注未覆盖任务结果时请先关注“标注覆盖”。</p>
    </div>

    <div v-if="latest" class="panel">
      <h3>3. 错例与未覆盖标注</h3>
      <el-table :data="errors" size="small" empty-text="本次验收没有错例" max-height="440">
        <el-table-column prop="truth_key" label="验收键" min-width="140" />
        <el-table-column prop="expected_group_code" label="正确集团码" min-width="130" />
        <el-table-column label="任务覆盖" width="90"><template #default="scope">{{ scope.row.matched_task_row ? '是' : '否' }}</template></el-table-column>
        <el-table-column prop="top1_group_code" label="Top1" min-width="110" />
        <el-table-column prop="final_group_code" label="最终集团码" min-width="130" />
        <el-table-column prop="expected_candidate_rank" label="正确候选排名" width="120" />
        <el-table-column prop="original_status" label="原判定" width="100" />
        <el-table-column prop="current_status" label="当前状态" width="110" />
      </el-table>
    </div>

    <div v-if="history.length" class="panel">
      <h3>历史验收</h3>
      <el-table :data="history" size="small">
        <el-table-column prop="created_at" label="时间" min-width="180" />
        <el-table-column label="覆盖率" width="110"><template #default="scope">{{ percent(scope.row.metrics.truth_coverage) }}</template></el-table-column>
        <el-table-column label="Top1准确率" width="120"><template #default="scope">{{ percent(scope.row.metrics.top1_accuracy) }}</template></el-table-column>
        <el-table-column label="最终准确率" width="120"><template #default="scope">{{ percent(scope.row.metrics.final_accuracy) }}</template></el-table-column>
        <el-table-column label="操作" width="100"><template #default="scope"><el-button link type="primary" @click="loadEvaluation(scope.row.run_id)">查看</el-button></template></el-table-column>
      </el-table>
    </div>
  </div>
</template>

<style scoped>
.section-head{display:flex;justify-content:space-between;align-items:center}
.panel .el-alert{margin-bottom:14px}
</style>
