<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api'

type Row = { id: string; name: string; stage: string; progress: number; status: string; created_at: string; kind: 'task' | 'draft' }
const props = defineProps<{ mode?: 'review' | 'result' }>()
const router = useRouter()
const allRows = ref<Row[]>([])
const stageLabels: Record<string, string> = { CALCULATE: '比对计算', REVIEW: '人工处理', RESULT: '生成结果' }
const rows = computed(() => {
  if (props.mode === 'review') return allRows.value.filter(row => row.kind === 'task' && row.stage === '人工处理')
  if (props.mode === 'result') return allRows.value.filter(row => row.kind === 'task' && row.stage === '生成结果')
  return allRows.value
})
const pageTitle = computed(() => props.mode === 'review' ? 'STEP 3 · 人工调整' : props.mode === 'result' ? 'STEP 4 · 输出结果' : 'STEP 2 · 匹配计算')
const pageDesc = computed(() => props.mode === 'review' ? '待确认/运行中的任务,点击进入复核与阈值重判。' : props.mode === 'result' ? '已完成任务:生成匹配摘要与样式化 Excel。' : '全部任务与草稿;运行中任务可实时查看进度与中间结果。')

async function load(): Promise<void> {
  try {
    const [tasks, drafts] = await Promise.all([api.get('/tasks'), api.get('/task-drafts')])
    allRows.value = [
      ...tasks.data.map((task: any) => ({ id: task.task_id, name: task.name, stage: stageLabels[task.stage] ?? task.stage, progress: task.progress, status: task.status, created_at: task.created_at, kind: 'task' as const })),
      ...drafts.data.map((draft: any) => ({ id: draft.draft_id, name: draft.name, stage: draft.current_step === 1 ? '选择数据' : '确认匹配规则', progress: 0, status: '草稿', created_at: draft.updated_at, kind: 'draft' as const })),
    ].sort((a, b) => b.created_at.localeCompare(a.created_at))
  } catch { await router.push('/login') }
}
function open(row: Row): void { row.kind === 'draft' ? router.push({ path: '/tasks/new', query: { draft: row.id } }) : router.push(`/tasks/${row.id}`) }
function evaluate(row: Row): void { if (row.kind === 'task') router.push(`/tasks/${row.id}/evaluation`) }
onMounted(load)
</script>
<template><div class="toolbar"><div><h2>匹配任务</h2><p>从选择数据到生成结果保持同一任务上下文；完成后的任务可使用独立标注集进行准确率验收。</p></div><el-button type="primary" @click="router.push('/tasks/new')">新建匹配任务</el-button></div><el-table :data="rows"><el-table-column prop="id" label="任务编号" width="180"/><el-table-column prop="name" label="任务名称"/><el-table-column prop="stage" label="当前阶段"/><el-table-column prop="progress" label="进度"/><el-table-column prop="status" label="状态"/><el-table-column prop="created_at" label="创建时间"/><el-table-column label="操作" min-width="180"><template #default="scope"><el-button link type="primary" @click="open(scope.row)">{{ scope.row.status === 'COMPLETED' ? '查看' : '继续' }}</el-button><el-button v-if="scope.row.kind==='task' && scope.row.status==='COMPLETED'" link type="success" @click="evaluate(scope.row)">准确率验收</el-button></template></el-table-column></el-table></template>
