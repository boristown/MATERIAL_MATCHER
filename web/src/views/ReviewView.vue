<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api'
import '../styles/pages/review.css'

type Row = { id: string; name: string; stage: string; progress: number; status: string; created_at: string }
const router = useRouter()
const rows = ref<Row[]>([])
const stageLabels: Record<string, string> = { CALCULATE: '比对计算', REVIEW: '人工处理', RESULT: '生成结果' }
const RUNNING_STATUSES = ['RUNNING', 'PREPARING', 'RECOVERING', 'PENDING']

function statusTagType(status: string): 'success' | 'danger' | 'warning' | 'primary' | 'info' {
  if (status === 'COMPLETED') return 'success'
  if (status === 'FAILED') return 'danger'
  if (RUNNING_STATUSES.includes(status)) return 'primary'
  return 'warning'
}
function statusLabel(status: string): string {
  return ({ RUNNING: '运行中', PREPARING: '准备中', RECOVERING: '恢复中', PENDING: '排队中', COMPLETED: '已完成', FAILED: '失败' } as Record<string, string>)[status] ?? status
}
async function load(): Promise<void> {
  try {
    const tasks = (await api.get('/tasks')).data ?? []
    rows.value = tasks
      .map((task: any) => ({ id: task.task_id, name: task.name, stage: stageLabels[task.stage] ?? task.stage, progress: task.progress, status: task.status, created_at: task.created_at }))
      .filter((row: Row) => row.stage === '人工处理')
      .sort((a: Row, b: Row) => b.created_at.localeCompare(a.created_at))
  } catch { await router.push('/login') }
}
function open(row: Row): void { router.push(`/tasks/${row.id}`) }
onMounted(load)
</script>

<template>
  <div class="review-page">
    <div class="toolbar">
      <div><h2>STEP 3 · 人工调整</h2><p>待确认任务:点击进入复核、阈值重判与候选对比。</p></div>
      <el-button type="primary" @click="router.push('/tasks/new')">新建匹配任务</el-button>
    </div>

    <div class="panel">
      <div class="section-head"><h3 style="margin:0">任务列表</h3></div>
      <el-table :data="rows" size="default">
        <el-table-column label="名称" min-width="220"><template #default="scope"><a class="row-link" @click="open(scope.row)">{{ scope.row.name }}</a><div class="row-sub">{{ scope.row.id }}</div></template></el-table-column>
        <el-table-column prop="stage" label="阶段" width="120"/>
        <el-table-column label="进度" width="170"><template #default="scope"><el-progress :percentage="Math.round(Number(scope.row.progress ?? 0))" :stroke-width="8" :status="scope.row.status==='FAILED'?'exception':scope.row.status==='COMPLETED'?'success':undefined"/></template></el-table-column>
        <el-table-column label="状态" width="100"><template #default="scope"><el-tag size="small" :type="statusTagType(scope.row.status)">{{ statusLabel(scope.row.status) }}</el-tag></template></el-table-column>
        <el-table-column label="更新时间" width="170"><template #default="scope">{{ String(scope.row.created_at).slice(0, 19).replace('T', ' ') }}</template></el-table-column>
        <el-table-column label="操作" min-width="120"><template #default="scope"><el-button link type="primary" @click="open(scope.row)">{{ scope.row.status === 'COMPLETED' ? '查看' : '继续' }}</el-button></template></el-table-column>
      </el-table>
    </div>
  </div>
</template>
