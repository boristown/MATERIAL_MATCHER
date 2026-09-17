<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '../api'
import TaskWorkspaceBase from './TaskWorkspaceBase.vue'

type Counts = { matched: number; review: number; unmatched: number; confirmed: number }
type HistogramBucket = { min: number; max: number; count: number }
type CalibrationStats = {
  current: { revision_no: number; success_threshold: number; review_threshold: number; operator?: string | null; created_at?: string | null }
  counts: Counts
  top1_score_histogram: HistogramBucket[]
  top1_top2_gap_histogram: HistogramBucket[]
}
type Preview = {
  before: Counts
  after: Counts
  transitions: Record<string, number>
  affected_rows: number
  human_protected: number
}
type DecisionRevision = {
  revision_no: number
  success_threshold: number
  review_threshold: number
  operator: string
  created_at: string
  rollback_of_revision?: number | null
  before_counts: Counts
  after_counts: Counts
}
type ResultRevision = {
  revision_no: number
  decision_revision_no: number
  file_id: string
  created_at: string
}

const route = useRoute()
const taskId = computed(() => typeof route.params.taskId === 'string' ? route.params.taskId : '')
const baseKey = ref(0)
const stats = ref<CalibrationStats | null>(null)
const successThreshold = ref(78)
const reviewThreshold = ref(60)
const preview = ref<Preview | null>(null)
const revisions = ref<DecisionRevision[]>([])
const resultRevisions = ref<ResultRevision[]>([])
const batchRows = ref<any[]>([])
const loading = ref(false)
const previewBusy = ref(false)
const applyBusy = ref(false)
const batchBusy = ref(false)

const thresholdValid = computed(() => reviewThreshold.value >= 0 && reviewThreshold.value < successThreshold.value && successThreshold.value <= 100)
const transitionRows = computed(() => Object.entries(preview.value?.transitions ?? {})
  .filter(([, count]) => Number(count) > 0)
  .map(([transition, count]) => ({ transition, count })))

function formatTime(value?: string | null): string {
  if (!value) return '—'
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}

async function loadCalibration(resetInputs = true): Promise<void> {
  if (!taskId.value) return
  loading.value = true
  try {
    const [statsResponse, revisionsResponse, resultsResponse] = await Promise.all([
      api.get(`/tasks/${taskId.value}/calibration`),
      api.get(`/tasks/${taskId.value}/decision-revisions`),
      api.get(`/tasks/${taskId.value}/result-revisions`),
    ])
    stats.value = statsResponse.data
    revisions.value = revisionsResponse.data
    resultRevisions.value = resultsResponse.data
    if (resetInputs) {
      successThreshold.value = Number(stats.value?.current?.success_threshold ?? 78)
      reviewThreshold.value = Number(stats.value?.current?.review_threshold ?? 60)
      preview.value = null
    }
  } catch (error) {
    // Task creation/profile-edit routes do not have a completed task yet; leave the
    // normal workspace usable instead of turning calibration into a hard failure.
    stats.value = null
  } finally {
    loading.value = false
  }
}

async function previewThresholds(): Promise<void> {
  if (!taskId.value || !thresholdValid.value) return
  previewBusy.value = true
  try {
    preview.value = (await api.post(`/tasks/${taskId.value}/re-decide`, {
      success_threshold: successThreshold.value,
      review_threshold: reviewThreshold.value,
      mode: 'preview',
    })).data
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    previewBusy.value = false
  }
}

async function applyThresholds(): Promise<void> {
  if (!taskId.value || !thresholdValid.value) return
  if (!preview.value) await previewThresholds()
  if (!preview.value) return
  try {
    await ElMessageBox.confirm(
      `应用后自动匹配 ${preview.value.after.matched} 条、待人工 ${preview.value.after.review} 条、未匹配 ${preview.value.after.unmatched} 条；人工已确认数据不会被覆盖。`,
      '应用双阈值',
      { confirmButtonText: '确认应用', cancelButtonText: '取消', type: 'warning' },
    )
  } catch { return }
  applyBusy.value = true
  try {
    const response = (await api.post(`/tasks/${taskId.value}/re-decide`, {
      success_threshold: successThreshold.value,
      review_threshold: reviewThreshold.value,
      mode: 'apply',
    })).data
    ElMessage.success(`已形成判定版本 ${response.revision_no}`)
    await loadCalibration(true)
    baseKey.value += 1
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    applyBusy.value = false
  }
}

async function loadBatchPreview(): Promise<void> {
  if (!taskId.value) return
  batchBusy.value = true
  try {
    const scenarios = [95, 90, 85, 80, 75, 70, 65, 60].map(success => ({
      success_threshold: success,
      review_threshold: Math.max(0, success - 20),
    }))
    batchRows.value = (await api.post(`/tasks/${taskId.value}/calibration/batch-preview`, { scenarios })).data.scenarios ?? []
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    batchBusy.value = false
  }
}

async function rollback(revision: DecisionRevision): Promise<void> {
  if (!taskId.value) return
  try {
    await ElMessageBox.confirm(
      `恢复版本 ${revision.revision_no} 的阈值：自动匹配 ${revision.success_threshold}，人工处理下限 ${revision.review_threshold}。恢复操作会形成一个新的判定版本，不删除历史。`,
      '恢复阈值版本',
      { confirmButtonText: '恢复', cancelButtonText: '取消', type: 'warning' },
    )
  } catch { return }
  try {
    const response = (await api.post(`/tasks/${taskId.value}/decision-revisions/${revision.revision_no}/rollback`)).data
    ElMessage.success(`已恢复并形成判定版本 ${response.revision_no}`)
    await loadCalibration(true)
    baseKey.value += 1
  } catch (error) {
    ElMessage.error((error as Error).message)
  }
}

onMounted(() => void loadCalibration())
watch(taskId, () => void loadCalibration())
</script>

<template>
  <section v-if="taskId && stats" class="calibration-panel" v-loading="loading">
    <div class="calibration-title-row">
      <div>
        <div class="calibration-title">全局判定调参</div>
        <div class="calibration-subtitle">仅使用已落库候选与分数快速重判，不重新计算向量、候选召回或字段评分。没有金标时这里只展示数量影响，不给出“最佳阈值”推荐。</div>
      </div>
      <el-tag effect="plain">当前判定版本 {{ stats.current.revision_no }}</el-tag>
    </div>

    <div class="calibration-counts">
      <span>自动匹配 <b>{{ stats.counts.matched }}</b></span>
      <span>待人工 <b>{{ stats.counts.review }}</b></span>
      <span>未匹配 <b>{{ stats.counts.unmatched }}</b></span>
      <span>已人工匹配 <b>{{ stats.counts.confirmed }}</b></span>
    </div>

    <div class="threshold-row">
      <label>自动匹配阈值</label>
      <el-input-number v-model="successThreshold" :min="0" :max="100" :step="1" />
      <label>人工处理下限</label>
      <el-input-number v-model="reviewThreshold" :min="0" :max="100" :step="1" />
      <el-button :loading="previewBusy" :disabled="!thresholdValid" @click="previewThresholds">预览影响</el-button>
      <el-button type="primary" :loading="applyBusy" :disabled="!thresholdValid" @click="applyThresholds">应用并生成版本</el-button>
      <span v-if="!thresholdValid" class="invalid">需满足 0 ≤ 人工处理下限 &lt; 自动匹配阈值 ≤ 100</span>
    </div>

    <div v-if="preview" class="preview-grid">
      <div class="preview-card">
        <div class="preview-card-title">当前 → 新阈值</div>
        <div>自动匹配：{{ preview.before.matched }} → <b>{{ preview.after.matched }}</b></div>
        <div>待人工：{{ preview.before.review }} → <b>{{ preview.after.review }}</b></div>
        <div>未匹配：{{ preview.before.unmatched }} → <b>{{ preview.after.unmatched }}</b></div>
        <div>已人工匹配：{{ preview.before.confirmed }} → <b>{{ preview.after.confirmed }}</b></div>
        <div class="muted">影响 {{ preview.affected_rows }} 条；人工保护 {{ preview.human_protected }} 条</div>
      </div>
      <div class="preview-card">
        <div class="preview-card-title">状态变化</div>
        <div v-for="row in transitionRows" :key="row.transition" class="transition-row">
          <span>{{ row.transition.replace('->', ' → ') }}</span><b>{{ row.count }}</b>
        </div>
      </div>
    </div>

    <details class="calibration-details">
      <summary>查看分数分布、批量试算与历史版本</summary>
      <div class="histograms">
        <div>
          <h4>Top1 分数分布</h4>
          <div v-for="bucket in stats.top1_score_histogram" :key="bucket.min" class="hist-row">
            <span>{{ bucket.min }}-{{ bucket.max }}</span><b>{{ bucket.count }}</b>
          </div>
        </div>
        <div>
          <h4>Top1 / Top2 分差分布</h4>
          <div v-for="bucket in stats.top1_top2_gap_histogram" :key="bucket.min" class="hist-row">
            <span>{{ bucket.min }}-{{ bucket.max }}</span><b>{{ bucket.count }}</b>
          </div>
        </div>
      </div>

      <div class="batch-section">
        <div class="section-title-row">
          <h4>批量试算</h4>
          <el-button size="small" :loading="batchBusy" @click="loadBatchPreview">计算 95 → 60 示例组合</el-button>
        </div>
        <div class="muted">示例组合固定使用“人工处理下限 = 自动阈值 - 20”，仅用于观察数量变化，不代表准确率推荐。</div>
        <el-table v-if="batchRows.length" :data="batchRows" size="small" max-height="280">
          <el-table-column prop="success_threshold" label="自动阈值" width="90" />
          <el-table-column prop="review_threshold" label="人工下限" width="90" />
          <el-table-column label="自动匹配" width="100"><template #default="scope">{{ scope.row.after.matched }}</template></el-table-column>
          <el-table-column label="待人工" width="100"><template #default="scope">{{ scope.row.after.review }}</template></el-table-column>
          <el-table-column label="未匹配" width="100"><template #default="scope">{{ scope.row.after.unmatched }}</template></el-table-column>
          <el-table-column prop="affected_rows" label="变化条数" width="100" />
        </el-table>
      </div>

      <div class="revision-section">
        <h4>阈值历史</h4>
        <el-table :data="revisions" size="small" max-height="280" empty-text="尚未应用过新的阈值">
          <el-table-column prop="revision_no" label="版本" width="70" />
          <el-table-column prop="success_threshold" label="自动阈值" width="90" />
          <el-table-column prop="review_threshold" label="人工下限" width="90" />
          <el-table-column prop="operator" label="操作人" min-width="110" />
          <el-table-column label="时间" min-width="170"><template #default="scope">{{ formatTime(scope.row.created_at) }}</template></el-table-column>
          <el-table-column label="操作" width="90"><template #default="scope"><el-button link type="primary" @click="rollback(scope.row)">恢复</el-button></template></el-table-column>
        </el-table>
      </div>

      <div class="revision-section">
        <h4>正式结果版本</h4>
        <el-table :data="resultRevisions" size="small" max-height="220" empty-text="尚未生成正式结果">
          <el-table-column prop="revision_no" label="结果版本" width="90" />
          <el-table-column prop="decision_revision_no" label="判定版本" width="90" />
          <el-table-column label="生成时间" min-width="170"><template #default="scope">{{ formatTime(scope.row.created_at) }}</template></el-table-column>
          <el-table-column label="文件" width="100"><template #default="scope"><a :href="`/api/tasks/${taskId}/result-revisions/${scope.row.revision_no}`" target="_blank">下载</a></template></el-table-column>
        </el-table>
      </div>
    </details>
  </section>

  <TaskWorkspaceBase :key="baseKey" />
</template>

<style scoped>
.calibration-panel { margin: 16px 20px 0; padding: 16px 18px; border: 1px solid #d9e2ef; border-radius: 10px; background: #fff; box-shadow: 0 1px 4px rgba(15, 23, 42, .05); }
.calibration-title-row, .section-title-row { display: flex; align-items: center; justify-content: space-between; gap: 16px; }
.calibration-title { font-size: 17px; font-weight: 700; color: #1f2937; }
.calibration-subtitle, .muted { margin-top: 4px; color: #64748b; font-size: 12px; line-height: 1.6; }
.calibration-counts { display: flex; flex-wrap: wrap; gap: 18px; margin-top: 12px; padding: 9px 12px; background: #f8fafc; border-radius: 7px; color: #475569; }
.calibration-counts b { color: #0f172a; }
.threshold-row { display: flex; flex-wrap: wrap; align-items: center; gap: 10px; margin-top: 13px; }
.threshold-row label { color: #334155; font-weight: 600; }
.invalid { color: #dc2626; font-size: 12px; }
.preview-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 12px; margin-top: 12px; }
.preview-card { padding: 12px; border: 1px solid #e2e8f0; border-radius: 8px; line-height: 1.8; }
.preview-card-title { font-weight: 700; margin-bottom: 4px; }
.transition-row, .hist-row { display: flex; justify-content: space-between; gap: 16px; padding: 2px 0; }
.calibration-details { margin-top: 12px; border-top: 1px solid #eef2f7; padding-top: 10px; }
.calibration-details summary { cursor: pointer; color: #2563eb; font-weight: 600; }
.histograms { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 28px; margin-top: 14px; max-width: 720px; }
.histograms h4, .batch-section h4, .revision-section h4 { margin: 6px 0 8px; color: #334155; }
.hist-row { border-bottom: 1px dashed #edf2f7; color: #475569; }
.batch-section, .revision-section { margin-top: 18px; }
a { color: #2563eb; text-decoration: none; }
@media (max-width: 900px) { .preview-grid, .histograms { grid-template-columns: 1fr; } }
</style>
