<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api'
import '../styles/pages/review.css'

type ReviewSummary = {
  pending_review: number
  confirmed: number
  unmatched: number
  automatic_matched: number
}

type ReviewTask = {
  id: string
  name: string
  stage: string
  progress: number
  status: string
  created_at: string
  started_at?: string | null
  finished_at?: string | null
  result_file_id?: string | null
  error_code?: string | null
  error_message?: string | null
  summary?: ReviewSummary
  summaryError?: boolean
}

type ProgressState = {
  task_id: string
  stage: string
  status: string
  progress: number
  processed_rows: number
  total_rows: number
  current_phase?: string | null
}

const router = useRouter()
const reviewRows = ref<ReviewTask[]>([])
const readyTask = ref<ReviewTask | null>(null)
const calculatingTask = ref<ReviewTask | null>(null)
const calculatingProgress = ref<ProgressState | null>(null)
const latestFailed = ref<ReviewTask | null>(null)
const loadError = ref('')
const loading = ref(false)
const RUNNING_STATUSES = ['RUNNING', 'PREPARING', 'RECOVERING', 'PENDING']
let pollTimer: number | undefined
let progressRefreshing = false

const actionableTaskCount = computed(() => reviewRows.value.filter(row => Number(row.summary?.pending_review ?? 0) > 0 && !row.summaryError).length)
const hasUnknownReviewState = computed(() => reviewRows.value.some(row => row.summaryError))
const consoleMode = computed<'ready' | 'waiting' | 'empty' | 'error'>(() => {
  if (loadError.value) return 'error'
  if (readyTask.value) return 'ready'
  if (hasUnknownReviewState.value) return 'error'
  if (calculatingTask.value) return 'waiting'
  return 'empty'
})
const waitingPercent = computed(() => percent(calculatingProgress.value?.progress ?? calculatingTask.value?.progress ?? 0))
const waitingProcessed = computed(() => Number(calculatingProgress.value?.processed_rows ?? 0))
const waitingTotal = computed(() => Number(calculatingProgress.value?.total_rows ?? 0))

function normalizeTask(task: any): ReviewTask {
  return {
    id: String(task.task_id ?? ''),
    name: String(task.name ?? '未命名任务'),
    stage: String(task.stage ?? ''),
    progress: Number(task.progress ?? 0),
    status: String(task.status ?? ''),
    created_at: String(task.created_at ?? ''),
    started_at: task.started_at ? String(task.started_at) : null,
    finished_at: task.finished_at ? String(task.finished_at) : null,
    result_file_id: task.result_file_id ? String(task.result_file_id) : null,
    error_code: task.error_code ? String(task.error_code) : null,
    error_message: task.error_message ? String(task.error_message) : null,
  }
}

function percent(value: unknown): number {
  const number = Number(value)
  if (!Number.isFinite(number)) return 0
  return Math.max(0, Math.min(100, Math.round(number)))
}

function formatNumber(value: unknown): string {
  const number = Number(value ?? 0)
  return Number.isFinite(number) ? number.toLocaleString() : '0'
}

function formatDate(value: string | null | undefined): string {
  if (!value) return '—'
  return value.slice(0, 19).replace('T', ' ')
}

function phaseLabel(phase: string | null | undefined): string {
  return ({
    INDEX: '构建向量索引',
    RETRIEVE: '候选召回',
    RERANK: '逐条匹配评分',
    PERSIST: '结果持久化',
    DONE: '计算完成',
    WAITING: '等待调度',
    FAILED: '计算失败',
  } as Record<string, string>)[String(phase ?? '')] ?? '准备计算'
}

function statusTagType(status: string): 'success' | 'danger' | 'warning' | 'primary' | 'info' {
  if (status === 'COMPLETED') return 'success'
  if (status === 'FAILED') return 'danger'
  if (RUNNING_STATUSES.includes(status)) return 'primary'
  return 'warning'
}

function statusLabel(status: string): string {
  return ({
    RUNNING: '运行中',
    PREPARING: '准备中',
    RECOVERING: '恢复中',
    PENDING: '排队中',
    COMPLETED: '已完成',
    FAILED: '失败',
  } as Record<string, string>)[status] ?? status
}

function stopPolling(): void {
  if (pollTimer) window.clearInterval(pollTimer)
  pollTimer = undefined
}

function startPollingIfNeeded(): void {
  stopPolling()
  if (consoleMode.value === 'waiting' && calculatingTask.value) {
    pollTimer = window.setInterval(() => void refreshCalculatingProgress(), 3000)
  }
}

async function loadReviewSummary(task: ReviewTask): Promise<ReviewTask> {
  try {
    const summary = (await api.get(`/tasks/${task.id}/workbench/summary`)).data ?? {}
    return {
      ...task,
      summary: {
        pending_review: Number(summary.pending_review ?? 0),
        confirmed: Number(summary.confirmed ?? 0),
        unmatched: Number(summary.unmatched ?? 0),
        automatic_matched: Number(summary.automatic_matched ?? 0),
      },
      summaryError: false,
    }
  } catch {
    return { ...task, summaryError: true }
  }
}

async function refreshCalculatingProgress(): Promise<void> {
  const task = calculatingTask.value
  if (!task || progressRefreshing) return
  progressRefreshing = true
  try {
    const progress = (await api.get(`/tasks/${task.id}/progress`)).data as ProgressState
    calculatingProgress.value = progress
    task.progress = Number(progress.progress ?? task.progress)
    if (!RUNNING_STATUSES.includes(String(progress.status)) || String(progress.stage) !== 'CALCULATE') {
      await load()
    }
  } catch {
    // 瞬时进度读取失败时保留 /tasks 的最后已知状态，下一轮自动重试。
  } finally {
    progressRefreshing = false
  }
}

async function load(): Promise<void> {
  if (loading.value) return
  loading.value = true
  loadError.value = ''
  stopPolling()
  try {
    const tasks = ((await api.get('/tasks')).data ?? [])
      .map((task: any) => normalizeTask(task))
      .sort((a: ReviewTask, b: ReviewTask) => b.created_at.localeCompare(a.created_at))

    const reviewCandidates = tasks.filter((task: ReviewTask) => task.status === 'COMPLETED' && task.stage === 'REVIEW')
    reviewRows.value = await Promise.all(reviewCandidates.map((task: ReviewTask) => loadReviewSummary(task)))
    readyTask.value = reviewRows.value.find(task => !task.summaryError && Number(task.summary?.pending_review ?? 0) > 0 && !task.result_file_id) ?? null

    calculatingTask.value = tasks.find((task: ReviewTask) => task.stage === 'CALCULATE' && RUNNING_STATUSES.includes(task.status)) ?? null
    latestFailed.value = tasks.find((task: ReviewTask) => task.status === 'FAILED') ?? null
    calculatingProgress.value = null

    if (!readyTask.value && calculatingTask.value && !hasUnknownReviewState.value) {
      await refreshCalculatingProgress()
    }
  } catch (error) {
    reviewRows.value = []
    readyTask.value = null
    calculatingTask.value = null
    calculatingProgress.value = null
    latestFailed.value = null
    loadError.value = (error as Error).message || 'STEP3 状态读取失败'
  } finally {
    loading.value = false
    startPollingIfNeeded()
  }
}

function openReview(task: ReviewTask): void {
  if (Number(task.summary?.pending_review ?? 0) <= 0 || task.summaryError) return
  void router.push(`/tasks/${task.id}`)
}

function openTask(task: ReviewTask): void {
  void router.push(`/tasks/${task.id}`)
}

onMounted(() => void load())
onBeforeUnmount(stopPolling)
</script>

<template>
  <div class="review-page">
    <div class="toolbar">
      <div>
        <h2>STEP 3 · 人工调整</h2>
        <p>只展示真实可人工处理的数据；计算未完成时不会提前开放复核。</p>
      </div>
      <el-button :loading="loading" @click="load">刷新状态</el-button>
    </div>

    <section class="review-console" :class="`is-${consoleMode}`" aria-live="polite">
      <template v-if="consoleMode === 'ready' && readyTask">
        <div class="review-console-main">
          <div class="review-console-kicker"><span class="review-status-dot"></span>可进入人工处理</div>
          <h3>{{ readyTask.name }}</h3>
          <p>STEP2 计算已完成，当前存在需要人工确认的匹配结果。以下数量来自该任务的实时人工处理汇总。</p>
          <div class="review-console-meta">
            <span>任务编号 {{ readyTask.id.slice(0, 12) }}</span>
            <span>计算完成 {{ formatDate(readyTask.finished_at) }}</span>
            <span v-if="actionableTaskCount > 1">另有 {{ actionableTaskCount - 1 }} 个任务待处理</span>
          </div>
        </div>
        <div class="review-console-metrics">
          <div class="review-console-metric is-emphasis"><span>待人工确认</span><b>{{ formatNumber(readyTask.summary?.pending_review) }}</b><small>条</small></div>
          <div class="review-console-metric"><span>已人工确认</span><b>{{ formatNumber(readyTask.summary?.confirmed) }}</b><small>条</small></div>
          <div class="review-console-metric"><span>自动匹配</span><b>{{ formatNumber(readyTask.summary?.automatic_matched) }}</b><small>条</small></div>
        </div>
        <div class="review-console-action">
          <el-button type="primary" size="large" @click="openReview(readyTask)">进入人工调整 →</el-button>
          <small>进入后可逐条确认、候选对比与阈值重判</small>
        </div>
      </template>

      <template v-else-if="consoleMode === 'waiting' && calculatingTask">
        <div class="review-console-main">
          <div class="review-console-kicker"><span class="review-status-dot"></span>STEP2 计算进行中</div>
          <h3>正在等待 STEP2 计算完成</h3>
          <p>当前任务「{{ calculatingTask.name }}」仍在计算。中间结果不作为 STEP3 可复核数据，计算完成后这里会自动切换为人工处理状态。</p>
          <div class="review-console-meta">
            <span>{{ phaseLabel(calculatingProgress?.current_phase) }}</span>
            <span>{{ statusLabel(calculatingProgress?.status ?? calculatingTask.status) }}</span>
            <span v-if="waitingTotal > 0">已处理 {{ formatNumber(waitingProcessed) }} / {{ formatNumber(waitingTotal) }} 行</span>
          </div>
        </div>
        <div class="review-wait-progress">
          <div class="review-wait-percent"><b>{{ waitingPercent }}%</b><span>STEP2 计算进度</span></div>
          <el-progress :percentage="waitingPercent" :stroke-width="10" :show-text="false" />
        </div>
        <div class="review-console-action">
          <el-button type="primary" plain size="large" @click="openTask(calculatingTask)">查看 STEP2 计算进度</el-button>
          <small>当前不可进行人工复核</small>
        </div>
      </template>

      <template v-else-if="consoleMode === 'error'">
        <div class="review-console-main">
          <div class="review-console-kicker"><span class="review-status-dot"></span>状态读取异常</div>
          <h3>暂时无法确认是否存在可人工处理的数据</h3>
          <p>{{ loadError || '部分人工处理汇总读取失败，为避免误导，未将这些任务标记为“可人工处理”。请刷新后重试。' }}</p>
        </div>
        <div class="review-console-action">
          <el-button type="primary" :loading="loading" @click="load">重新读取</el-button>
          <el-button @click="router.push('/tasks')">前往 STEP2</el-button>
        </div>
      </template>

      <template v-else>
        <div class="review-console-main">
          <div class="review-console-kicker"><span class="review-status-dot"></span>暂无待处理数据</div>
          <h3>当前没有计算完成的数据，请先启动 STEP2 的数据计算</h3>
          <p>STEP3 只接收已经完成匹配计算且仍有待人工确认记录的任务。</p>
          <div v-if="latestFailed" class="review-failure-note">
            <b>最近失败任务：{{ latestFailed.name }}</b>
            <span>{{ latestFailed.error_message || latestFailed.error_code || '计算失败，未产生可进入 STEP3 的完成数据' }}</span>
            <el-button link type="danger" @click="openTask(latestFailed)">查看失败详情</el-button>
          </div>
        </div>
        <div class="review-console-action review-empty-actions">
          <el-button type="primary" size="large" @click="router.push('/tasks')">前往 STEP2</el-button>
          <el-button size="large" @click="router.push('/profiles')">前往 STEP1</el-button>
        </div>
      </template>
    </section>

    <div class="panel review-list-panel">
      <div class="section-head">
        <div>
          <h3>人工处理任务记录</h3>
          <p class="review-section-desc">仅列出真正进入过 REVIEW 阶段的已完成计算任务；“待确认”数量来自后端人工处理汇总。</p>
        </div>
      </div>

      <el-table v-if="reviewRows.length" :data="reviewRows" size="default">
        <el-table-column label="名称" min-width="220">
          <template #default="scope">
            <a class="row-link" @click="openTask(scope.row)">{{ scope.row.name }}</a>
            <div class="row-sub">{{ scope.row.id }}</div>
          </template>
        </el-table-column>
        <el-table-column label="计算状态" width="110">
          <template #default="scope"><el-tag size="small" :type="statusTagType(scope.row.status)">{{ statusLabel(scope.row.status) }}</el-tag></template>
        </el-table-column>
        <el-table-column label="人工处理" min-width="180">
          <template #default="scope">
            <template v-if="scope.row.summaryError">
              <el-tag size="small" type="danger">汇总读取失败</el-tag>
            </template>
            <template v-else-if="Number(scope.row.summary?.pending_review ?? 0) > 0">
              <el-tag size="small" type="warning">待确认 {{ formatNumber(scope.row.summary?.pending_review) }} 条</el-tag>
            </template>
            <template v-else>
              <el-tag size="small" type="success">待确认 0 条</el-tag>
              <span class="review-done-hint">人工队列已清空</span>
            </template>
          </template>
        </el-table-column>
        <el-table-column label="已人工确认" width="120">
          <template #default="scope">{{ scope.row.summaryError ? '—' : formatNumber(scope.row.summary?.confirmed) }}</template>
        </el-table-column>
        <el-table-column label="计算完成时间" width="170">
          <template #default="scope">{{ formatDate(scope.row.finished_at) }}</template>
        </el-table-column>
        <el-table-column label="操作" min-width="150">
          <template #default="scope">
            <el-button v-if="!scope.row.summaryError && Number(scope.row.summary?.pending_review ?? 0) > 0" link type="primary" @click="openReview(scope.row)">进入人工调整</el-button>
            <el-button v-else link :type="scope.row.summaryError ? 'danger' : 'info'" @click="scope.row.summaryError ? load() : openTask(scope.row)">{{ scope.row.summaryError ? '重新读取' : '查看已处理任务' }}</el-button>
          </template>
        </el-table-column>
      </el-table>

      <el-empty v-else description="暂无进入过人工处理阶段的任务" :image-size="72" />
    </div>
  </div>
</template>
