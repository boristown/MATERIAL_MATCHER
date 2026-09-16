<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { api } from './api'

const route = useRoute()
const router = useRouter()
const user = ref<{ username: string; role: string } | null>(null)
const nav = [
  ['匹配任务', '/tasks', '任务创建、比对执行与人工复核'],
  ['匹配方案', '/profiles', '版本化可复用匹配规则模板'],
  ['基础数据', '/data', '集团码目录、文件与业务字典'],
  ['系统设置', '/system', '账号、模型与运行诊断'],
] as const
const roleLabels: Record<string, string> = { admin: '管理员', operator: '操作员', reviewer: '复核员', viewer: '只读' }

onMounted(async () => {
  if (route.path === '/login') return
  try {
    user.value = (await api.get('/auth/me')).data
  } catch {
    /* 401 由 api 拦截器跳转登录页 */
  }
})

async function logout(): Promise<void> {
  try {
    await api.post('/auth/logout')
  } finally {
    await router.push('/login')
  }
}
</script>

<template>
  <router-view v-if="route.path === '/login'" />
  <div v-else class="shell">
    <aside>
      <div class="brand"><span class="brand-mark">MM</span><div class="brand-text"><b>集团码匹配</b><small>MATERIAL_MATCHER</small></div></div>
      <nav>
        <button v-for="item in nav" :key="item[1]" :class="{ active: route.path.startsWith(item[1]) }" @click="router.push(item[1])">
          <span class="nav-title">{{ item[0] }}</span>
          <span v-if="route.path.startsWith(item[1])" class="nav-desc">{{ item[2] }}</span>
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
