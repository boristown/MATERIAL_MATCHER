<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api'

const password = ref('')
const error = ref('')
const router = useRouter()

async function login(): Promise<void> {
  error.value = ''
  try {
    await api.post('/auth/login', { username: 'admin', password: password.value })
    await router.push('/tasks')
  } catch (exception) {
    error.value = (exception as Error).message
  }
}
</script>

<template>
  <div class="login">
    <div class="card">
      <h1>物料集团码匹配引擎</h1>
      <p>账号：admin</p>
      <el-input v-model="password" type="password" show-password @keyup.enter="login" />
      <p class="error">{{ error }}</p>
      <el-button type="primary" class="full" :disabled="!password" @click="login">登录</el-button>
    </div>
  </div>
</template>
