<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { api } from '../api'

type AboutInfo = {
  product_name: string
  version: string
  build_time: string
  git_commit: string
  deployment_mode: string
}

const info = ref<AboutInfo | null>(null)
const loading = ref(false)

const deploymentModeText = computed(() => {
  if (info.value?.deployment_mode === 'native-source') return '原生源码部署'
  if (info.value?.deployment_mode === 'docker-source') return 'Docker 源码部署'
  return info.value?.deployment_mode || '-'
})

function formatDateTime(value: string | undefined): string {
  if (!value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString()
}

async function load(): Promise<void> {
  loading.value = true
  try {
    info.value = (await api.get('/about')).data
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    loading.value = false
  }
}

onMounted(load)
</script>

<template>
  <div class="about-page">
    <div class="toolbar about-toolbar">
      <div>
        <h2>系统设置 · 关于</h2>
        <p>这里显示当前正在运行的系统版本和部署信息，内容来自后端运行实例。</p>
      </div>
      <el-button :loading="loading" @click="load">刷新</el-button>
    </div>

    <div class="panel about-panel" v-loading="loading">
      <el-descriptions v-if="info" :column="1" border>
        <el-descriptions-item label="产品名称">{{ info.product_name }}</el-descriptions-item>
        <el-descriptions-item label="版本">v{{ info.version }}</el-descriptions-item>
        <el-descriptions-item label="构建时间">{{ formatDateTime(info.build_time) }}</el-descriptions-item>
        <el-descriptions-item label="Git Commit">
          <code>{{ info.git_commit || '-' }}</code>
        </el-descriptions-item>
        <el-descriptions-item label="部署方式">{{ deploymentModeText }}</el-descriptions-item>
      </el-descriptions>
      <el-empty v-else-if="!loading" description="暂时无法读取系统信息" />
    </div>
  </div>
</template>

<style scoped>
.about-page {
  display: grid;
  gap: 16px;
}

.about-toolbar {
  align-items: flex-start;
}

.about-toolbar h2 {
  margin: 0 0 6px;
}

.about-toolbar p {
  margin: 0;
  color: var(--text-secondary, #667085);
}

.about-panel {
  max-width: 920px;
}

.about-panel code {
  word-break: break-all;
  font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}
</style>
