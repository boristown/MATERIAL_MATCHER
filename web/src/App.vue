<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  cleanupFiles,
  createTask,
  deleteFile,
  downloadTaskResult,
  dryRun,
  getSystemInfo,
  listFiles,
  listProfiles,
  listTasks,
  login,
  publishProfile,
  setToken,
  uploadExcel,
  type MappingConfig,
  type MatchConfig,
} from './api'

type ColumnInfo = {
  index: number
  header: string
  logical_hint: string | null
  confidence: number
  samples: string[]
  leading_zero_risk: boolean
  null_tokens_seen: string[]
}

type SheetInfo = {
  name: string
  header_row: number
  header_confidence: number
  row_count: number
  column_count: number
  columns: ColumnInfo[]
  warnings: string[]
}

type UploadResponse = {
  file: {
    file_id: string
    role: string
    original_name: string
    size: number
    created_at: number
  }
  inspection: {
    sheets: SheetInfo[]
    recommended_sheet: string | null
  }
}

const password = ref('')
const loading = ref(false)
const loggedIn = ref(Boolean(sessionStorage.getItem('material_matcher_token')))
const systemInfo = ref<any>(null)
const activeSection = ref('home')
const wizardStep = ref(0)
const sourceUpload = ref<UploadResponse | null>(null)
const targetUpload = ref<UploadResponse | null>(null)
const sourceSheet = ref('')
const targetSheet = ref('')
const sourceIdColumn = ref('')
const groupCodeColumn = ref('')
const mappings = ref<MappingConfig[]>([])
const strictness = ref(72)
const reviewEnabled = ref(true)
const topN = ref(5)
const dryResult = ref<any>(null)
const profileName = ref('')
const profileDescription = ref('')
const publishedProfile = ref<any>(null)
const profiles = ref<any[]>([])
const tasks = ref<any[]>([])
const tempFiles = ref<any[]>([])
const uploadBusy = ref<'source' | 'target' | null>(null)
const dryBusy = ref(false)
const publishBusy = ref(false)
const taskBusy = ref(false)

const navigation = [
  { id: 'home', label: '首页' },
  { id: 'tasks', label: '匹配任务' },
  { id: 'wizard', label: '配置向导' },
  { id: 'data', label: '数据与临时文件' },
  { id: 'system', label: '系统管理' },
]

const sectionTitle = computed(() => navigation.find((item) => item.id === activeSection.value)?.label ?? '首页')
const sourceSheetInfo = computed<SheetInfo | null>(() => {
  if (!sourceUpload.value) return null
  return sourceUpload.value.inspection.sheets.find((sheet) => sheet.name === sourceSheet.value) ?? null
})
const targetSheetInfo = computed<SheetInfo | null>(() => {
  if (!targetUpload.value) return null
  return targetUpload.value.inspection.sheets.find((sheet) => sheet.name === targetSheet.value) ?? null
})
const sourceColumns = computed(() => sourceSheetInfo.value?.columns ?? [])
const targetColumns = computed(() => targetSheetInfo.value?.columns ?? [])
const threshold = computed(() => Number((0.62 + strictness.value * 0.0036).toFixed(3)))
const reviewThreshold = computed(() => reviewEnabled.value ? Math.max(0.5, Number((threshold.value - 0.08).toFixed(3))) : null)
const weightTotal = computed(() => mappings.value.reduce((sum, item) => sum + Number(item.weight || 0), 0))

function humanField(hint: string | null) {
  const labels: Record<string, string> = {
    source_id: '物料编码',
    group_code: '集团码',
    material_name: '物料名称',
    model: '型号/牌号',
    specification: '规格/尺寸',
    manufacturer: '厂家/品牌',
    material_group: '物料组/分类',
    standard: '标准/规范',
    unit: '计量单位',
  }
  return hint ? labels[hint] ?? hint : '未识别'
}

function bytesText(size: number) {
  if (size < 1024) return `${size} B`
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`
  return `${(size / 1024 / 1024).toFixed(1)} MB`
}

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

async function refreshLists() {
  if (!loggedIn.value) return
  const [profileData, taskData, fileData] = await Promise.all([listProfiles(), listTasks(), listFiles()])
  profiles.value = profileData
  tasks.value = taskData
  tempFiles.value = fileData
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
    await Promise.all([refreshSystemInfo(), refreshLists()])
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

function resetWizard() {
  wizardStep.value = 0
  sourceUpload.value = null
  targetUpload.value = null
  sourceSheet.value = ''
  targetSheet.value = ''
  sourceIdColumn.value = ''
  groupCodeColumn.value = ''
  mappings.value = []
  dryResult.value = null
  publishedProfile.value = null
  profileName.value = ''
  profileDescription.value = ''
}

function chooseRecommendedSheet(upload: UploadResponse, role: 'source' | 'target') {
  const recommended = upload.inspection.recommended_sheet || upload.inspection.sheets[0]?.name || ''
  if (role === 'source') sourceSheet.value = recommended
  else targetSheet.value = recommended
}

function findHint(columns: ColumnInfo[], hint: string) {
  return columns.find((column) => column.logical_hint === hint)?.header ?? ''
}

function rebuildSuggestions() {
  if (!sourceSheetInfo.value || !targetSheetInfo.value) return
  sourceIdColumn.value ||= findHint(sourceColumns.value, 'source_id') || sourceColumns.value[0]?.header || ''
  groupCodeColumn.value ||= findHint(targetColumns.value, 'group_code') || targetColumns.value[0]?.header || ''
  const result: MappingConfig[] = []
  const used = new Set<string>()
  for (const source of sourceColumns.value) {
    if (!source.logical_hint || source.logical_hint === 'source_id' || source.logical_hint === 'group_code') continue
    const target = targetColumns.value.find((column) => column.logical_hint === source.logical_hint)
    if (!target) continue
    const key = `${source.header}::${target.header}`
    if (used.has(key)) continue
    used.add(key)
    const important = ['model', 'specification', 'standard'].includes(source.logical_hint)
    result.push({
      source_header: source.header,
      target_header: target.header,
      weight: important ? 80 : 55,
      method: source.logical_hint === 'standard' ? 'normalized_standard' : source.logical_hint === 'specification' ? 'numeric_text' : 'hybrid',
      name: humanField(source.logical_hint),
      critical: important,
    })
  }
  mappings.value = result.length ? result : [{ source_header: '', target_header: '', weight: 50, method: 'hybrid', name: '字段匹配', critical: false }]
}

async function handleUpload(event: Event, role: 'source' | 'target') {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  input.value = ''
  if (!file) return
  uploadBusy.value = role
  try {
    const data = await uploadExcel(file, role) as UploadResponse
    if (role === 'source') sourceUpload.value = data
    else targetUpload.value = data
    chooseRecommendedSheet(data, role)
    if (sourceUpload.value && targetUpload.value) rebuildSuggestions()
    ElMessage.success(`${role === 'source' ? '客户物料' : '集团码'}样表识别完成`)
    await refreshLists()
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail ?? '文件上传失败')
  } finally {
    uploadBusy.value = null
  }
}

function addMapping() {
  mappings.value.push({ source_header: '', target_header: '', weight: 50, method: 'hybrid', name: '自定义字段', critical: false })
}

function removeMapping(index: number) {
  mappings.value.splice(index, 1)
}

function validateMappings() {
  if (!sourceIdColumn.value || !groupCodeColumn.value) {
    ElMessage.warning('请确认客户物料编码列和集团码列')
    return false
  }
  if (!mappings.value.length || mappings.value.some((item) => !item.source_header || !item.target_header)) {
    ElMessage.warning('请完整配置至少一个字段对应关系')
    return false
  }
  return true
}

function buildConfig(): MatchConfig {
  const normalizedMappings = mappings.value.map((item) => ({
    ...item,
    weight: weightTotal.value > 0 ? item.weight / weightTotal.value : 1 / mappings.value.length,
  }))
  return {
    source_sheet: sourceSheet.value,
    source_header_row: sourceSheetInfo.value?.header_row ?? 1,
    target_sheet: targetSheet.value,
    target_header_row: targetSheetInfo.value?.header_row ?? 1,
    source_id_column: sourceIdColumn.value,
    group_code_column: groupCodeColumn.value,
    mappings: normalizedMappings,
    threshold: threshold.value,
    review_threshold: reviewThreshold.value,
    top_n: topN.value,
    candidate_limit: 400,
  }
}

function nextWizard() {
  if (wizardStep.value === 0 && !sourceUpload.value) return ElMessage.warning('请先上传客户物料样表')
  if (wizardStep.value === 1 && !targetUpload.value) return ElMessage.warning('请先上传集团码样表')
  if (wizardStep.value === 2 && !validateMappings()) return
  wizardStep.value = Math.min(5, wizardStep.value + 1)
}

async function runDry() {
  if (!sourceUpload.value || !targetUpload.value || !validateMappings()) return
  dryBusy.value = true
  try {
    dryResult.value = await dryRun(sourceUpload.value.file.file_id, targetUpload.value.file.file_id, buildConfig())
    wizardStep.value = 4
    ElMessage.success('试跑完成，请重点检查低分和人工复核样本')
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail ?? '试跑失败')
  } finally {
    dryBusy.value = false
  }
}

async function doPublish() {
  if (!profileName.value.trim()) {
    ElMessage.warning('请为匹配方案起一个名称')
    return
  }
  if (!dryResult.value) {
    ElMessage.warning('发布前必须先完成试跑')
    return
  }
  publishBusy.value = true
  try {
    publishedProfile.value = await publishProfile(profileName.value.trim(), profileDescription.value.trim(), buildConfig())
    wizardStep.value = 5
    await refreshLists()
    ElMessage.success('匹配方案已发布')
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail ?? '发布失败')
  } finally {
    publishBusy.value = false
  }
}

async function runFullTask() {
  if (!publishedProfile.value || !sourceUpload.value || !targetUpload.value) return
  taskBusy.value = true
  try {
    await createTask(publishedProfile.value.name, sourceUpload.value.file.file_id, targetUpload.value.file.file_id)
    activeSection.value = 'tasks'
    await refreshLists()
    ElMessage.success('正式匹配任务已创建')
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail ?? '任务创建失败')
  } finally {
    taskBusy.value = false
  }
}

async function doDownload(taskId: string) {
  try {
    await downloadTaskResult(taskId)
  } catch (error: any) {
    ElMessage.error(error?.response?.data?.detail ?? '结果下载失败')
  }
}

async function doCleanup(hours?: number) {
  try {
    const text = hours ? `确认清理 ${hours} 小时以前的临时上传文件？` : '确认清理全部临时上传文件？正式配置和结果不会被删除。'
    await ElMessageBox.confirm(text, '清理临时文件', { type: 'warning' })
    const result = await cleanupFiles(hours)
    await refreshLists()
    ElMessage.success(`已清理 ${result.deleted} 个文件，释放 ${bytesText(result.bytes_deleted)}`)
  } catch (error: any) {
    if (error === 'cancel' || error === 'close') return
    ElMessage.error(error?.response?.data?.detail ?? '清理失败')
  }
}

async function doDeleteFile(fileId: string) {
  await deleteFile(fileId)
  await refreshLists()
}

onMounted(async () => {
  await refreshSystemInfo()
  if (loggedIn.value) await refreshLists()
})
</script>

<template>
  <div v-if="!loggedIn" class="login-page">
    <div class="brand-panel">
      <div class="brand-mark">MM</div>
      <h1>MATERIAL_MATCHER</h1>
      <p>通用物料集团码批量匹配平台</p>
      <div class="brand-points">
        <span>零代码客户适配</span><span>百万级高速召回</span><span>可解释匹配结果</span>
      </div>
    </div>
    <el-card class="login-card" shadow="never">
      <div class="login-heading"><span class="eyebrow">管理员登录</span><h2>欢迎回来</h2><p>使用安装时生成的 admin 密码登录。</p></div>
      <el-form @submit.prevent="doLogin">
        <el-form-item label="账号"><el-input model-value="admin" disabled /></el-form-item>
        <el-form-item label="密码"><el-input v-model="password" type="password" show-password autocomplete="current-password" placeholder="请输入管理员密码" @keyup.enter="doLogin" /></el-form-item>
        <el-button type="primary" class="login-button" :loading="loading" @click="doLogin">登录</el-button>
      </el-form>
      <div class="password-tip">密码文件：<code>/etc/material_matcher/secret/admin_password.env</code></div>
    </el-card>
  </div>

  <div v-else class="app-shell">
    <aside class="sidebar">
      <div class="sidebar-brand"><div class="brand-mark small">MM</div><div><strong>MATERIAL_MATCHER</strong><span>物料匹配平台</span></div></div>
      <nav><button v-for="item in navigation" :key="item.id" class="nav-item" :class="{ active: activeSection === item.id }" @click="activeSection = item.id; item.id !== 'wizard' && refreshLists()">{{ item.label }}</button></nav>
      <div class="sidebar-footer"><div class="version">v{{ systemInfo?.version ?? '0.1.0' }}</div><button class="text-button" @click="logout">退出登录</button></div>
    </aside>

    <main class="main-content">
      <header class="topbar"><div><span class="eyebrow">MATERIAL_MATCHER</span><h1>{{ sectionTitle }}</h1></div><div class="health-pill"><span class="health-dot"></span> 服务正常</div></header>

      <template v-if="activeSection === 'home'">
        <section class="hero-card"><div><span class="eyebrow light">快速开始</span><h2>从 Excel 到集团码结果，不需要写配置文件</h2><p>系统自动识别字段并推荐对应关系，业务人员只需确认重要程度和匹配严格程度。</p></div><el-button size="large" type="primary" @click="activeSection = 'wizard'; resetWizard()">新建匹配方案</el-button></section>
        <section class="quick-grid">
          <button class="action-card primary-card" @click="activeSection = 'wizard'; resetWizard()"><span class="action-index">01</span><strong>配置向导</strong><p>上传两侧 Excel，自动识别、映射、试跑和发布。</p></button>
          <button class="action-card" @click="activeSection = 'tasks'; refreshLists()"><span class="action-index">02</span><strong>匹配任务</strong><p>查看运行状态，完成后下载正式结果和 TopN。</p></button>
          <button class="action-card" @click="activeSection = 'data'; refreshLists()"><span class="action-index">03</span><strong>临时文件</strong><p>查看上传缓存占用，并安全清理。</p></button>
          <button class="action-card" @click="activeSection = 'system'"><span class="action-index">04</span><strong>系统状态</strong><p>查看端口、路径、版本和插件能力。</p></button>
        </section>
        <section class="status-grid"><el-card shadow="never"><template #header><strong>产品状态</strong></template><div class="status-row"><span>已发布方案</span><strong>{{ profiles.length }}</strong></div><div class="status-row"><span>匹配任务</span><strong>{{ tasks.length }}</strong></div><div class="status-row"><span>临时文件</span><strong>{{ tempFiles.length }}</strong></div></el-card><el-card shadow="never"><template #header><strong>部署信息</strong></template><div class="status-row"><span>服务端口</span><strong>{{ systemInfo?.port ?? '-' }}</strong></div><div class="status-row"><span>数据目录</span><strong>{{ systemInfo?.data_dir ?? '-' }}</strong></div><div class="status-row"><span>版本</span><strong>{{ systemInfo?.version ?? '-' }}</strong></div></el-card></section>
      </template>

      <template v-else-if="activeSection === 'wizard'">
        <section class="page-card wizard-shell">
          <div class="wizard-header"><div><span class="eyebrow">新建配置方案</span><h2>业务配置向导</h2><p>普通模式只确认业务含义；YAML、Join、Rule Set 和插件参数由系统生成。</p></div><div class="wizard-actions"><el-tag type="success">向导模式</el-tag><el-button text @click="resetWizard">重新开始</el-button></div></div>
          <el-steps :active="wizardStep" finish-status="success" align-center><el-step title="客户物料" /><el-step title="集团码" /><el-step title="字段对应" /><el-step title="匹配策略" /><el-step title="试跑" /><el-step title="发布" /></el-steps>

          <div v-if="wizardStep === 0" class="wizard-stage">
            <div class="stage-copy"><h3>上传客户物料样表</h3><p>系统会自动识别表头、业务字段、空值和编码前导零风险。建议使用真实格式的小样表。</p></div>
            <label class="upload-box"><input type="file" accept=".xlsx,.xlsm" @change="handleUpload($event, 'source')" /><span class="upload-illustration">XLSX</span><strong>{{ sourceUpload?.file.original_name ?? '选择客户物料 Excel' }}</strong><span>{{ uploadBusy === 'source' ? '正在识别…' : sourceUpload ? `${sourceSheetInfo?.row_count ?? 0} 行 · ${sourceColumns.length} 列` : '点击选择文件' }}</span></label>
            <div v-if="sourceUpload" class="inspection-panel"><div class="panel-title"><strong>识别结果</strong><el-select v-model="sourceSheet" size="small" @change="sourceIdColumn = findHint(sourceColumns, 'source_id')"><el-option v-for="sheet in sourceUpload.inspection.sheets" :key="sheet.name" :label="sheet.name" :value="sheet.name" /></el-select></div><el-alert v-for="warning in sourceSheetInfo?.warnings ?? []" :key="warning" :title="warning" type="warning" :closable="false" show-icon /><el-table :data="sourceColumns" size="small" max-height="320"><el-table-column prop="header" label="原始列名" /><el-table-column label="系统理解"><template #default="scope">{{ humanField(scope.row.logical_hint) }}</template></el-table-column><el-table-column label="样例值"><template #default="scope"><span class="sample-text">{{ scope.row.samples.join(' · ') || '-' }}</span></template></el-table-column><el-table-column label="风险" width="120"><template #default="scope"><el-tag v-if="scope.row.leading_zero_risk" type="warning">前导零</el-tag><span v-else>-</span></template></el-table-column></el-table></div>
          </div>

          <div v-else-if="wizardStep === 1" class="wizard-stage">
            <div class="stage-copy"><h3>上传集团码基准表</h3><p>集团码侧可以与 SAP 完全不同格式，后续会按字段含义建立对应关系。</p></div>
            <label class="upload-box"><input type="file" accept=".xlsx,.xlsm" @change="handleUpload($event, 'target')" /><span class="upload-illustration target">CODE</span><strong>{{ targetUpload?.file.original_name ?? '选择集团码 Excel' }}</strong><span>{{ uploadBusy === 'target' ? '正在识别…' : targetUpload ? `${targetSheetInfo?.row_count ?? 0} 行 · ${targetColumns.length} 列` : '点击选择文件' }}</span></label>
            <div v-if="targetUpload" class="inspection-panel"><div class="panel-title"><strong>识别结果</strong><el-select v-model="targetSheet" size="small" @change="rebuildSuggestions"><el-option v-for="sheet in targetUpload.inspection.sheets" :key="sheet.name" :label="sheet.name" :value="sheet.name" /></el-select></div><el-table :data="targetColumns" size="small" max-height="320"><el-table-column prop="header" label="集团表列名" /><el-table-column label="系统理解"><template #default="scope">{{ humanField(scope.row.logical_hint) }}</template></el-table-column><el-table-column label="样例值"><template #default="scope"><span class="sample-text">{{ scope.row.samples.join(' · ') || '-' }}</span></template></el-table-column></el-table></div>
          </div>

          <div v-else-if="wizardStep === 2" class="wizard-stage wide-stage">
            <div class="stage-copy"><h3>确认字段对应关系</h3><p>系统已经按字段含义给出建议。只需要确认“客户这列”和“集团这列”表示同一业务含义。</p></div>
            <div class="identity-grid"><div><label>客户物料唯一标识</label><el-select v-model="sourceIdColumn" filterable><el-option v-for="col in sourceColumns" :key="col.header" :label="col.header" :value="col.header" /></el-select></div><div><label>集团码结果列</label><el-select v-model="groupCodeColumn" filterable><el-option v-for="col in targetColumns" :key="col.header" :label="col.header" :value="col.header" /></el-select></div></div>
            <div class="mapping-list"><div v-for="(mapping, index) in mappings" :key="index" class="mapping-row"><div class="mapping-field"><span>客户字段</span><el-select v-model="mapping.source_header" filterable><el-option v-for="col in sourceColumns" :key="col.header" :label="col.header" :value="col.header" /></el-select></div><div class="mapping-arrow">→</div><div class="mapping-field"><span>集团字段</span><el-select v-model="mapping.target_header" filterable><el-option v-for="col in targetColumns" :key="col.header" :label="col.header" :value="col.header" /></el-select></div><div class="mapping-method"><span>比较方式</span><el-select v-model="mapping.method"><el-option label="智能综合" value="hybrid" /><el-option label="标准号" value="normalized_standard" /><el-option label="规格数值" value="numeric_text" /><el-option label="完全一致" value="normalized_exact" /><el-option label="文字相似" value="fuzzy" /></el-select></div><el-button text type="danger" @click="removeMapping(index)">删除</el-button></div></div><el-button @click="addMapping">+ 添加字段对应</el-button>
          </div>

          <div v-else-if="wizardStep === 3" class="wizard-stage wide-stage">
            <div class="stage-copy"><h3>调整业务重要程度与匹配严格程度</h3><p>不需要手工计算权重。拖动“重要程度”即可，系统会自动归一化。</p></div>
            <div class="strategy-grid"><el-card shadow="never"><template #header><strong>字段重要程度</strong></template><div v-for="mapping in mappings" :key="`${mapping.source_header}-${mapping.target_header}`" class="weight-row"><div><strong>{{ mapping.name || mapping.source_header }}</strong><span>{{ mapping.source_header }} → {{ mapping.target_header }}</span></div><el-slider v-model="mapping.weight" :min="5" :max="100" :step="5" show-input /><el-checkbox v-model="mapping.critical">关键字段</el-checkbox></div></el-card><el-card shadow="never"><template #header><strong>匹配严格程度</strong></template><div class="strictness-copy"><strong>{{ strictness < 40 ? '偏重覆盖率' : strictness > 75 ? '偏重准确率' : '平衡模式' }}</strong><span>内部成功阈值 {{ threshold }}</span></div><el-slider v-model="strictness" :min="0" :max="100" :marks="{0:'更多匹配',50:'平衡',100:'更少误配'}" /><el-switch v-model="reviewEnabled" active-text="启用人工复核区间" /><div v-if="reviewEnabled" class="policy-note">{{ reviewThreshold }} ～ {{ threshold }} 的结果进入“建议复核”，不会直接写入正式集团码。</div><div class="topn-row"><span>最相似候选数量</span><el-input-number v-model="topN" :min="1" :max="20" /></div></el-card></div>
          </div>

          <div v-else-if="wizardStep === 4" class="wizard-stage wide-stage">
            <div class="stage-copy"><h3>试跑并确认效果</h3><p>发布前必须使用真实样本试跑。只有超过成功阈值的记录才会正式写入集团码。</p></div>
            <div v-if="!dryResult" class="dry-empty"><span class="empty-icon">▶</span><h3>准备试跑 30 条客户物料</h3><p>集团侧最多读取 10000 条样本用于快速验证。</p><el-button type="primary" size="large" :loading="dryBusy" @click="runDry">开始试跑</el-button></div>
            <template v-else><div class="metric-grid"><div class="metric"><span>样本数</span><strong>{{ dryResult.summary.source_rows }}</strong></div><div class="metric success"><span>自动匹配</span><strong>{{ dryResult.summary.matched }}</strong></div><div class="metric review"><span>建议复核</span><strong>{{ dryResult.summary.review }}</strong></div><div class="metric"><span>未匹配</span><strong>{{ dryResult.summary.unmatched }}</strong></div></div><el-table :data="dryResult.rows" stripe max-height="360"><el-table-column prop="source_id" label="客户物料" /><el-table-column prop="status" label="判定"><template #default="scope"><el-tag :type="scope.row.status === 'MATCHED' ? 'success' : scope.row.status === 'REVIEW' ? 'warning' : 'info'">{{ scope.row.status }}</el-tag></template></el-table-column><el-table-column prop="matched_group_code" label="正式集团码" /><el-table-column prop="score" label="相似度" /><el-table-column label="Top 候选"><template #default="scope"><span class="sample-text">{{ scope.row.candidates.map((c:any) => `${c.group_code}:${c.score}`).join(' / ') }}</span></template></el-table-column></el-table><div class="dry-actions"><el-button @click="dryResult = null">调整后重跑</el-button><el-button type="primary" @click="wizardStep = 5">效果可以，继续发布</el-button></div></template>
          </div>

          <div v-else class="wizard-stage publish-stage">
            <div class="stage-copy"><h3>发布匹配方案</h3><p>发布后该方案可以反复用于新的客户物料文件，无需重新配置。</p></div>
            <el-form label-position="top" class="publish-form"><el-form-item label="方案名称"><el-input v-model="profileName" placeholder="例如：13所-元器件集团码匹配-v1" /></el-form-item><el-form-item label="说明（可选）"><el-input v-model="profileDescription" type="textarea" :rows="3" placeholder="说明适用范围、物料类型或数据版本" /></el-form-item><el-alert v-if="publishedProfile" title="方案已发布，可以直接创建正式匹配任务。" type="success" :closable="false" show-icon /><div class="publish-buttons"><el-button v-if="!publishedProfile" type="primary" size="large" :loading="publishBusy" @click="doPublish">发布方案</el-button><template v-else><el-button @click="resetWizard">配置下一套方案</el-button><el-button type="primary" size="large" :loading="taskBusy" @click="runFullTask">立即正式匹配当前文件</el-button></template></div></el-form>
          </div>

          <div v-if="wizardStep < 4" class="wizard-footer"><el-button :disabled="wizardStep === 0" @click="wizardStep--">上一步</el-button><el-button v-if="wizardStep < 3" type="primary" @click="nextWizard">下一步</el-button><el-button v-else type="primary" :loading="dryBusy" @click="runDry">保存设置并试跑</el-button></div>
        </section>
      </template>

      <template v-else-if="activeSection === 'tasks'">
        <section class="page-card"><div class="page-heading"><div><h2>匹配任务</h2><p>任务完成后可下载“匹配结果 + TopN”Excel。</p></div><el-button @click="refreshLists">刷新</el-button></div><el-empty v-if="!tasks.length" description="暂无匹配任务" /><el-table v-else :data="tasks" stripe><el-table-column prop="task_id" label="任务号" width="150" /><el-table-column prop="profile_name" label="匹配方案" /><el-table-column prop="status" label="状态" width="120"><template #default="scope"><el-tag :type="scope.row.status === 'COMPLETED' ? 'success' : scope.row.status === 'FAILED' ? 'danger' : 'warning'">{{ scope.row.status }}</el-tag></template></el-table-column><el-table-column label="结果"><template #default="scope"><span v-if="scope.row.summary">匹配 {{ scope.row.summary.matched }} / {{ scope.row.summary.source_rows }}</span><span v-else>{{ scope.row.error || '-' }}</span></template></el-table-column><el-table-column label="操作" width="120"><template #default="scope"><el-button v-if="scope.row.status === 'COMPLETED'" link type="primary" @click="doDownload(scope.row.task_id)">下载结果</el-button></template></el-table-column></el-table></section>
      </template>

      <template v-else-if="activeSection === 'data'">
        <section class="page-card"><div class="page-heading"><div><h2>临时文件管理</h2><p>这里只管理上传缓存，不会删除正式配置、正式结果和索引。</p></div><div><el-button @click="doCleanup(72)">清理 3 天前</el-button><el-button type="danger" plain @click="doCleanup()">清理全部缓存</el-button></div></div><el-empty v-if="!tempFiles.length" description="暂无临时文件" /><el-table v-else :data="tempFiles" stripe><el-table-column prop="original_name" label="文件" /><el-table-column prop="role" label="用途" width="120" /><el-table-column label="大小" width="120"><template #default="scope">{{ bytesText(scope.row.size) }}</template></el-table-column><el-table-column label="操作" width="100"><template #default="scope"><el-button link type="danger" @click="doDeleteFile(scope.row.file_id)">删除</el-button></template></el-table-column></el-table></section>
      </template>

      <template v-else-if="activeSection === 'system'">
        <section class="status-grid"><el-card shadow="never"><template #header><strong>服务信息</strong></template><div class="status-row"><span>版本</span><strong>{{ systemInfo?.version ?? '-' }}</strong></div><div class="status-row"><span>端口</span><strong>{{ systemInfo?.port ?? '-' }}</strong></div><div class="status-row"><span>配置目录</span><strong>{{ systemInfo?.config_dir ?? '-' }}</strong></div><div class="status-row"><span>数据目录</span><strong>{{ systemInfo?.data_dir ?? '-' }}</strong></div><div class="status-row"><span>日志目录</span><strong>{{ systemInfo?.log_dir ?? '-' }}</strong></div></el-card><el-card shadow="never"><template #header><strong>已发布匹配方案</strong></template><el-empty v-if="!profiles.length" description="暂无方案" /><div v-for="profile in profiles" :key="profile.name" class="profile-item"><div><strong>{{ profile.name }}</strong><span>{{ profile.version }}</span></div><el-tag type="success">已发布</el-tag></div></el-card></section>
      </template>
    </main>
  </div>
</template>
