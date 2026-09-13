<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api'

type Row = { id: string; name: string; stage: string; progress: number; status: string; created_at: string; kind: 'task' | 'draft' }
const router = useRouter()
const rows = ref<Row[]>([])
const stageLabels: Record<string, string> = { CALCULATE: '比对计算', REVIEW: '人工处理', RESULT: '生成结果' }

async function load(): Promise<void> {
  try {
    const [tasks, drafts] = await Promise.all([api.get('/tasks'), api.get('/task-drafts')])
    rows.value = [
      ...tasks.data.map((task: any) => ({ id: task.task_id, name: task.name, stage: stageLabels[task.stage] ?? task.stage, progress: task.progress, status: task.status, created_at: task.created_at, kind: 'task' as const })),
      ...drafts.data.map((draft: any) => ({ id: draft.draft_id, name: draft.name, stage: draft.current_step === 1 ? '选择数据' : '确认匹配规则', progress: 0, status: '草稿', created_at: draft.updated_at, kind: 'draft' as const })),
    ].sort((a, b) => b.created_at.localeCompare(a.created_at))
  } catch { await router.push('/login') }
}
function open(row: Row): void { row.kind === 'draft' ? router.push({ path: '/tasks/new', query: { draft: row.id } }) : router.push(`/tasks/${row.id}`) }
onMounted(load)
</script>
<template><div class="toolbar"><div><h2>匹配任务</h2><p>从选择数据到生成结果保持同一任务上下文。</p></div><el-button type="primary" @click="router.push('/tasks/new')">新建匹配任务</el-button></div><el-table :data="rows"><el-table-column prop="id" label="任务编号" width="180"/><el-table-column prop="name" label="任务名称"/><el-table-column prop="stage" label="当前阶段"/><el-table-column prop="progress" label="进度"/><el-table-column prop="status" label="状态"/><el-table-column prop="created_at" label="创建时间"/><el-table-column label="操作"><template #default="scope"><el-button link type="primary" @click="open(scope.row)">{{ scope.row.status === 'COMPLETED' ? '查看' : '继续' }}</el-button></template></el-table-column></el-table></template>
