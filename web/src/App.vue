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
      <div class="brand">
        <span class="brand-mark" aria-hidden="true">
          <svg class="brand-logo" viewBox="0 0 44 44" role="img" aria-label="集团码匹配">
            <defs>
              <linearGradient id="brand-bg" x1="7" y1="5" x2="38" y2="40" gradientUnits="userSpaceOnUse">
                <stop stop-color="#48A6FF" />
                <stop offset="0.46" stop-color="#2876F5" />
                <stop offset="1" stop-color="#1847C9" />
              </linearGradient>
              <radialGradient id="brand-glow" cx="0" cy="0" r="1" gradientTransform="translate(12 8) rotate(47) scale(34)" gradientUnits="userSpaceOnUse">
                <stop stop-color="white" stop-opacity="0.26" />
                <stop offset="1" stop-color="white" stop-opacity="0" />
              </radialGradient>
              <linearGradient id="brand-accent" x1="15" y1="14" x2="29" y2="30" gradientUnits="userSpaceOnUse">
                <stop stop-color="#E7FAFF" />
                <stop offset="1" stop-color="#8EEBFF" />
              </linearGradient>
            </defs>
            <rect x="2" y="2" width="40" height="40" rx="11" fill="url(#brand-bg)" />
            <rect x="2.5" y="2.5" width="39" height="39" rx="10.5" fill="url(#brand-glow)" stroke="white" stroke-opacity="0.14" />
            <path d="M11 13.5h6.1c2.15 0 3.9 1.75 3.9 3.9v1.1" fill="none" stroke="white" stroke-width="2.7" stroke-linecap="round" stroke-linejoin="round" />
            <path d="M33 13.5h-6.1c-2.15 0-3.9 1.75-3.9 3.9v1.1" fill="none" stroke="white" stroke-width="2.7" stroke-linecap="round" stroke-linejoin="round" />
            <path d="M11 30.5h6.1c2.15 0 3.9-1.75 3.9-3.9v-1.1" fill="none" stroke="white" stroke-width="2.7" stroke-linecap="round" stroke-linejoin="round" />
            <path d="M33 30.5h-6.1c-2.15 0-3.9-1.75-3.9-3.9v-1.1" fill="none" stroke="white" stroke-width="2.7" stroke-linecap="round" stroke-linejoin="round" />
            <rect x="18.2" y="18.2" width="7.6" height="7.6" rx="2.15" transform="rotate(45 22 22)" fill="url(#brand-accent)" />
            <circle cx="11" cy="13.5" r="1.7" fill="white" />
            <circle cx="33" cy="13.5" r="1.7" fill="white" />
            <circle cx="11" cy="30.5" r="1.7" fill="white" />
            <circle cx="33" cy="30.5" r="1.7" fill="white" />
          </svg>
        </span>
        <div class="brand-text"><b>集团码匹配</b></div>
      </div>
      <div class="step-nav">
        <button v-for="step in steps" :key="step.n" :class="{ active: stepActive(step.path) }" @click="router.push(step.path)">
          <span class="step-no" :class="{ done: false }">{{ step.n }}</span>
          <span class="step-body"><span class="step-title">STEP {{ step.n }} · {{ step.title }}</span><span class="nav-desc">{{ step.desc }}</span></span>
        </button>
      </div>
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

<style scoped>
.brand {
  gap: 12px;
  padding: 2px 8px 24px;
}

.brand-mark {
  width: 42px;
  height: 42px;
  border-radius: 12px;
  display: block;
  background: transparent;
  box-shadow: none;
  overflow: visible;
}

.brand-logo {
  display: block;
  width: 42px;
  height: 42px;
  filter: drop-shadow(0 7px 10px rgba(20, 87, 214, 0.34));
}

.brand-text b {
  color: #f7faff;
  font-size: 16px;
  font-weight: 700;
  letter-spacing: 0.9px;
  line-height: 1.2;
  text-shadow: 0 1px 8px rgba(0, 0, 0, 0.14);
}

.support-nav {
  margin-top: 18px;
}
</style>
