<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from './api'
import { fetchAppVersion } from './version'
import { activeWorkspaceStep } from './workspaceStage'

const route = useRoute()
const router = useRouter()
const user = ref<{ username: string; role: string } | null>(null)
const appVersion = ref('')
const steps = [
  { n: 1, title: '第一步 · 数据上传', desc: '上传源 Excel 与目标集团码 Excel', path: '/profiles' },
  { n: 2, title: '第二步 · 进度监控', desc: '查看任务进度与实时处理情况', path: '/tasks' },
  { n: 3, title: '第三步 · 人工调整', desc: '集中处理需要人工确认的记录', path: '/review' },
  { n: 4, title: '第四步 · 输出结果', desc: '查看结果摘要并下载 Excel', path: '/results' },
] as const
const support = [
  ['同义词配置', '/data'],
  ['系统设置', '/system'],
] as const
const roleLabels: Record<string, string> = { admin: '管理员', operator: '操作员', reviewer: '复核员', viewer: '只读' }

const activeStep = computed<number | null>(() => {
  if (route.meta.workspace && activeWorkspaceStep.value) return activeWorkspaceStep.value
  const fromRoute = Number(route.meta.navStep)
  return Number.isInteger(fromRoute) && fromRoute >= 1 && fromRoute <= 4 ? fromRoute : null
})

onMounted(async () => {
  appVersion.value = await fetchAppVersion()
  if (route.path === '/login') return
  try { user.value = (await api.get('/auth/me')).data } catch { /* 401 由统一认证逻辑处理 */ }
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
          <svg class="brand-logo" viewBox="0 0 340 340" role="img" aria-label="小罡 AI">
            <rect x="28" y="28" width="284" height="284" rx="68" fill="#F3F3F3" stroke="#DFDFDF" stroke-width="5" />
            <path transform="translate(27.2 27.2) scale(.84)" fill="#BF2D2B" d="M205.01 21.76C277.37 114.16 126.85 160.8 103.94 239.52C7.77 157.08 172.37 93.36 205.01 21.76Z" />
            <path transform="translate(27.2 27.2) scale(.84)" fill="#1C2B7E" d="M233.52 92.66C337.04 175.54 161.32 240.64 132.46 317.06C57.19 221.08 208.33 172.91 233.52 92.66Z" />
          </svg>
        </span>
        <div class="brand-text">
          <b>小罡 AI</b>
          <span>物料智能匹配</span>
        </div>
      </div>
      <div class="step-nav">
        <button v-for="step in steps" :key="step.n" :class="{ active: step.n === activeStep }" @click="router.push(step.path)">
          <span class="step-no">{{ step.n }}</span>
          <span class="step-body"><span class="step-title">{{ step.title }}</span><span class="nav-desc">{{ step.desc }}</span></span>
        </button>
      </div>
      <nav class="support-nav">
        <button v-for="item in support" :key="item[1]" :class="{ active: route.path.startsWith(item[1]) }" @click="router.push(item[1])">
          <span class="nav-title">{{ item[0] }}</span>
        </button>
      </nav>
      <div class="side-foot"><span>小罡 AI</span><span v-if="appVersion"> · v{{ appVersion }}</span></div>
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
  width: 44px;
  height: 44px;
  flex: 0 0 44px;
  display: block;
}

.brand-logo {
  display: block;
  width: 44px;
  height: 44px;
  filter: drop-shadow(0 6px 10px rgba(8, 23, 70, 0.24));
}

.brand-text {
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 3px;
}

.brand-text b {
  color: #f7faff;
  font-size: 17px;
  font-weight: 800;
  letter-spacing: 0.7px;
  line-height: 1.15;
  text-shadow: 0 1px 8px rgba(0, 0, 0, 0.14);
}

.brand-text span {
  color: rgba(238, 244, 255, 0.74);
  font-size: 11px;
  line-height: 1.2;
  white-space: nowrap;
}

.support-nav {
  margin-top: 18px;
}
</style>
