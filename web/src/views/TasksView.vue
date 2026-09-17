<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api'

type Row = { id: string; schemeName: string; runNumber: number | null; startedAt: string | null; stage: string; progress: number; status: string; created_at: string; kind: 'task' | 'draft' }
const router = useRouter()
const rows = ref<Row[]>([])
const stageLabels: Record<string, string> = { CALCULATE: '比对计算', REVIEW: '人工处理', RESULT: '生成结果' }
const RUNNING_STATUSES = ['RUNNING', 'PREPARING', 'RECOVERING', 'PENDING']

/* ---- 顶部运行态大屏 ---- */
const running = ref<Row | null>(null)
const live = ref<any>(null)
let liveTimer: number | undefined

const phaseLabel = computed(() => ({ INDEX: '构建向量索引', RETRIEVE: '候选召回', RERANK: '逐条匹配评分', PERSIST: '结果持久化', DONE: '已完成', WAITING: '等待调度', FAILED: '失败', RECOVERING: '重启恢复中' }[String(live.value?.current_phase ?? '')] ?? '准备中'))
const heroPercent = computed(() => Math.round(Number(live.value?.progress ?? running.value?.progress ?? 0)))
const heroStatus = computed(() => String(live.value?.status ?? running.value?.status ?? ''))

function fmtDuration(seconds: number | null | undefined): string {
  if (seconds == null || !Number.isFinite(Number(seconds)) || Number(seconds) < 0) return '估算中'
  const total = Math.round(Number(seconds))
  if (total < 60) return `${total} 秒`
  if (total < 3600) return `${Math.floor(total / 60)} 分 ${total % 60} 秒`
  return `${Math.floor(total / 3600)} 小时 ${Math.floor((total % 3600) / 60)} 分`
}
function fmtClock(iso: string | null | undefined): string {
  if (!iso) return '—'
  const date = new Date(iso)
  return Number.isNaN(date.getTime()) ? '—' : `${String(date.getHours()).padStart(2, '0')}:${String(date.getMinutes()).padStart(2, '0')}`
}
function statusTagType(status: string): 'success' | 'danger' | 'warning' | 'primary' | 'info' {
  if (status === 'COMPLETED') return 'success'
  if (status === 'FAILED') return 'danger'
  if (RUNNING_STATUSES.includes(status)) return 'primary'
  if (status === '草稿') return 'info'
  return 'warning'
}
function statusLabel(status: string): string {
  return ({ RUNNING: '运行中', PREPARING: '准备中', RECOVERING: '恢复中', PENDING: '排队中', COMPLETED: '已完成', FAILED: '失败' } as Record<string, string>)[status] ?? status
}

async function refreshLive(): Promise<void> {
  if (!running.value) return
  try { live.value = (await api.get(`/tasks/${running.value.id}/progress`)).data } catch { /* 忽略瞬时错误 */ }
}
async function load(): Promise<void> {
  try {
    const [tasks, drafts, profiles] = await Promise.all([api.get('/tasks'), api.get('/task-drafts'), api.get('/profiles')])
    const profileNames = new Map<string, string>((profiles.data ?? []).map((profile: any) => [String(profile.profile_id), String(profile.name || '未命名方案')]))
    rows.value = [
      ...tasks.data.map((task: any) => ({ id: task.task_id, schemeName: String(task.scheme_name || '未命名方案'), runNumber: Number(task.run_number ?? 1), startedAt: task.started_at ?? null, stage: stageLabels[task.stage] ?? task.stage, progress: task.progress, status: task.status, created_at: task.created_at, kind: 'task' as const })),
      ...drafts.data.map((draft: any) => ({ id: draft.draft_id, schemeName: profileNames.get(String(draft.template_profile_id || '')) || '未命名方案', runNumber: null, startedAt: null, stage: draft.current_step === 1 ? '选择数据' : '确认匹配规则', progress: 0, status: '草稿', created_at: draft.updated_at, kind: 'draft' as const })),
    ].sort((a, b) => b.created_at.localeCompare(a.created_at))
  } catch { await router.push('/login'); return }
  const runningRow = rows.value.find(row => row.kind === 'task' && RUNNING_STATUSES.includes(row.status)) ?? null
  running.value = runningRow
  if (runningRow) {
    await refreshLive()
    if (!liveTimer) liveTimer = window.setInterval(() => void refreshLive(), 3000)
  } else if (liveTimer) {
    window.clearInterval(liveTimer); liveTimer = undefined; live.value = null
  }
}
function open(row: Row): void { row.kind === 'draft' ? router.push({ path: '/tasks/new', query: { draft: row.id } }) : router.push(`/tasks/${row.id}`) }
function evaluate(row: Row): void { if (row.kind === 'task') router.push(`/tasks/${row.id}/evaluation`) }
onMounted(load)
onBeforeUnmount(() => { if (liveTimer) window.clearInterval(liveTimer) })
</script>

<template>
  <div class="tasks-page">
    <div class="toolbar">
      <div><h2>STEP 2 · 匹配计算</h2><p>正在进行的方案实时呈现；历史运行与草稿在下方列表。</p></div>
      <el-button type="primary" @click="router.push('/profiles')">配置匹配方案</el-button>
    </div>

    <div v-if="running" class="hero" @click="open(running)">
      <div class="hero-ring">
        <el-progress type="circle" :width="132" :percentage="heroPercent" :stroke-width="10">
          <template #default><div class="hero-ring-inner"><b>{{ heroPercent }}%</b><span>{{ statusLabel(heroStatus) }}</span></div></template>
        </el-progress>
      </div>
      <div class="hero-main">
        <div class="hero-title"><b>{{ running.schemeName }}</b><el-tag size="small" effect="dark" type="primary">{{ phaseLabel }}</el-tag><span class="hero-enter">点击进入实时看板 →</span></div>
        <div class="hero-grid">
          <div class="hero-cell"><span>已处理</span><b>{{ (live?.processed_rows ?? 0).toLocaleString() }} / {{ (live?.total_rows || '—') }}</b></div>
          <div class="hero-cell"><span>已匹配集团码</span><b class="good">{{ Number(live?.live_counts?.matched_group_codes ?? 0).toLocaleString() }}</b></div>
          <div class="hero-cell"><span>待人工确认</span><b>{{ Number(live?.live_counts?.review ?? 0).toLocaleString() }}</b></div>
          <div class="hero-cell"><span>吞吐</span><b>{{ live?.estimate?.rows_per_minute ? Number(live.estimate.rows_per_minute).toFixed(0) + ' 行/分' : '—' }}</b></div>
          <div class="hero-cell"><span>预计剩余</span><b>{{ live?.current_phase === 'INDEX' ? fmtDuration(live?.estimate?.phase_remaining_seconds) : fmtDuration(live?.estimate?.eta_seconds) }}</b></div>
          <div class="hero-cell"><span>预计完成</span><b>{{ fmtClock(live?.estimate?.eta_at) }}</b></div>
        </div>
      </div>
    </div>
    <div v-else class="hero idle">
      <div class="idle-icon">◎</div>
      <div class="idle-text">
        <b>无正在进行的方案</b>
        <p>请通过 STEP 1 选择方案、拖入数据并配置字段映射后开始匹配；运行中的进度、中间结果与预计完成时间会实时显示在这里。</p>
      </div>
      <el-button type="primary" size="large" @click="router.push('/profiles')">前往 STEP 1 配置并启动 →</el-button>
    </div>

    <div class="panel">
      <div class="section-head"><h3 style="margin:0">历史运行与草稿</h3></div>
      <el-table :data="rows" size="default">
        <el-table-column label="方案名称" min-width="240"><template #default="scope"><a class="row-link" @click="open(scope.row)">{{ scope.row.schemeName }}</a><div v-if="scope.row.kind === 'task'" class="row-sub">第 {{ scope.row.runNumber }} 次计算 · 开始 {{ String(scope.row.startedAt ?? scope.row.created_at).slice(0, 16).replace('T', ' ') }}</div></template></el-table-column>
        <el-table-column prop="stage" label="阶段" width="120"/>
        <el-table-column label="进度" width="170"><template #default="scope"><el-progress :percentage="Math.round(Number(scope.row.progress ?? 0))" :stroke-width="8" :status="scope.row.status==='FAILED'?'exception':scope.row.status==='COMPLETED'?'success':undefined"/></template></el-table-column>
        <el-table-column label="状态" width="100"><template #default="scope"><el-tag size="small" :type="statusTagType(scope.row.status)">{{ statusLabel(scope.row.status) }}</el-tag></template></el-table-column>
        <el-table-column label="更新时间" width="170"><template #default="scope">{{ String(scope.row.created_at).slice(0, 19).replace('T', ' ') }}</template></el-table-column>
        <el-table-column label="操作" min-width="170"><template #default="scope">
          <el-button link type="primary" @click="open(scope.row)">{{ scope.row.status === 'COMPLETED' ? '查看' : '继续' }}</el-button>
          <el-button v-if="scope.row.kind==='task' && scope.row.status === 'RUNNING'" link type="primary" @click="open(scope.row)">实时看板</el-button>
          <el-button v-if="scope.row.kind==='task' && scope.row.status==='COMPLETED'" link type="success" @click="evaluate(scope.row)">准确率验收</el-button>
        </template></el-table-column>
      </el-table>
    </div>
  </div>
</template>
