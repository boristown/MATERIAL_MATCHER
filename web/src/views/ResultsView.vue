<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { api } from '../api'
import '../styles/pages/results.css'

type TaskRow = {
  id: string
  name: string
  stage: string
  progress: number
  status: string
  created_at: string
  finished_at?: string | null
  result_file_id?: string | null
  processed_rows: number
  total_rows: number
}
type ResultSummary = { pending_review: number; confirmed: number; unmatched: number; automatic_matched: number }
type PreviewRow = {
  source_id?: string | null
  current_status?: string | null
  top1_group_code?: string | null
  top1_score?: number | null
  final_group_code?: string | null
  updated_at?: string | null
}
type FileRecord = { file_id: string; role: string; original_name: string; size_bytes?: number; created_at?: string }
type ExportInfo = { file_id: string; download_url: string }

const router = useRouter()
const tasks = ref<TaskRow[]>([])
const resultFiles = ref<Record<string, FileRecord>>({})
const latestSummary = ref<ResultSummary>({ pending_review: 0, confirmed: 0, unmatched: 0, automatic_matched: 0 })
const latestPreview = ref<PreviewRow[]>([])
const latestExport = ref<ExportInfo | null>(null)
const loading = ref(true)
const downloadingTaskId = ref('')

const stageLabels: Record<string, string> = { CALCULATE: '比对计算', REVIEW: '人工处理', RESULT: '生成结果' }
const RUNNING_STATUSES = ['RUNNING', 'PREPARING', 'RECOVERING', 'PENDING']

function resultCompletedAt(task: TaskRow): string {
  const file = task.result_file_id ? resultFiles.value[task.result_file_id] : undefined
  return String(file?.created_at || task.finished_at || task.created_at || '')
}

const generatedResults = computed(() => tasks.value
  .filter(task => Boolean(task.result_file_id))
  .slice()
  .sort((a, b) => resultCompletedAt(b).localeCompare(resultCompletedAt(a))))

const latestResult = computed(() => generatedResults.value[0] ?? null)

const pendingTask = computed(() => tasks.value
  .filter(task => !task.result_file_id && task.status !== 'FAILED')
  .slice()
  .sort((a, b) => b.created_at.localeCompare(a.created_at))[0] ?? null)

const waitingState = computed(() => {
  const task = pendingTask.value
  if (!task) return null
  if (RUNNING_STATUSES.includes(task.status)) {
    return {
      title: '正在等待 STEP2 计算完成',
      description: `任务「${task.name}」仍在计算中，结果文件尚未生成，当前不可下载。`,
      action: '查看计算进度',
      path: `/tasks/${task.id}`,
      showProgress: true,
    }
  }
  if (task.status === 'COMPLETED' && task.stage === 'REVIEW') {
    return {
      title: '正在等待 STEP3 人工处理完成',
      description: `任务「${task.name}」已完成计算，但仍处于人工处理阶段，完成确认后才能生成最终结果。`,
      action: '进入人工处理',
      path: `/tasks/${task.id}`,
      showProgress: false,
    }
  }
  if (task.status === 'COMPLETED' && task.stage === 'RESULT') {
    return {
      title: '前序步骤已完成，结果文件尚未生成',
      description: `任务「${task.name}」已经可以生成最终结果，请进入任务完成结果生成。`,
      action: '进入任务生成结果',
      path: `/tasks/${task.id}`,
      showProgress: false,
    }
  }
  return {
    title: '任务尚未形成可下载结果',
    description: `任务「${task.name}」当前状态为“${statusLabel(task.status)}”，请进入任务查看详情。`,
    action: '查看任务',
    path: `/tasks/${task.id}`,
    showProgress: false,
  }
})

function statusTagType(status: string): 'success' | 'danger' | 'warning' | 'primary' | 'info' {
  if (status === 'COMPLETED') return 'success'
  if (status === 'FAILED') return 'danger'
  if (RUNNING_STATUSES.includes(status)) return 'primary'
  return 'warning'
}
function statusLabel(status: string): string {
  return ({ RUNNING: '运行中', PREPARING: '准备中', RECOVERING: '恢复中', PENDING: '排队中', COMPLETED: '已完成', FAILED: '失败' } as Record<string, string>)[status] ?? status
}
function resultStatusLabel(row: PreviewRow): string {
  return ({ MATCHED: '自动匹配', CONFIRMED: '人工确认', REVIEW: '待人工确认', UNMATCHED: '未匹配' } as Record<string, string>)[String(row.current_status ?? '')] ?? String(row.current_status ?? '—')
}
function resultStatusType(row: PreviewRow): 'success' | 'warning' | 'info' | 'primary' {
  if (row.current_status === 'MATCHED') return 'success'
  if (row.current_status === 'CONFIRMED') return 'primary'
  if (row.current_status === 'REVIEW') return 'warning'
  return 'info'
}
function formatTime(value?: string | null): string {
  if (!value) return '—'
  return String(value).slice(0, 19).replace('T', ' ')
}
function formatScore(value?: number | null): string {
  if (value === null || value === undefined || Number.isNaN(Number(value))) return '—'
  return Number(value).toFixed(1)
}
function totalRows(task: TaskRow | null): number {
  const direct = Number(task?.total_rows ?? 0)
  if (direct > 0) return direct
  const summary = latestSummary.value
  return Number(summary.automatic_matched || 0) + Number(summary.confirmed || 0) + Number(summary.unmatched || 0) + Number(summary.pending_review || 0)
}
function openTask(task: TaskRow): void { router.push(`/tasks/${task.id}`) }
function evaluate(task: TaskRow): void { router.push(`/tasks/${task.id}/evaluation`) }

async function loadLatestDetails(task: TaskRow): Promise<void> {
  const [summaryResponse, previewResponse, exportResponse] = await Promise.all([
    api.get(`/tasks/${task.id}/workbench/summary`),
    api.get(`/tasks/${task.id}/live-results`, { params: { limit: 6 } }),
    api.get(`/tasks/${task.id}/exports`),
  ])
  latestSummary.value = summaryResponse.data ?? latestSummary.value
  latestPreview.value = previewResponse.data?.rows ?? []
  latestExport.value = exportResponse.data?.final_result ?? null
}

async function load(): Promise<void> {
  loading.value = true
  try {
    const [tasksResponse, filesResponse] = await Promise.all([api.get('/tasks'), api.get('/files')])
    const files = (filesResponse.data ?? []) as FileRecord[]
    resultFiles.value = Object.fromEntries(files.filter(file => file.role === 'result').map(file => [file.file_id, file]))
    tasks.value = ((tasksResponse.data ?? []) as any[]).map(task => ({
      id: String(task.task_id),
      name: String(task.name ?? task.task_id),
      stage: String(task.stage ?? ''),
      progress: Number(task.progress ?? 0),
      status: String(task.status ?? ''),
      created_at: String(task.created_at ?? ''),
      finished_at: task.finished_at ? String(task.finished_at) : null,
      result_file_id: task.result_file_id ? String(task.result_file_id) : null,
      processed_rows: Number(task.processed_rows ?? 0),
      total_rows: Number(task.total_rows ?? 0),
    }))
    latestSummary.value = { pending_review: 0, confirmed: 0, unmatched: 0, automatic_matched: 0 }
    latestPreview.value = []
    latestExport.value = null
    if (latestResult.value) await loadLatestDetails(latestResult.value)
  } catch {
    await router.push('/login')
  } finally {
    loading.value = false
  }
}

async function download(task: TaskRow): Promise<void> {
  downloadingTaskId.value = task.id
  try {
    const response = (await api.get(`/tasks/${task.id}/exports`)).data
    const exportInfo = response?.final_result as ExportInfo | null
    if (!exportInfo?.download_url) {
      ElMessage.warning('该任务尚未生成可下载的最终结果')
      await load()
      return
    }
    window.location.href = String(exportInfo.download_url)
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    downloadingTaskId.value = ''
  }
}

onMounted(load)
</script>

<template>
  <div class="results-page">
    <div class="toolbar results-toolbar">
      <div><h2>STEP 4 · 输出结果</h2><p>集中查看最终匹配结果、摘要预览与真实 Excel 导出。</p></div>
      <el-button @click="load">刷新结果</el-button>
    </div>

    <section class="result-workbench" v-loading="loading">
      <template v-if="latestResult">
        <div class="result-workbench-accent"></div>
        <div class="result-workbench-body">
          <div class="result-workbench-head">
            <div class="result-title-block">
              <div class="result-eyebrow"><span class="result-ready-dot"></span>最近一次已生成结果</div>
              <h3>{{ latestResult.name }}</h3>
              <div class="result-meta-line">
                <span>生成完成：{{ formatTime(resultCompletedAt(latestResult)) }}</span>
                <span>任务编号：{{ latestResult.id }}</span>
              </div>
            </div>
            <div class="result-main-actions">
              <el-button type="primary" plain @click="openTask(latestResult)">查看完整结果</el-button>
              <el-button type="primary" :loading="downloadingTaskId===latestResult.id" :disabled="!latestExport" @click="download(latestResult)">下载 Excel</el-button>
            </div>
          </div>

          <div class="result-metrics">
            <div class="result-metric primary"><span>总行数</span><b>{{ totalRows(latestResult) }}</b><small>最终结果记录</small></div>
            <div class="result-metric"><span>自动匹配</span><b>{{ latestSummary.automatic_matched ?? 0 }}</b><small>系统直接判定</small></div>
            <div class="result-metric"><span>人工确认</span><b>{{ latestSummary.confirmed ?? 0 }}</b><small>人工复核确认</small></div>
            <div class="result-metric"><span>未匹配</span><b>{{ latestSummary.unmatched ?? 0 }}</b><small>最终未形成集团码</small></div>
          </div>

          <div v-if="(latestSummary.pending_review ?? 0) > 0" class="result-note warning">
            该结果仍包含 {{ latestSummary.pending_review }} 条待人工确认记录；导出文件中这些记录会按现有后端规则保留处理状态。
          </div>

          <div class="result-preview">
            <div class="result-preview-head">
              <div><b>结果预览</b><span>最近 {{ latestPreview.length }} 条结果</span></div>
              <el-button link type="primary" @click="openTask(latestResult)">查看完整结果 →</el-button>
            </div>
            <el-table v-if="latestPreview.length" :data="latestPreview" size="small" class="result-preview-table">
              <el-table-column prop="source_id" label="源物料" min-width="170" show-overflow-tooltip/>
              <el-table-column label="结果状态" width="120"><template #default="scope"><el-tag size="small" :type="resultStatusType(scope.row)">{{ resultStatusLabel(scope.row) }}</el-tag></template></el-table-column>
              <el-table-column label="最终集团码" min-width="150"><template #default="scope"><b class="result-code">{{ scope.row.final_group_code || '—' }}</b></template></el-table-column>
              <el-table-column label="Top1 候选" min-width="150"><template #default="scope">{{ scope.row.top1_group_code || '—' }}</template></el-table-column>
              <el-table-column label="Top1 分数" width="105"><template #default="scope">{{ formatScore(scope.row.top1_score) }}</template></el-table-column>
            </el-table>
            <div v-else class="result-preview-empty">该结果暂无可预览记录，可直接查看完整结果或下载 Excel。</div>
          </div>
        </div>
      </template>

      <template v-else-if="!loading && waitingState && pendingTask">
        <div class="result-state-panel waiting">
          <div class="result-state-icon">…</div>
          <div class="result-state-content">
            <span class="result-state-kicker">结果尚不可下载</span>
            <h3>{{ waitingState.title }}</h3>
            <p>{{ waitingState.description }}</p>
            <div class="result-state-meta">
              <span>任务：{{ pendingTask.name }}</span>
              <span>阶段：{{ stageLabels[pendingTask.stage] ?? pendingTask.stage }}</span>
              <span>状态：{{ statusLabel(pendingTask.status) }}</span>
            </div>
            <el-progress v-if="waitingState.showProgress" :percentage="Math.round(pendingTask.progress)" :stroke-width="10" class="result-wait-progress"/>
            <div class="result-state-actions">
              <el-button type="primary" @click="router.push(waitingState.path)">{{ waitingState.action }}</el-button>
              <el-button @click="router.push('/tasks')">前往 STEP2</el-button>
            </div>
          </div>
        </div>
      </template>

      <template v-else-if="!loading">
        <div class="result-state-panel empty">
          <div class="result-state-icon">□</div>
          <div class="result-state-content">
            <span class="result-state-kicker">暂无输出结果</span>
            <h3>尚无任何已经生成完成的结果</h3>
            <p>当前没有可下载结果，也没有正在推进中的任务。请先创建任务并完成 STEP2 计算与必要的 STEP3 人工处理。</p>
            <div class="result-state-actions">
              <el-button type="primary" @click="router.push('/tasks/new')">新建匹配任务</el-button>
              <el-button @click="router.push('/tasks')">前往 STEP2</el-button>
            </div>
          </div>
        </div>
      </template>
    </section>

    <div class="panel results-history">
      <div class="section-head results-history-head">
        <div><h3>历史结果</h3><p>已生成过最终 Excel 的任务，可再次查看或下载。</p></div>
        <span class="results-history-count">{{ generatedResults.length }} 个结果</span>
      </div>
      <el-table :data="generatedResults" size="default" empty-text="暂无历史结果">
        <el-table-column label="任务" min-width="230"><template #default="scope"><a class="row-link" @click="openTask(scope.row)">{{ scope.row.name }}</a><div class="row-sub">{{ scope.row.id }}</div></template></el-table-column>
        <el-table-column label="完成时间" width="180"><template #default="scope">{{ formatTime(resultCompletedAt(scope.row)) }}</template></el-table-column>
        <el-table-column label="总行数" width="110"><template #default="scope">{{ scope.row.total_rows || '—' }}</template></el-table-column>
        <el-table-column label="状态" width="105"><template #default="scope"><el-tag size="small" :type="statusTagType(scope.row.status)">{{ statusLabel(scope.row.status) }}</el-tag></template></el-table-column>
        <el-table-column label="操作" min-width="210"><template #default="scope">
          <el-button link type="primary" @click="openTask(scope.row)">查看</el-button>
          <el-button link type="primary" :loading="downloadingTaskId===scope.row.id" @click="download(scope.row)">下载 Excel</el-button>
          <el-button link type="success" @click="evaluate(scope.row)">准确率验收</el-button>
        </template></el-table-column>
      </el-table>
    </div>
  </div>
</template>
