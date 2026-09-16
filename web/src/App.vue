<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from './api'

const route = useRoute()
const router = useRouter()
const user = ref<{ username: string; role: string } | null>(null)
const steps = [
  { n: 1, title: '方案与配置', desc: '字段映射 · 过滤 · 阈值', path: '/profiles' },
  { n: 2, title: '匹配计算', desc: '实时进度 · 中间结果', path: '/tasks' },
  { n: 3, title: '人工调整', desc: '复核 · 重判 · 候选对比', path: '/review' },
  { n: 4, title: '输出结果', desc: '匹配摘要 · Excel 下载', path: '/results' },
] as const
const support = [
  ['基础数据', '/data'],
  ['系统设置', '/system'],
] as const
const roleLabels: Record<string, string> = { admin: '管理员', operator: '操作员', reviewer: '复核员', viewer: '只读' }

function stepActive(path: string): boolean {
  if (path === '/profiles') return route.path.startsWith('/profiles') || route.path.startsWith('/tasks/new') || route.path.startsWith('/tasks/workspace')
  if (path === '/tasks') return route.path === '/tasks' || (route.path.startsWith('/tasks/') && !route.path.endsWith('/evaluation'))
  if (path === '/review') return route.path.startsWith('/review')
  if (path === '/results') return route.path.startsWith('/results')
  return false
}

onMounted(async () => {
  if (route.path === '/login') return
  try { user.value = (await api.get('/auth/me')).data } catch { /* 401 由拦截器处理 */ }
})
async function logout(): Promise<void> {
  try { await api.post('/auth/logout') } finally { await router.push('/login') }
}
</script>

<template>
  <router-view v-if="route.path === '/login'" />
  <div v-else class="shell">
    <aside>
      <div class="brand"><span class="brand-mark">MM</span><div class="brand-text"><b>集团码匹配</b><small>MATERIAL_MATCHER</small></div></div>
      <div class="step-nav">
        <button v-for="step in steps" :key="step.n" :class="{ active: stepActive(step.path) }" @click="router.push(step.path)">
          <span class="step-no" :class="{ done: false }">{{ step.n }}</span>
          <span class="step-body"><span class="step-title">STEP {{ step.n }} · {{ step.title }}</span><span class="nav-desc">{{ step.desc }}</span></span>
        </button>
      </div>
      <div class="side-divider">支撑功能</div>
      <nav class="support-nav">
        <button v-for="item in support" :key="item[1]" :class="{ active: route.path.startsWith(item[1]) }" @click="router.push(item[1])">
          <span class="nav-title">{{ item[0] }}</span>
        </button>
      </nav>
      <div class="side-foot">v1.0 · bge-base-zh-v1.5</div>
    </aside>
    <main>
      <header>
        <b>物料集团码智能匹配平台</b>
        <div class="head-right">
          <span v-if="user" class="user-chip"><i>{{ user.username }}</i><em>{{ roleLabels[user.role] ?? user.role }}</em></span>
          <button v-if="user" class="logout" @click="logout">退出</button>
        </div>
      </header>
      <section class="content"><router-view /></section>
    </main>
  </div>
</template>
