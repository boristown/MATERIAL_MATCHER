<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { getSystemInfo, login, setToken } from './api'

const password = ref('')
const loading = ref(false)
const loggedIn = ref(Boolean(sessionStorage.getItem('material_matcher_token')))
const systemInfo = ref<any>(null)
const activeSection = ref('home')

const navigation = [
  { id: 'home', label: '首页' },
  { id: 'tasks', label: '匹配任务' },
  { id: 'wizard', label: '配置向导' },
  { id: 'data', label: '数据与索引' },
  { id: 'system', label: '系统管理' },
]

const sectionTitle = computed(() => navigation.find((item) => item.id === activeSection.value)?.label ?? '首页')

async function refreshSystemInfo() {
  if (!loggedIn.value) return
  try {
    systemInfo.value = await getSystemInfo()
  } catch (error: any) {
    if (error?.response?.status === 401) {
      setToken(null)
      loggedIn.value = false
    }
  }
}

async function doLogin() {
  if (!password.value) {
    ElMessage.warning('请输入管理员密码')
    return
  }
  loading.value = true
  try {
    await login(password.value)
    loggedIn.value = true
    password.value = ''
    await refreshSystemInfo()
    ElMessage.success('登录成功')
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail ?? '登录失败')
  } finally {
    loading.value = false
  }
}

function logout() {
  setToken(null)
  loggedIn.value = false
  systemInfo.value = null
}

function notImplemented(feature: string) {
  ElMessage.info(`${feature} 已进入开发计划，当前为第一阶段产品骨架`)
}

onMounted(refreshSystemInfo)
</script>

<template>
  <div v-if="!loggedIn" class="login-page">
    <div class="brand-panel">
      <div class="brand-mark">MM</div>
      <h1>MATERIAL_MATCHER</h1>
      <p>通用物料集团码批量匹配平台</p>
      <div class="brand-points">
        <span>零代码客户适配</span>
        <span>百万级高速召回</span>
        <span>可解释匹配结果</span>
      </div>
    </div>

    <el-card class="login-card" shadow="never">
      <div class="login-heading">
        <span class="eyebrow">管理员登录</span>
        <h2>欢迎回来</h2>
        <p>使用安装时生成的 admin 密码登录。</p>
      </div>
      <el-form @submit.prevent="doLogin">
        <el-form-item label="账号">
          <el-input model-value="admin" disabled />
        </el-form-item>
        <el-form-item label="密码">
          <el-input
            v-model="password"
            type="password"
            show-password
            autocomplete="current-password"
            placeholder="请输入管理员密码"
            @keyup.enter="doLogin"
          />
        </el-form-item>
        <el-button type="primary" class="login-button" :loading="loading" @click="doLogin">登录</el-button>
      </el-form>
      <div class="password-tip">
        密码文件：<code>/etc/material_matcher/secret/admin_password.env</code>
      </div>
    </el-card>
  </div>

  <div v-else class="app-shell">
    <aside class="sidebar">
      <div class="sidebar-brand">
        <div class="brand-mark small">MM</div>
        <div>
          <strong>MATERIAL_MATCHER</strong>
          <span>物料匹配平台</span>
        </div>
      </div>
      <nav>
        <button
          v-for="item in navigation"
          :key="item.id"
          class="nav-item"
          :class="{ active: activeSection === item.id }"
          @click="activeSection = item.id"
        >
          {{ item.label }}
        </button>
      </nav>
      <div class="sidebar-footer">
        <div class="version">v{{ systemInfo?.version ?? '0.1.0' }}</div>
        <button class="text-button" @click="logout">退出登录</button>
      </div>
    </aside>

    <main class="main-content">
      <header class="topbar">
        <div>
          <span class="eyebrow">MATERIAL_MATCHER</span>
          <h1>{{ sectionTitle }}</h1>
        </div>
        <div class="health-pill"><span class="health-dot"></span> 服务正常</div>
      </header>

      <template v-if="activeSection === 'home'">
        <section class="hero-card">
          <div>
            <span class="eyebrow light">快速开始</span>
            <h2>从 Excel 到集团码结果，不需要写配置文件</h2>
            <p>上传客户物料和集团码样表，系统会自动识别字段、推荐映射与权重，再通过试跑确认后发布。</p>
          </div>
          <el-button size="large" type="primary" @click="activeSection = 'wizard'">开始配置向导</el-button>
        </section>

        <section class="quick-grid">
          <button class="action-card primary-card" @click="notImplemented('新建匹配任务')">
            <span class="action-index">01</span>
            <strong>新建匹配任务</strong>
            <p>选择已发布的配置方案，上传待匹配数据并运行。</p>
          </button>
          <button class="action-card" @click="activeSection = 'wizard'">
            <span class="action-index">02</span>
            <strong>配置向导</strong>
            <p>图形化完成字段识别、映射、权重、阈值和试跑。</p>
          </button>
          <button class="action-card" @click="notImplemented('数据与索引')">
            <span class="action-index">03</span>
            <strong>数据与索引</strong>
            <p>管理集团码 Catalog、BBQ 索引及模型版本。</p>
          </button>
          <button class="action-card" @click="notImplemented('临时文件管理')">
            <span class="action-index">04</span>
            <strong>临时文件</strong>
            <p>查看任务缓存占用，并安全清理可删除文件。</p>
          </button>
        </section>

        <section class="status-grid">
          <el-card shadow="never">
            <template #header><strong>系统状态</strong></template>
            <div class="status-row"><span>服务版本</span><strong>{{ systemInfo?.version ?? '-' }}</strong></div>
            <div class="status-row"><span>服务端口</span><strong>{{ systemInfo?.port ?? '-' }}</strong></div>
            <div class="status-row"><span>数据目录</span><strong>{{ systemInfo?.data_dir ?? '-' }}</strong></div>
          </el-card>
          <el-card shadow="never">
            <template #header><strong>当前阶段</strong></template>
            <div class="empty-state">
              <div class="empty-icon">✓</div>
              <strong>基础服务已启动</strong>
              <span>下一步将实现 Excel 自动识别与配置向导。</span>
            </div>
          </el-card>
        </section>
      </template>

      <template v-else-if="activeSection === 'wizard'">
        <section class="page-card wizard-shell">
          <div class="wizard-header">
            <div>
              <span class="eyebrow">新建配置方案</span>
              <h2>配置向导</h2>
              <p>普通模式只需要确认业务含义，不需要理解 YAML、Join、Rule Set 或插件。</p>
            </div>
            <el-tag type="success" effect="light">向导模式</el-tag>
          </div>
          <el-steps :active="0" finish-status="success" align-center>
            <el-step title="上传客户物料" />
            <el-step title="上传集团码" />
            <el-step title="确认字段" />
            <el-step title="设置匹配规则" />
            <el-step title="试跑" />
            <el-step title="发布" />
          </el-steps>
          <div class="wizard-placeholder">
            <div class="upload-illustration">XLSX</div>
            <h3>第一步：上传客户物料样表</h3>
            <p>下一阶段将实现自动识别 Sheet、表头、字段含义、空值和前导零风险。</p>
            <el-button type="primary" disabled>选择 Excel 文件（开发中）</el-button>
          </div>
        </section>
      </template>

      <template v-else>
        <section class="page-card coming-soon">
          <div class="empty-icon">↗</div>
          <h2>{{ sectionTitle }}</h2>
          <p>该模块已进入 MVP 开发计划。</p>
        </section>
      </template>
    </main>
  </div>
</template>
