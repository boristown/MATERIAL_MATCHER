<script setup lang="ts">
import { useRoute, useRouter } from 'vue-router'

const route = useRoute()
const router = useRouter()
const nav = [
  ['匹配任务', '/tasks'],
  ['匹配方案', '/profiles'],
  ['基础数据', '/data'],
  ['系统设置', '/system'],
] as const
</script>

<template>
  <router-view v-if="route.path === '/login'" />
  <div v-else class="shell">
    <aside>
      <div class="brand">集团码匹配</div>
      <button
        v-for="item in nav"
        :key="item[1]"
        :class="{ active: route.path.startsWith(item[1]) }"
        @click="router.push(item[1])"
      >
        {{ item[0] }}
      </button>
    </aside>
    <main>
      <header>
        <b>物料集团码匹配引擎</b>
        <span>admin</span>
      </header>
      <section class="content"><router-view /></section>
    </main>
  </div>
</template>
