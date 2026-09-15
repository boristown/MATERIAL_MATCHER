<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { api } from '../api'

const username = ref('admin')
const password = ref('')
const newPassword = ref('')
const confirmPassword = ref('')
const error = ref('')
const busy = ref(false)
const passwordChangeRequired = ref(false)
const router = useRouter()

async function login(): Promise<void> {
  error.value = ''
  busy.value = true
  try {
    const response = await api.post('/auth/login', { username: username.value.trim(), password: password.value })
    if (response.data?.user?.must_change_password) {
      passwordChangeRequired.value = true
      return
    }
    await router.push('/tasks')
  } catch (exception) {
    error.value = (exception as Error).message
  } finally {
    busy.value = false
  }
}

async function changePassword(): Promise<void> {
  error.value = ''
  if (newPassword.value.length < 10) {
    error.value = '新密码至少需要10个字符，并同时包含字母和数字'
    return
  }
  if (newPassword.value !== confirmPassword.value) {
    error.value = '两次输入的新密码不一致'
    return
  }
  busy.value = true
  try {
    await api.post('/auth/change-password', { current_password: password.value, new_password: newPassword.value })
    password.value = ''
    newPassword.value = ''
    confirmPassword.value = ''
    passwordChangeRequired.value = false
    error.value = '密码修改成功，请使用新密码重新登录'
  } catch (exception) {
    error.value = (exception as Error).message
  } finally {
    busy.value = false
  }
}
</script>

<template>
  <div class="login">
    <div class="card">
      <h1>物料集团码匹配引擎</h1>
      <template v-if="!passwordChangeRequired">
        <p>使用分配的本地账号登录</p>
        <el-input v-model="username" placeholder="用户名" autocomplete="username" />
        <el-input v-model="password" type="password" show-password placeholder="密码" autocomplete="current-password" @keyup.enter="login" />
        <p class="error">{{ error }}</p>
        <el-button type="primary" class="full" :loading="busy" :disabled="!username.trim()||!password" @click="login">登录</el-button>
      </template>
      <template v-else>
        <p>账号 {{ username }} 需要先修改初始/重置密码。</p>
        <el-alert title="新密码至少10个字符，并同时包含字母和数字。修改成功后需要重新登录。" type="warning" :closable="false" />
        <el-input v-model="newPassword" type="password" show-password placeholder="新密码" autocomplete="new-password" />
        <el-input v-model="confirmPassword" type="password" show-password placeholder="再次输入新密码" autocomplete="new-password" @keyup.enter="changePassword" />
        <p class="error">{{ error }}</p>
        <el-button type="primary" class="full" :loading="busy" :disabled="!newPassword||!confirmPassword" @click="changePassword">修改密码</el-button>
      </template>
    </div>
  </div>
</template>

<style scoped>
.card .el-input{margin:8px 0}.card .el-alert{margin:12px 0}.error{min-height:20px;color:#c45656}
</style>
