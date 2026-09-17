<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '../api'

type VectorStatus = {
  embedding: {
    provider: string; model_id: string; dimensions: number; max_length: number; precision: string; model_dir: string;
    runtime_installed: boolean; model_installed: boolean; ready: boolean; batch_size?: number; token_budget?: number
  }
  indexes: { counts: Record<string, number>; latest: any | null; index_dir: string }
  cache_dir: string
}
type UserRow = { username: string; role: string; enabled: boolean; must_change_password: boolean; created_at: string; updated_at: string }
type SystemInfo = {
  version: string
  data_dir: string
  baseline_max_target_rows: number
  index_dir: string
  authorization?: { roles?: string[] }
}

const info = ref<SystemInfo | null>(null)
const me = ref<UserRow | null>(null)
const vector = ref<VectorStatus | null>(null)
const indexes = ref<any[]>([])
const benchmarks = ref<any[]>([])
const users = ref<UserRow[]>([])
const loading = ref(false)
const technicalLoading = ref(false)
const technicalLoaded = ref(false)
const activeTab = ref('accounts')
const advancedSections = ref<string[]>([])
const embeddingBusy = ref(false)
const vectorBusy = ref(false)
const userDialogVisible = ref(false)
const userSaving = ref(false)
const userForm = reactive({ username: '', password: '', role: 'viewer' })
const resetDialogVisible = ref(false)
const resetTarget = ref<UserRow | null>(null)
const resetPassword = ref('')
const resetMustChange = ref(true)

const roleLabel: Record<string, string> = { admin: '管理员', operator: '操作员', reviewer: '复核员', viewer: '只读用户' }
const readyText = computed(() => vector.value?.embedding.ready ? '已就绪' : '需要运维处理')
const isAdmin = computed(() => me.value?.role === 'admin')
const canOperate = computed(() => me.value?.role === 'admin' || me.value?.role === 'operator')
const availableRoles = computed(() => {
  const serverRoles = info.value?.authorization?.roles?.filter((role) => role in roleLabel) ?? []
  return serverRoles.length ? serverRoles : Object.keys(roleLabel)
})
const roleModelText = computed(() => availableRoles.value.map(role => roleLabel[role] ?? role).join(' / '))
const readyIndexCount = computed(() => vector.value?.indexes.counts.READY ?? 0)

function pad2(value: number): string {
  return String(value).padStart(2, '0')
}

function formatDateTime(value: unknown): string {
  if (typeof value !== 'string' || !value) return '-'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return `${date.getFullYear()}-${pad2(date.getMonth() + 1)}-${pad2(date.getDate())} ${pad2(date.getHours())}:${pad2(date.getMinutes())}:${pad2(date.getSeconds())}`
}

function recallText(row: any): string {
  if (row?.kind !== 'vector_kernel') return '-'
  const recall = row?.metrics?.recall_quality?.recall_at
  if (!recall) return '-'
  const percent = (value: unknown) => typeof value === 'number' ? `${(value * 100).toFixed(1)}%` : '-'
  return `R@10 ${percent(recall['10'])} / R@50 ${percent(recall['50'])} / R@100 ${percent(recall['100'])}`
}

async function loadAdvanced(force = false): Promise<void> {
  if (technicalLoaded.value && !force) return
  technicalLoading.value = true
  try {
    const [indexResponse, benchmarkResponse] = await Promise.all([
      api.get('/indexes'),
      api.get('/system/benchmarks'),
    ])
    indexes.value = indexResponse.data.items ?? []
    benchmarks.value = benchmarkResponse.data ?? []
    technicalLoaded.value = true
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    technicalLoading.value = false
  }
}

async function refresh(): Promise<void> {
  loading.value = true
  try {
    const meResponse = await api.get('/auth/me')
    me.value = meResponse.data
    const requests: Promise<any>[] = [api.get('/system/info'), api.get('/system/vector-status')]
    if (me.value?.role === 'admin') requests.push(api.get('/users'))
    const responses = await Promise.all(requests)
    info.value = responses[0].data
    vector.value = responses[1].data
    users.value = isAdmin.value ? (responses[2]?.data ?? []) : []
    if (technicalLoaded.value) await loadAdvanced(true)
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    loading.value = false
  }
}

async function handleTabChange(name: string | number): Promise<void> {
  if (String(name) === 'advanced') await loadAdvanced()
}

async function runEmbeddingBenchmark(): Promise<void> {
  if (!canOperate.value) return
  embeddingBusy.value = true
  try {
    const response = await api.post('/system/benchmarks/embedding', { sample_count: 1000 })
    const profile = response.data.metrics.token_length_profile
    ElMessage.success(`Embedding：${response.data.metrics.throughput_rows_per_second} 条/秒，建议 max_length=${profile?.recommended_max_length ?? '-'}`)
    await loadAdvanced(true)
  } catch (error) { ElMessage.error((error as Error).message) }
  finally { embeddingBusy.value = false }
}

async function runVectorBenchmark(): Promise<void> {
  if (!canOperate.value) return
  vectorBusy.value = true
  try {
    const response = await api.post('/system/benchmarks/vector', { target_rows: 10000, query_count: 100, dimensions: 128, top_k: 50 })
    const recall = response.data.metrics.recall_quality?.recall_at ?? {}
    const r100 = typeof recall['100'] === 'number' ? `${(recall['100'] * 100).toFixed(1)}%` : '-'
    ElMessage.success(`向量内核基准完成：${response.data.metrics.search_queries_per_second} 查询/秒，Recall@100=${r100}`)
    await loadAdvanced(true)
  } catch (error) { ElMessage.error((error as Error).message) }
  finally { vectorBusy.value = false }
}

function openCreateUser(): void {
  Object.assign(userForm, { username: '', password: '', role: availableRoles.value.includes('viewer') ? 'viewer' : (availableRoles.value[0] ?? 'viewer') })
  userDialogVisible.value = true
}
async function createUser(): Promise<void> {
  if (!userForm.username.trim() || !userForm.password) return
  userSaving.value = true
  try {
    await api.post('/users', { username: userForm.username.trim(), password: userForm.password, role: userForm.role })
    ElMessage.success('账号已创建；首次登录必须修改初始密码')
    userDialogVisible.value = false
    await refresh()
  } catch (error) { ElMessage.error((error as Error).message) }
  finally { userSaving.value = false }
}
async function changeRole(row: UserRow, role: string): Promise<void> {
  try {
    await api.patch(`/users/${encodeURIComponent(row.username)}`, { role })
    ElMessage.success('角色已更新，该用户现有会话已失效')
    await refresh()
  } catch (error) { ElMessage.error((error as Error).message); await refresh() }
}
async function toggleEnabled(row: UserRow, enabled: boolean): Promise<void> {
  try {
    await api.patch(`/users/${encodeURIComponent(row.username)}`, { enabled })
    ElMessage.success(enabled ? '账号已启用' : '账号已停用，该用户现有会话已失效')
    await refresh()
  } catch (error) { ElMessage.error((error as Error).message); await refresh() }
}
function openReset(row: UserRow): void {
  resetTarget.value = row
  resetPassword.value = ''
  resetMustChange.value = true
  resetDialogVisible.value = true
}
async function submitReset(): Promise<void> {
  if (!resetTarget.value || !resetPassword.value) return
  userSaving.value = true
  try {
    await api.post(`/users/${encodeURIComponent(resetTarget.value.username)}/reset-password`, {
      password: resetPassword.value,
      must_change_password: resetMustChange.value,
    })
    ElMessage.success('密码已重置，该用户现有会话已失效')
    resetDialogVisible.value = false
    await refresh()
  } catch (error) { ElMessage.error((error as Error).message) }
  finally { userSaving.value = false }
}
async function changeOwnPassword(): Promise<void> {
  try {
    const current = await ElMessageBox.prompt('请输入当前密码', '修改我的密码', { inputType: 'password', confirmButtonText: '下一步', cancelButtonText: '取消' })
    const next = await ElMessageBox.prompt('请输入新密码（至少10位，包含字母和数字）', '修改我的密码', { inputType: 'password', confirmButtonText: '确认修改', cancelButtonText: '取消' })
    await api.post('/auth/change-password', { current_password: current.value, new_password: next.value })
    ElMessage.success('密码已修改，请重新登录')
    window.location.href = '/login'
  } catch (error) {
    if (error instanceof Error) ElMessage.error(error.message)
  }
}

onMounted(refresh)
</script>

<template>
  <div class="system-page">
    <div class="toolbar system-toolbar">
      <div class="system-title">
        <h2>系统设置</h2>
        <p>账号、权限和服务状态优先展示；模型、索引和性能基准仅在高级技术信息中查看。</p>
      </div>
      <div class="system-toolbar-actions">
        <el-tag v-if="me" class="identity-tag">{{ me.username }} · {{ roleLabel[me.role] ?? me.role }}</el-tag>
        <el-button @click="changeOwnPassword">修改我的密码</el-button>
        <el-button :loading="loading" @click="refresh">刷新状态</el-button>
      </div>
    </div>

    <div class="panel system-panel" v-loading="loading">
      <el-tabs v-model="activeTab" class="system-tabs" @tab-change="handleTabChange">
        <el-tab-pane label="账号与权限" name="accounts">
          <section class="account-summary">
            <div>
              <span>当前账号</span>
              <strong>{{ me?.username ?? '-' }}</strong>
            </div>
            <div>
              <span>当前角色</span>
              <strong>{{ roleLabel[me?.role ?? ''] ?? me?.role ?? '-' }}</strong>
            </div>
            <div>
              <span>账号状态</span>
              <strong>{{ me?.enabled === false ? '已停用' : '正常' }}</strong>
            </div>
          </section>

          <div v-if="isAdmin" class="system-section">
            <div class="system-section-head">
              <div class="system-section-copy">
                <h3>用户管理</h3>
                <p class="muted">维护登录账号与业务角色。停用、改角色或重置密码会立即撤销该用户现有会话。</p>
              </div>
              <el-button type="primary" @click="openCreateUser">创建账号</el-button>
            </div>
            <el-table class="system-table" :data="users" size="small" empty-text="尚无账号">
              <el-table-column prop="username" label="用户名" min-width="150" />
              <el-table-column label="角色" width="170">
                <template #default="scope">
                  <el-select class="system-role-select" :model-value="scope.row.role" @change="(value:string)=>changeRole(scope.row,value)">
                    <el-option v-for="role in availableRoles" :key="role" :label="roleLabel[role] ?? role" :value="role" />
                  </el-select>
                </template>
              </el-table-column>
              <el-table-column label="启用" width="90" align="center" header-align="center">
                <template #default="scope"><el-switch :model-value="scope.row.enabled" @change="(value:boolean)=>toggleEnabled(scope.row,value)" /></template>
              </el-table-column>
              <el-table-column label="需改密" width="90" align="center" header-align="center">
                <template #default="scope"><el-tag :type="scope.row.must_change_password?'warning':'success'">{{ scope.row.must_change_password?'是':'否' }}</el-tag></template>
              </el-table-column>
              <el-table-column label="更新时间" min-width="180">
                <template #default="scope"><span class="date-value">{{ formatDateTime(scope.row.updated_at) }}</span></template>
              </el-table-column>
              <el-table-column label="操作" width="120" align="center" header-align="center">
                <template #default="scope"><el-button link type="primary" @click="openReset(scope.row)">重置密码</el-button></template>
              </el-table-column>
            </el-table>
            <el-alert title="管理员可维护账号；操作员可执行匹配任务和同义词配置维护；复核员负责人工确认与结果复核；只读用户仅查看。系统禁止停用或降级最后一个管理员。" type="info" :closable="false" />
          </div>

          <el-empty v-else description="当前账号没有用户管理权限。你仍可修改自己的密码，并在“运行状态”查看服务是否正常。" />
        </el-tab-pane>

        <el-tab-pane label="运行状态" name="status">
          <section class="service-grid">
            <article>
              <span>平台服务</span>
              <strong class="service-ok">运行正常</strong>
              <small>系统接口已连接</small>
            </article>
            <article>
              <span>语义匹配服务</span>
              <strong :class="vector?.embedding.ready ? 'service-ok' : 'service-warn'">{{ readyText }}</strong>
              <small>{{ vector?.embedding.ready ? '可执行正式语义匹配' : '请联系运维检查模型环境' }}</small>
            </article>
            <article>
              <span>可用匹配索引</span>
              <strong>{{ readyIndexCount }}</strong>
              <small>由平台自动创建和复用</small>
            </article>
            <article>
              <span>系统版本</span>
              <strong>{{ info?.version ?? '-' }}</strong>
              <small>当前部署版本</small>
            </article>
          </section>
          <el-descriptions v-if="info" class="system-descriptions business-status" :column="2" border>
            <el-descriptions-item label="当前账号">{{ me?.username }}（{{ roleLabel[me?.role ?? ''] ?? me?.role }}）</el-descriptions-item>
            <el-descriptions-item label="业务角色">{{ roleModelText }}</el-descriptions-item>
            <el-descriptions-item label="单批数据安全上限">{{ info.baseline_max_target_rows }} 行</el-descriptions-item>
            <el-descriptions-item label="匹配服务状态">{{ vector?.embedding.ready ? '可用' : '需运维处理' }}</el-descriptions-item>
          </el-descriptions>
        </el-tab-pane>

        <el-tab-pane label="高级技术信息" name="advanced">
          <div class="advanced-note">
            <b>仅用于管理员 / 运维排障</b>
            <span>Embedding、Token Budget、向量索引、内部路径和性能基准不会出现在普通业务流程中。</span>
          </div>
          <el-collapse v-model="advancedSections" class="advanced-collapse" v-loading="technicalLoading">
            <el-collapse-item title="Embedding Provider 与运行参数" name="embedding">
              <div class="system-section-head">
                <h3>Embedding Provider</h3>
                <el-tag class="status-tag" :type="vector?.embedding.ready ? 'success' : 'warning'">{{ readyText }}</el-tag>
              </div>
              <el-descriptions v-if="vector" class="system-descriptions" :column="2" border>
                <el-descriptions-item label="Provider">{{ vector.embedding.provider }}</el-descriptions-item>
                <el-descriptions-item label="模型">{{ vector.embedding.model_id }}</el-descriptions-item>
                <el-descriptions-item label="维度">{{ vector.embedding.dimensions }}</el-descriptions-item>
                <el-descriptions-item label="最大长度">{{ vector.embedding.max_length }}</el-descriptions-item>
                <el-descriptions-item label="最大 Batch">{{ vector.embedding.batch_size ?? '-' }}</el-descriptions-item>
                <el-descriptions-item label="Token Budget">{{ vector.embedding.token_budget ?? '-' }}</el-descriptions-item>
                <el-descriptions-item label="精度">{{ vector.embedding.precision }}</el-descriptions-item>
                <el-descriptions-item label="Runtime">{{ vector.embedding.runtime_installed ? '已安装' : '未安装' }}</el-descriptions-item>
                <el-descriptions-item label="模型文件">{{ vector.embedding.model_installed ? '已安装' : '未安装' }}</el-descriptions-item>
                <el-descriptions-item label="模型目录"><span class="path-value">{{ vector.embedding.model_dir }}</span></el-descriptions-item>
              </el-descriptions>
              <div class="system-panel-actions">
                <el-button :loading="embeddingBusy" :disabled="!vector?.embedding.ready||!canOperate" @click="runEmbeddingBenchmark">运行 Embedding 基准</el-button>
                <el-button :loading="vectorBusy" :disabled="!canOperate" @click="runVectorBenchmark">运行向量内核基准</el-button>
              </div>
            </el-collapse-item>

            <el-collapse-item title="向量索引" name="indexes">
              <div v-if="vector" class="system-stats">
                <span>READY {{ vector.indexes.counts.READY || 0 }}</span>
                <span>BUILDING {{ vector.indexes.counts.BUILDING || 0 }}</span>
                <span>FAILED {{ vector.indexes.counts.FAILED || 0 }}</span>
              </div>
              <el-table class="system-table" :data="indexes" size="small" empty-text="尚未构建向量索引">
                <el-table-column prop="index_id" label="Index ID" min-width="220" show-overflow-tooltip/>
                <el-table-column prop="catalog_version_id" label="Catalog Version" min-width="180" show-overflow-tooltip/>
                <el-table-column prop="status" label="状态" width="110"/>
                <el-table-column label="创建时间" min-width="180"><template #default="scope"><span class="date-value">{{ formatDateTime(scope.row.created_at) }}</span></template></el-table-column>
                <el-table-column label="行数" width="100"><template #default="scope">{{ scope.row.metadata?.stats?.row_count ?? scope.row.metadata?.index_metadata?.row_count ?? '-' }}</template></el-table-column>
                <el-table-column label="模型" min-width="180"><template #default="scope">{{ scope.row.metadata?.provider?.model_id ?? '-' }}</template></el-table-column>
              </el-table>
            </el-collapse-item>

            <el-collapse-item title="性能与召回基准" name="benchmarks">
              <p class="muted system-note">这里是运维诊断记录，不代表最终业务匹配准确率。</p>
              <el-table class="system-table" :data="benchmarks" size="small" empty-text="尚无基准记录">
                <el-table-column prop="kind" label="类型" width="140"/>
                <el-table-column prop="status" label="状态" width="100"/>
                <el-table-column label="时间" min-width="180"><template #default="scope"><span class="date-value">{{ formatDateTime(scope.row.started_at) }}</span></template></el-table-column>
                <el-table-column label="吞吐" min-width="160"><template #default="scope"><span v-if="scope.row.kind==='embedding'">{{ scope.row.metrics?.throughput_rows_per_second ?? '-' }} 条/秒</span><span v-else>{{ scope.row.metrics?.search_queries_per_second ?? '-' }} 查询/秒</span></template></el-table-column>
                <el-table-column label="Recall@K" min-width="330"><template #default="scope">{{ recallText(scope.row) }}</template></el-table-column>
                <el-table-column label="Token P99 / 建议长度" min-width="180"><template #default="scope"><span v-if="scope.row.kind==='embedding'">P99 {{ scope.row.metrics?.token_length_profile?.p99 ?? '-' }} / {{ scope.row.metrics?.token_length_profile?.recommended_max_length ?? '-' }}</span><span v-else>-</span></template></el-table-column>
                <el-table-column prop="error_message" label="错误" min-width="220" show-overflow-tooltip/>
              </el-table>
            </el-collapse-item>

            <el-collapse-item title="内部目录与权限模型" name="paths">
              <el-descriptions v-if="info" class="system-descriptions" :column="2" border>
                <el-descriptions-item label="数据目录"><span class="path-value">{{ info.data_dir }}</span></el-descriptions-item>
                <el-descriptions-item label="向量索引目录"><span class="path-value">{{ info.index_dir }}</span></el-descriptions-item>
                <el-descriptions-item label="缓存目录"><span class="path-value">{{ vector?.cache_dir ?? '-' }}</span></el-descriptions-item>
                <el-descriptions-item label="角色模型">{{ availableRoles.join(' / ') }}</el-descriptions-item>
              </el-descriptions>
            </el-collapse-item>
          </el-collapse>
        </el-tab-pane>
      </el-tabs>
    </div>

    <el-dialog v-model="userDialogVisible" title="创建本地账号" width="560px">
      <el-form label-width="100px">
        <el-form-item label="用户名"><el-input v-model="userForm.username" /></el-form-item>
        <el-form-item label="初始密码"><el-input v-model="userForm.password" type="password" show-password /></el-form-item>
        <el-form-item label="角色"><el-select v-model="userForm.role"><el-option v-for="role in availableRoles" :key="role" :label="roleLabel[role] ?? role" :value="role" /></el-select></el-form-item>
      </el-form>
      <el-alert title="新账号首次登录必须修改初始密码。密码至少10位且包含字母和数字。" type="info" :closable="false"/>
      <template #footer><el-button @click="userDialogVisible=false">取消</el-button><el-button type="primary" :loading="userSaving" @click="createUser">创建账号</el-button></template>
    </el-dialog>
    <el-dialog v-model="resetDialogVisible" :title="resetTarget ? `重置密码：${resetTarget.username}` : '重置密码'" width="560px">
      <el-form label-width="120px">
        <el-form-item label="新密码"><el-input v-model="resetPassword" type="password" show-password /></el-form-item>
        <el-form-item label="下次登录改密"><el-switch v-model="resetMustChange" /></el-form-item>
      </el-form>
      <template #footer><el-button @click="resetDialogVisible=false">取消</el-button><el-button type="primary" :loading="userSaving" :disabled="!resetPassword" @click="submitReset">确认重置</el-button></template>
    </el-dialog>
  </div>
</template>

<style scoped src="../styles/pages/system.css"></style>
