<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '../api'

type ProfileRow = { profile_id: string; name: string; latest_published_version?: number | null; has_draft: number; updated_at?: string; created_at?: string }
type VersionRow = { version_no: number; status: string; sha256: string; created_at: string; document: any }

const router = useRouter()
const profiles = ref<ProfileRow[]>([])
const canDelete = ref(false)
const loading = ref(false)
const versionsVisible = ref(false)
const versionsOf = ref<ProfileRow | null>(null)
const versions = ref<VersionRow[]>([])

async function load(): Promise<void> {
  loading.value = true
  try { profiles.value = (await api.get('/profiles')).data ?? [] } finally { loading.value = false }
}
function createProfile(): void { router.push({ path: '/tasks/new', query: { edit: '1' } }) }
function useProfile(row: ProfileRow): void { router.push({ path: '/tasks/new', query: { profile: row.profile_id } }) }
function editProfile(row: ProfileRow): void { router.push({ path: '/tasks/new', query: { profile: row.profile_id, edit: '1' } }) }
async function renameProfile(row: ProfileRow): Promise<void> {
  try {
    const { value } = await ElMessageBox.prompt('方案名称(建议代码在前,如 A001 元器件)', '重命名方案', { inputValue: row.name, confirmButtonText: '保存', cancelButtonText: '取消' })
    await api.patch(`/profiles/${row.profile_id}`, { name: value.trim() })
    ElMessage.success('已重命名')
    await load()
  } catch (error) { if (error !== 'cancel') ElMessage.error((error as Error).message ?? '重命名失败') }
}
async function deleteProfile(row: ProfileRow): Promise<void> {
  try {
    await ElMessageBox.confirm(`删除方案「${row.name}」及其全部版本?被任务或草稿引用的方案无法删除。`, '删除方案', { type: 'warning', confirmButtonText: '删除', cancelButtonText: '取消' })
    await api.delete(`/profiles/${row.profile_id}`)
    ElMessage.success('已删除')
    await load()
  } catch (error) { if (error !== 'cancel') ElMessage.error((error as Error).message ?? '删除失败') }
}
async function openVersions(row: ProfileRow): Promise<void> {
  versionsOf.value = row
  versions.value = (await api.get(`/profiles/${row.profile_id}/versions`)).data ?? []
  versionsVisible.value = true
}
async function rollback(row: ProfileRow, versionNo: number): Promise<void> {
  try {
    await ElMessageBox.confirm(`将基于 v${versionNo} 复制生成新的发布版本(历史版本保持不变),确认回滚?`, '回滚方案', { type: 'warning' })
    await api.post(`/profiles/${row.profile_id}/rollback/${versionNo}`)
    ElMessage.success('回滚完成,已产生新发布版本')
    await load()
  } catch (error) { if (error !== 'cancel') ElMessage.error((error as Error).message ?? '回滚失败') }
}
function originOf(row: ProfileRow): string {
  const version = versions.value.find(item => item.status === 'PUBLISHED')
  return String(version?.document?.advanced?.origin ?? '')
}
onMounted(async () => {
  await load()
  try { canDelete.value = ((await api.get('/auth/me')).data?.role ?? '') === 'admin' } catch { canDelete.value = false }
})
</script>

<template>
  <div v-loading="loading" class="profiles-page">
    <div class="toolbar">
      <div><h2>匹配方案</h2><p>方案 = 可复用的字段映射 + 过滤 + 阈值模板;发布后不可变,任务引用时冻结版本。</p></div>
      <el-button type="primary" @click="createProfile">＋ 新建方案</el-button>
    </div>
    <el-empty v-if="!profiles.length" description="尚无方案。点击「新建方案」进入专用方案配置页。"/>
    <div class="profile-grid">
      <div v-for="row in profiles" :key="row.profile_id" class="profile-card">
        <div class="profile-head">
          <b class="profile-name">{{ row.name }}</b>
          <div class="profile-tags">
            <el-tag v-if="row.latest_published_version" size="small" type="success">已发布 v{{ row.latest_published_version }}</el-tag>
            <el-tag v-if="row.has_draft" size="small" type="warning">有草稿</el-tag>
          </div>
        </div>
        <p class="muted">更新:{{ String(row.updated_at ?? row.created_at ?? '').slice(0, 19).replace('T', ' ') }}</p>
        <div class="profile-actions">
          <el-button type="primary" size="small" :disabled="!row.latest_published_version" @click="useProfile(row)">用此方案建任务</el-button>
          <el-button size="small" @click="editProfile(row)">编辑</el-button>
          <el-button size="small" @click="openVersions(row)">版本</el-button>
          <el-button size="small" @click="renameProfile(row)">重命名</el-button>
          <el-button v-if="canDelete" size="small" type="danger" plain @click="deleteProfile(row)">删除</el-button>
        </div>
      </div>
    </div>
    <el-dialog v-model="versionsVisible" :title="`版本历史 · ${versionsOf?.name ?? ''}`" width="640px">
      <el-table :data="versions" size="small">
        <el-table-column prop="version_no" label="版本" width="70"/>
        <el-table-column label="状态" width="100"><template #default="scope"><el-tag size="small" :type="scope.row.status==='PUBLISHED'?'success':'info'">{{ scope.row.status }}</el-tag></template></el-table-column>
        <el-table-column label="SHA-256" min-width="160"><template #default="scope"><code>{{ String(scope.row.sha256).slice(0, 16) }}…</code></template></el-table-column>
        <el-table-column prop="created_at" label="时间" min-width="150"><template #default="scope">{{ String(scope.row.created_at).slice(0, 19).replace('T', ' ') }}</template></el-table-column>
        <el-table-column label="来源" min-width="140"><template #default="scope">{{ String(scope.row.document?.advanced?.origin ?? '') }}</template></el-table-column>
        <el-table-column label="" width="80"><template #default="scope"><el-button v-if="scope.row.status==='PUBLISHED'" link size="small" @click="rollback(versionsOf!, scope.row.version_no)">回滚</el-button></template></el-table-column>
      </el-table>
    </el-dialog>
  </div>
</template>

<style scoped>
.profiles-page .profile-grid {
  grid-template-columns: repeat(auto-fill, minmax(min(100%, 320px), 1fr));
}
.profiles-page .profile-card {
  min-width: 0;
}
.profile-head {
  align-items: flex-start;
}
.profile-name {
  flex: 1 1 180px;
  min-width: 0;
  overflow-wrap: anywhere;
  word-break: break-word;
  line-height: 1.45;
}
.profile-tags {
  display: flex;
  flex: 0 0 auto;
  flex-wrap: wrap;
  justify-content: flex-end;
  gap: 6px;
  max-width: 100%;
}
.profile-actions {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  min-width: 0;
}
.profile-actions :deep(.el-button) {
  flex: 0 0 auto;
  margin-left: 0;
}
.profile-actions :deep(.el-button + .el-button) {
  margin-left: 0;
}
@media (max-width: 720px) {
  .profile-tags {
    justify-content: flex-start;
    flex-basis: 100%;
  }
  .profile-actions :deep(.el-button) {
    flex: 1 1 calc(50% - 8px);
  }
}
</style>
