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
const readyText = computed(() => vector.value?.embedding.ready ? '已就绪' : '未就绪')
const isAdmin = computed(() => me.value?.role === 'admin')
const canOperate = computed(() => me.value?.role === 'admin' || me.value?.role === 'operator')
const availableRoles = computed(() => {
  const serverRoles = info.value?.authorization?.roles?.filter((role) => role in roleLabel) ?? []
  return serverRoles.length ? serverRoles : Object.keys(roleLabel)
})
const roleModelText = computed(() => availableRoles.value.join(' / '))

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

async function refresh(): Promise<void> {
  loading.value = true
  try {
    const meResponse = await api.get('/auth/me')
    me.value = meResponse.data
    const requests: Promise<any>[] = [api.get('/system/info'), api.get('/system/vector-status'), api.get('/indexes'), api.get('/system/benchmarks')]
    if (me.value?.role === 'admin') requests.push(api.get('/users'))
    const responses = await Promise.all(requests)
    info.value = responses[0].data
    vector.value = responses[1].data
    indexes.value = responses[2].data.items ?? []
    benchmarks.value = responses[3].data ?? []
    users.value = isAdmin.value ? (responses[4]?.data ?? []) : []
  } catch (error) {
    ElMessage.error((error as Error).message)
  } finally {
    loading.value = false
  }
}

async function runEmbeddingBenchmark(): Promise<void> {
  if (!canOperate.value) return
  embeddingBusy.value = true
  try {
    const response = await api.post('/system/benchmarks/embedding', { sample_count: 1000 })
    const profile = response.data.metrics.token_length_profile
    ElMessage.success(`Embedding：${response.data.metrics.throughput_rows_per_second} 条/秒，建议 max_length=${profile?.recommended_max_length ?? '-'}`)
    await refresh()
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
    ElMessage.success(`BBQ 基准完成：${response.data.metrics.search_queries_per_second} 查询/秒，synthetic Recall@100=${r100}`)
    await refresh()
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
        <p>查看运行环境、模型与索引状态，并管理本地账号权限。</p>
      </div>
      <div class="system-toolbar-actions">
        <el-tag v-if="me" class="identity-tag">{{ me.username }} · {{ roleLabel[me.role] ?? me.role }}</el-tag>
        <el-button @click="changeOwnPassword">修改我的密码</el-button>
        <el-button :loading="loading" @click="refresh">刷新状态</el-button>
      </div>
    </div>

    <div class="panel system-panel" v-loading="loading">
      <h3>运行环境</h3>
      <el-descriptions v-if="info" class="system-descriptions" :column="2" border>
        <el-descriptions-item label="版本">{{ info.version }}</el-descriptions-item>
        <el-descriptions-item label="数据目录"><span class="path-value">{{ info.data_dir }}</span></el-descriptions-item>
        <el-descriptions-item label="扫描安全上限">{{ info.baseline_max_target_rows }} Target</el-descriptions-item>
        <el-descriptions-item label="向量索引目录"><span class="path-value">{{ info.index_dir }}</span></el-descriptions-item>
        <el-descriptions-item label="角色模型">{{ roleModelText }}</el-descriptions-item>
        <el-descriptions-item label="当前账号">{{ me?.username }}（{{ roleLabel[me?.role ?? ''] ?? me?.role }}）</el-descriptions-item>
      </el-descriptions>
    </div>

    <div v-if="isAdmin" class="panel system-panel">
      <div class="system-section-head">
        <div class="system-section-copy">
          <h3>账号与权限</h3>
          <p class="muted">权限由服务端强制执行；停用、改角色或重置密码会立即撤销该用户现有会话。</p>
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
      <el-alert title="admin：全部权限；operator：任务、方案、基础数据及基准操作；reviewer：只读 + 人工复核/最终结果/准确率验收；viewer：只读。系统禁止停用或降级最后一个管理员。" type="info" :closable="false" />
    </div>

    <div class="panel system-panel">
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
      <el-alert v-if="vector && !vector.embedding.ready" title="向量核心已安装，但正式语义匹配需要离线安装 ONNX Runtime、tokenizers 和 bge-base-zh-v1.5 模型文件。系统不会使用测试向量冒充生产模型。" type="warning" :closable="false"/>
      <el-alert v-else-if="vector" title="正式 Embedding 基准会统计 token P50/P95/P99/P99.9、不同 max_length 截断率和 padding efficiency，用于现场选择 128/192/256/512。" type="info" :closable="false"/>
      <div class="system-panel-actions">
        <el-button :loading="embeddingBusy" :disabled="!vector?.embedding.ready||!canOperate" @click="runEmbeddingBenchmark">运行正式 Embedding 基准</el-button>
        <el-button :loading="vectorBusy" :disabled="!canOperate" @click="runVectorBenchmark">运行 BBQ 内核基准</el-button>
      </div>
    </div>

    <div class="panel system-panel">
      <h3>向量索引版本</h3>
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
    </div>

    <div class="panel system-panel">
      <h3>性能与召回基准记录</h3>
      <p class="muted system-note">Embedding 基准使用正式已安装模型；BBQ 内核基准使用确定性测试向量，并以 float32 exact cosine 为 reference。后者用于防止索引优化导致召回退化，不代表真实业务准确率。</p>
      <el-table class="system-table" :data="benchmarks" size="small" empty-text="尚无基准记录">
        <el-table-column prop="kind" label="类型" width="140"/>
        <el-table-column prop="status" label="状态" width="100"/>
        <el-table-column label="时间" min-width="180"><template #default="scope"><span class="date-value">{{ formatDateTime(scope.row.started_at) }}</span></template></el-table-column>
        <el-table-column label="吞吐" min-width="160"><template #default="scope"><span v-if="scope.row.kind==='embedding'">{{ scope.row.metrics?.throughput_rows_per_second ?? '-' }} 条/秒</span><span v-else>{{ scope.row.metrics?.search_queries_per_second ?? '-' }} 查询/秒</span></template></el-table-column>
        <el-table-column label="Recall@K" min-width="330"><template #default="scope">{{ recallText(scope.row) }}</template></el-table-column>
        <el-table-column label="Token P99 / 建议长度" min-width="180"><template #default="scope"><span v-if="scope.row.kind==='embedding'">P99 {{ scope.row.metrics?.token_length_profile?.p99 ?? '-' }} / {{ scope.row.metrics?.token_length_profile?.recommended_max_length ?? '-' }}</span><span v-else>-</span></template></el-table-column>
        <el-table-column prop="error_message" label="错误" min-width="220" show-overflow-tooltip/>
      </el-table>
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
