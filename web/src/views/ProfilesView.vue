<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { api } from '../api'

type CombineMode = 'concat' | 'coalesce' | 'best_of'
type DictionaryMode = 'exact' | 'replace'
type Rule = {
  id: string
  source_fields: string[]
  target_fields: string[]
  source_combine: CombineMode
  target_combine: CombineMode
  matcher: string
  weight: number
  critical: boolean
  source_separator: string
  target_separator: string
  source_pipeline: any[]
  target_pipeline: any[]
  source_dictionary_ref: string
  target_dictionary_ref: string
  source_dictionary_mode: DictionaryMode
  target_dictionary_mode: DictionaryMode
  matcher_options: Record<string, any>
}
type MappingRow = { source: string; targets: string }
type ProfileRow = { profile_id: string; name: string; latest_published_version?: number | null; has_draft: number; updated_at?: string }
type VersionRow = { version_no: number; status: string; sha256: string; created_at: string; document: any }
type DictionaryRow = { dictionary_id: string; name: string; latest_version: number }
type DictionaryChoice = { value: string; label: string }

const router = useRouter()
const rows = ref<ProfileRow[]>([])
const dictionaries = ref<DictionaryRow[]>([])
const loading = ref(false)
const editorVisible = ref(false)
const historyVisible = ref(false)
const advancedRuleVisible = ref(false)
const advancedRuleIndex = ref(-1)
const activeProfile = ref<any>(null)
const versions = ref<VersionRow[]>([])
const saving = ref(false)
const startingProfileId = ref('')
const baseDocument = ref<any>({})
const form = reactive({
  name: '',
  source_id_column: '物料号',
  success_threshold: 88,
  review_threshold: 75,
  top_n: 5,
  scope_mode: 'GLOBAL',
  scope_source_field: '',
  scope_target_field: '',
  scope_mapping_rows: [] as MappingRow[],
  retrieval_mode: 'auto',
  rules: [] as Rule[],
})

const totalWeight = computed(() => form.rules.reduce((sum, rule) => sum + Number(rule.weight || 0), 0))
const normalized = (weight: number): string => totalWeight.value > 0 ? `${(weight / totalWeight.value * 100).toFixed(1)}%` : '0%'
const advancedRule = computed(() => advancedRuleIndex.value >= 0 ? form.rules[advancedRuleIndex.value] : null)
const dictionaryChoices = computed<DictionaryChoice[]>(() => {
  const choices = dictionaries.value.map(item => ({ value: `${item.dictionary_id}:${item.latest_version}`, label: `${item.name} · v${item.latest_version}` }))
  const known = new Set(choices.map(item => item.value))
  for (const rule of form.rules) {
    for (const value of [rule.source_dictionary_ref, rule.target_dictionary_ref]) {
      if (!value || value === '__inline__' || known.has(value)) continue
      choices.push({ value, label: `冻结历史字典 · ${value.split(':')[0].slice(0, 10)} · v${value.split(':')[1]}` })
      known.add(value)
    }
  }
  return choices
})

function deepCopy<T>(value: T): T { return JSON.parse(JSON.stringify(value)) as T }
function dictionaryFromPipeline(pipeline: any[]): { ref: string; mode: DictionaryMode } {
  const step = (pipeline ?? []).find(item => item?.op === 'dictionary_map')
  if (!step) return { ref: '', mode: 'exact' }
  const id = step.options?.dictionary_id
  const version = step.options?.version_no
  if (id && version != null) return { ref: `${id}:${Number(version)}`, mode: step.options?.mode === 'replace' ? 'replace' : 'exact' }
  if (step.options?.mapping) return { ref: '__inline__', mode: step.options?.mode === 'replace' ? 'replace' : 'exact' }
  return { ref: '', mode: 'exact' }
}
function pipelineWithDictionary(pipeline: any[], reference: string, mode: DictionaryMode): any[] {
  const original = deepCopy(pipeline ?? [])
  if (reference === '__inline__') return original
  const retained = original.filter(item => item?.op !== 'dictionary_map')
  if (!reference) return retained
  const [dictionaryId, versionText] = reference.split(':')
  retained.push({
    op: 'dictionary_map',
    options: { dictionary_id: dictionaryId, version_no: Number(versionText), mode, on_missing: 'keep' },
  })
  return retained
}
function blankRule(): Rule {
  return {
    id: `rule_${Date.now()}_${Math.random().toString(16).slice(2, 6)}`,
    source_fields: [],
    target_fields: [],
    source_combine: 'concat',
    target_combine: 'concat',
    matcher: 'fuzzy',
    weight: 50,
    critical: false,
    source_separator: ' ',
    target_separator: ' ',
    source_pipeline: [],
    target_pipeline: [],
    source_dictionary_ref: '',
    target_dictionary_ref: '',
    source_dictionary_mode: 'exact',
    target_dictionary_mode: 'exact',
    matcher_options: {},
  }
}
function resetForm(): void {
  baseDocument.value = {}
  Object.assign(form, {
    name: '', source_id_column: '物料号', success_threshold: 88, review_threshold: 75, top_n: 5,
    scope_mode: 'GLOBAL', scope_source_field: '', scope_target_field: '', scope_mapping_rows: [],
    retrieval_mode: 'auto', rules: [blankRule()],
  })
}
function scopeMapping(): Record<string, string[]> {
  const mapping: Record<string, string[]> = {}
  for (const row of form.scope_mapping_rows) {
    const source = row.source.trim()
    if (!source) continue
    mapping[source] = row.targets.split(/[,，]/).map(value => value.trim()).filter(Boolean)
  }
  return mapping
}
function documentFromForm(): any {
  const base = deepCopy(baseDocument.value ?? {})
  const baseRules = new Map<string, any>((base.rules ?? []).map((rule: any) => [String(rule.id), rule]))
  return {
    ...base,
    source_id_column: form.source_id_column.trim(),
    scope_mode: form.scope_mode,
    scope: {
      ...(base.scope ?? {}),
      source_field: form.scope_mode === 'GLOBAL' ? null : form.scope_source_field.trim(),
      target_field: form.scope_mode === 'GLOBAL' ? null : form.scope_target_field.trim(),
      mapping: form.scope_mode === 'MAPPED' ? scopeMapping() : {},
    },
    rules: form.rules.map(rule => {
      const previous = baseRules.get(rule.id) ?? {}
      return {
        ...previous,
        id: rule.id,
        source: {
          ...(previous.source ?? {}),
          fields: [...rule.source_fields],
          combine: rule.source_combine,
          separator: rule.source_separator,
          pipeline: pipelineWithDictionary(rule.source_pipeline, rule.source_dictionary_ref, rule.source_dictionary_mode),
        },
        target: {
          ...(previous.target ?? {}),
          fields: [...rule.target_fields],
          combine: rule.target_combine,
          separator: rule.target_separator,
          pipeline: pipelineWithDictionary(rule.target_pipeline, rule.target_dictionary_ref, rule.target_dictionary_mode),
        },
        matcher: rule.matcher,
        weight: Number(rule.weight),
        critical: rule.critical,
        matcher_options: deepCopy(rule.matcher_options),
      }
    }),
    decision: {
      ...(base.decision ?? {}),
      success_threshold: Number(form.success_threshold),
      review_enabled: true,
      review_threshold: Number(form.review_threshold),
      top_n: Number(form.top_n),
    },
    retrieval: {
      ...(base.retrieval ?? {}),
      mode: form.retrieval_mode,
      provider: base.retrieval?.provider ?? 'onnx_local',
      model_id: base.retrieval?.model_id ?? 'BAAI/bge-base-zh-v1.5',
      dimensions: base.retrieval?.dimensions ?? 768,
      max_length: base.retrieval?.max_length ?? 256,
      precision: base.retrieval?.precision ?? 'int8',
      retrieval_top_k: base.retrieval?.retrieval_top_k ?? 200,
      oversample: base.retrieval?.oversample ?? 4,
    },
    advanced: deepCopy(base.advanced ?? {}),
  }
}
function loadDocument(document: any): void {
  baseDocument.value = deepCopy(document ?? {})
  form.source_id_column = document?.source_id_column ?? '物料号'
  form.success_threshold = document?.decision?.success_threshold ?? 88
  form.review_threshold = document?.decision?.review_threshold ?? 75
  form.top_n = document?.decision?.top_n ?? 5
  form.scope_mode = document?.scope_mode ?? 'GLOBAL'
  form.scope_source_field = document?.scope?.source_field ?? ''
  form.scope_target_field = document?.scope?.target_field ?? ''
  form.scope_mapping_rows = Object.entries(document?.scope?.mapping ?? {}).map(([source, targets]) => ({ source, targets: (targets as string[]).join(',') }))
  form.retrieval_mode = document?.retrieval?.mode ?? 'auto'
  form.rules = (document?.rules ?? []).map((rule: any) => {
    const sourceDictionary = dictionaryFromPipeline(rule.source?.pipeline ?? [])
    const targetDictionary = dictionaryFromPipeline(rule.target?.pipeline ?? [])
    return {
      id: rule.id,
      source_fields: [...(rule.source?.fields ?? [])],
      target_fields: [...(rule.target?.fields ?? [])],
      source_combine: rule.source?.combine ?? 'concat',
      target_combine: rule.target?.combine ?? 'concat',
      matcher: rule.matcher ?? 'fuzzy',
      weight: rule.weight ?? 0,
      critical: Boolean(rule.critical),
      source_separator: rule.source?.separator ?? ' ',
      target_separator: rule.target?.separator ?? ' ',
      source_pipeline: deepCopy(rule.source?.pipeline ?? []),
      target_pipeline: deepCopy(rule.target?.pipeline ?? []),
      source_dictionary_ref: sourceDictionary.ref,
      target_dictionary_ref: targetDictionary.ref,
      source_dictionary_mode: sourceDictionary.mode,
      target_dictionary_mode: targetDictionary.mode,
      matcher_options: deepCopy(rule.matcher_options ?? {}),
    }
  })
  if (!form.rules.length) form.rules = [blankRule()]
}
function ensureNumericTolerance(rule: Rule): void {
  if (rule.matcher !== 'numeric') return
  if (!rule.matcher_options.tolerance || typeof rule.matcher_options.tolerance !== 'object') {
    rule.matcher_options.tolerance = { mode: 'absolute', value: 0 }
  }
}
function openAdvancedRule(index: number): void {
  advancedRuleIndex.value = index
  const rule = form.rules[index]
  if (rule) ensureNumericTolerance(rule)
  advancedRuleVisible.value = true
}
async function refresh(): Promise<void> {
  loading.value = true
  try {
    const [profileResponse, dictionaryResponse] = await Promise.all([api.get('/profiles'), api.get('/dictionaries')])
    rows.value = profileResponse.data ?? []
    dictionaries.value = dictionaryResponse.data ?? []
  } catch (error) { ElMessage.error((error as Error).message) }
  finally { loading.value = false }
}
async function createProfile(): Promise<void> {
  resetForm(); activeProfile.value = null; editorVisible.value = true
}
async function editProfile(row: ProfileRow): Promise<void> {
  try {
    const response = await api.get(`/profiles/${row.profile_id}`)
    activeProfile.value = response.data
    form.name = response.data.name
    loadDocument(response.data.draft?.document ?? response.data.latest_published?.document ?? {})
    editorVisible.value = true
  } catch (error) { ElMessage.error((error as Error).message) }
}
async function saveDraft(): Promise<boolean> {
  saving.value = true
  try {
    const document = documentFromForm()
    if (!activeProfile.value) {
      const response = await api.post('/profiles', { name: form.name, document })
      activeProfile.value = response.data
    } else {
      await api.put(`/profiles/${activeProfile.value.profile_id}/draft`, document)
    }
    baseDocument.value = deepCopy(document)
    ElMessage.success('草稿已保存')
    await refresh()
    return true
  } catch (error) {
    ElMessage.error((error as Error).message)
    return false
  } finally { saving.value = false }
}
async function validateDraft(): Promise<void> {
  if (!await saveDraft() || !activeProfile.value) return
  try { await api.post(`/profiles/${activeProfile.value.profile_id}/validate`); ElMessage.success('方案校验通过') }
  catch (error) { ElMessage.error((error as Error).message) }
}
async function publish(): Promise<void> {
  if (!await saveDraft() || !activeProfile.value) return
  try {
    const result = (await api.post(`/profiles/${activeProfile.value.profile_id}/publish`)).data
    ElMessage.success(`已发布 v${result.version_no}`)
    editorVisible.value = false
    await refresh()
  } catch (error) { ElMessage.error((error as Error).message) }
}
async function showHistory(row: ProfileRow): Promise<void> {
  activeProfile.value = row
  versions.value = (await api.get(`/profiles/${row.profile_id}/versions`)).data ?? []
  historyVisible.value = true
}
async function rollback(version: VersionRow): Promise<void> {
  if (!activeProfile.value) return
  try {
    await ElMessageBox.confirm(`将 v${version.version_no} 复制为新的发布版本，不会覆盖历史版本。`, '确认回滚')
    const result = (await api.post(`/profiles/${activeProfile.value.profile_id}/rollback/${version.version_no}`)).data
    ElMessage.success(`已生成新版本 v${result.version_no}`)
    versions.value = (await api.get(`/profiles/${activeProfile.value.profile_id}/versions`)).data ?? []
    await refresh()
  } catch (error) {
    if (error instanceof Error) ElMessage.error(error.message)
  }
}
async function startTaskFromProfile(row: ProfileRow): Promise<void> {
  if (!row.latest_published_version) {
    ElMessage.warning('请先发布至少一个方案版本')
    return
  }
  startingProfileId.value = row.profile_id
  try {
    const allVersions = (await api.get(`/profiles/${row.profile_id}/versions`)).data as VersionRow[]
    const versionNo = Number(row.latest_published_version)
    const published = allVersions.find(item => item.status === 'PUBLISHED' && Number(item.version_no) === versionNo)
    if (!published) throw new Error(`未找到已发布版本 v${versionNo}`)
    const document = deepCopy(published.document ?? {})
    document.advanced = {
      ...(document.advanced ?? {}),
      template_source: { profile_id: row.profile_id, version_no: versionNo },
    }
    const draft = (await api.post('/task-drafts', { name: `${row.name}-匹配任务` })).data
    await api.put(`/task-drafts/${draft.draft_id}/rules`, document)
    ElMessage.success(`已按 ${row.name} v${versionNo} 创建任务草稿`)
    await router.push({ path: '/tasks/new', query: { draft: draft.draft_id } })
  } catch (error) { ElMessage.error((error as Error).message) }
  finally { startingProfileId.value = '' }
}
onMounted(refresh)
</script>

<template>
  <div>
    <div class="toolbar">
      <div><h2>匹配方案</h2><p>把成熟规则保存为可复用模板。方案是可选能力，不影响直接新建匹配任务。</p></div>
      <el-button type="primary" @click="createProfile">新建匹配方案</el-button>
    </div>
    <div class="panel" v-loading="loading">
      <el-table :data="rows" empty-text="尚无匹配方案">
        <el-table-column prop="name" label="方案名称" min-width="200" />
        <el-table-column label="最新发布版本" width="140"><template #default="scope">{{ scope.row.latest_published_version ? `v${scope.row.latest_published_version}` : '未发布' }}</template></el-table-column>
        <el-table-column label="草稿" width="100"><template #default="scope"><el-tag :type="scope.row.has_draft ? 'warning' : 'info'">{{ scope.row.has_draft ? '有草稿' : '无' }}</el-tag></template></el-table-column>
        <el-table-column prop="updated_at" label="更新时间" min-width="190" />
        <el-table-column label="操作" min-width="300"><template #default="scope"><el-button link type="primary" @click="editProfile(scope.row)">编辑</el-button><el-button link @click="showHistory(scope.row)">版本</el-button><el-button link type="success" :disabled="!scope.row.latest_published_version" :loading="startingProfileId===scope.row.profile_id" @click="startTaskFromProfile(scope.row)">用此方案新建任务</el-button></template></el-table-column>
      </el-table>
    </div>

    <el-dialog v-model="editorVisible" :title="activeProfile ? `编辑方案：${form.name}` : '新建匹配方案'" width="1180px" destroy-on-close>
      <el-form label-width="120px">
        <el-form-item label="方案名称"><el-input v-model="form.name" :disabled="Boolean(activeProfile)" /></el-form-item>
        <el-form-item label="客户物料标识"><el-input v-model="form.source_id_column" placeholder="例如：物料号" /></el-form-item>
        <el-form-item label="匹配范围">
          <el-radio-group v-model="form.scope_mode"><el-radio-button value="GLOBAL">全局</el-radio-button><el-radio-button value="STRICT">同分类</el-radio-button><el-radio-button value="MAPPED">分类映射</el-radio-button></el-radio-group>
        </el-form-item>
        <el-form-item v-if="form.scope_mode!=='GLOBAL'" label="分类字段"><div class="inline"><el-input v-model="form.scope_source_field" placeholder="客户分类字段"/><el-input v-model="form.scope_target_field" placeholder="集团分类字段"/></div></el-form-item>
        <el-form-item v-if="form.scope_mode==='MAPPED'" label="分类映射">
          <div class="mapping-list">
            <div v-for="(row,index) in form.scope_mapping_rows" :key="index" class="mapping-row"><el-input v-model="row.source" placeholder="客户分类"/><span>→</span><el-input v-model="row.targets" placeholder="集团分类，逗号分隔"/><el-button link type="danger" @click="form.scope_mapping_rows.splice(index,1)">删除</el-button></div>
            <el-button link @click="form.scope_mapping_rows.push({source:'',targets:''})">+ 添加分类映射</el-button>
          </div>
        </el-form-item>
        <el-form-item label="检索方式"><el-select v-model="form.retrieval_mode" style="width:220px"><el-option label="自动选择" value="auto"/><el-option label="扫描" value="scan"/><el-option label="向量" value="vector"/></el-select></el-form-item>
        <el-form-item label="判定阈值"><div class="inline"><span>自动成功</span><el-input-number v-model="form.success_threshold" :min="0" :max="100"/><span>人工复核下限</span><el-input-number v-model="form.review_threshold" :min="0" :max="100"/><span>TopN</span><el-input-number v-model="form.top_n" :min="1" :max="50"/></div></el-form-item>
      </el-form>
      <div class="section-head"><h3>字段规则</h3><span>总权重 {{ totalWeight }}（运行时归一化）</span></div>
      <el-alert title="字典、数值容差等高级处理必须显式配置；编辑常用字段时会保留其它 pipeline、matcher_options、retrieval 与 advanced 配置。" type="info" :closable="false" style="margin-bottom:12px" />
      <el-table :data="form.rules" size="small">
        <el-table-column label="客户字段" min-width="210"><template #default="scope"><el-select v-model="scope.row.source_fields" multiple filterable allow-create default-first-option placeholder="输入字段并回车" style="width:100%"/></template></el-table-column>
        <el-table-column label="客户组合" width="120"><template #default="scope"><el-select v-model="scope.row.source_combine"><el-option label="拼接" value="concat"/><el-option label="首个有效" value="coalesce"/><el-option label="最高分" value="best_of"/></el-select></template></el-table-column>
        <el-table-column label="集团字段" min-width="210"><template #default="scope"><el-select v-model="scope.row.target_fields" multiple filterable allow-create default-first-option placeholder="输入字段并回车" style="width:100%"/></template></el-table-column>
        <el-table-column label="集团组合" width="120"><template #default="scope"><el-select v-model="scope.row.target_combine"><el-option label="拼接" value="concat"/><el-option label="首个有效" value="coalesce"/><el-option label="最高分" value="best_of"/></el-select></template></el-table-column>
        <el-table-column label="匹配方式" width="125"><template #default="scope"><el-select v-model="scope.row.matcher" @change="ensureNumericTolerance(scope.row)"><el-option label="精确" value="exact"/><el-option label="包含" value="contains"/><el-option label="模糊" value="fuzzy"/><el-option label="混合" value="hybrid"/><el-option label="语义" value="semantic"/><el-option label="数值" value="numeric"/></el-select></template></el-table-column>
        <el-table-column label="权重" width="120"><template #default="scope"><el-input-number v-model="scope.row.weight" :min="0" :max="100" controls-position="right" style="width:100px"/></template></el-table-column>
        <el-table-column label="占比" width="80"><template #default="scope">{{ normalized(scope.row.weight) }}</template></el-table-column>
        <el-table-column label="关键" width="70"><template #default="scope"><el-switch v-model="scope.row.critical" /></template></el-table-column>
        <el-table-column label="高级" width="80"><template #default="scope"><el-button link type="primary" @click="openAdvancedRule(scope.$index)">配置</el-button></template></el-table-column>
        <el-table-column label="操作" width="70"><template #default="scope"><el-button link type="danger" @click="form.rules.splice(scope.$index,1)">删除</el-button></template></el-table-column>
      </el-table>
      <el-button class="add-rule" @click="form.rules.push(blankRule())">添加字段规则</el-button>
      <template #footer><el-button @click="editorVisible=false">关闭</el-button><el-button :loading="saving" @click="saveDraft">保存草稿</el-button><el-button @click="validateDraft">校验</el-button><el-button type="primary" @click="publish">发布新版本</el-button></template>
    </el-dialog>

    <el-dialog v-model="advancedRuleVisible" title="字段规则高级处理" width="760px">
      <template v-if="advancedRule">
        <el-alert title="不选择字典时不会执行任何同义词/规范值替换。字典引用会在发布时冻结版本、SHA 和映射内容。" type="info" :closable="false" />
        <el-form label-width="130px" style="margin-top:16px">
          <el-form-item label="客户字段字典">
            <div class="advanced-row"><el-select v-model="advancedRule.source_dictionary_ref" clearable placeholder="不使用字典"><el-option v-if="advancedRule.source_dictionary_ref==='__inline__'" label="内嵌历史字典（保留）" value="__inline__"/><el-option v-for="item in dictionaryChoices" :key="item.value" :label="item.label" :value="item.value"/></el-select><el-select v-model="advancedRule.source_dictionary_mode"><el-option label="整值映射 exact" value="exact"/><el-option label="文本替换 replace" value="replace"/></el-select></div>
          </el-form-item>
          <el-form-item label="集团字段字典">
            <div class="advanced-row"><el-select v-model="advancedRule.target_dictionary_ref" clearable placeholder="不使用字典"><el-option v-if="advancedRule.target_dictionary_ref==='__inline__'" label="内嵌历史字典（保留）" value="__inline__"/><el-option v-for="item in dictionaryChoices" :key="item.value" :label="item.label" :value="item.value"/></el-select><el-select v-model="advancedRule.target_dictionary_mode"><el-option label="整值映射 exact" value="exact"/><el-option label="文本替换 replace" value="replace"/></el-select></div>
          </el-form-item>
          <template v-if="advancedRule.matcher==='numeric'">
            <el-divider>数值容差</el-divider>
            <el-form-item label="模式"><el-select v-model="advancedRule.matcher_options.tolerance.mode"><el-option label="完全相等" value="exact"/><el-option label="绝对误差" value="absolute"/><el-option label="相对误差" value="relative"/><el-option label="差值区间" value="range"/></el-select></el-form-item>
            <el-form-item v-if="['absolute','relative'].includes(advancedRule.matcher_options.tolerance.mode)" label="容差值"><el-input-number v-model="advancedRule.matcher_options.tolerance.value" :min="0" :step="advancedRule.matcher_options.tolerance.mode==='relative'?0.01:1" /></el-form-item>
            <el-form-item v-if="advancedRule.matcher_options.tolerance.mode==='range'" label="差值范围"><div class="inline"><el-input-number v-model="advancedRule.matcher_options.tolerance.min_delta"/><span>～</span><el-input-number v-model="advancedRule.matcher_options.tolerance.max_delta"/></div></el-form-item>
          </template>
        </el-form>
      </template>
      <template #footer><el-button type="primary" @click="advancedRuleVisible=false">完成</el-button></template>
    </el-dialog>

    <el-dialog v-model="historyVisible" title="方案版本历史" width="820px">
      <el-alert title="已发布版本不可修改；回滚会复制旧版本并产生一个新的发布版本。" type="info" :closable="false" />
      <el-table :data="versions" size="small" style="margin-top:14px">
        <el-table-column label="版本" width="100"><template #default="scope">{{ scope.row.status==='DRAFT' ? '草稿' : `v${scope.row.version_no}` }}</template></el-table-column>
        <el-table-column prop="status" label="状态" width="120" />
        <el-table-column prop="sha256" label="配置 SHA" min-width="260" show-overflow-tooltip />
        <el-table-column prop="created_at" label="时间" min-width="180" />
        <el-table-column label="操作" width="100"><template #default="scope"><el-button v-if="scope.row.status==='PUBLISHED'" link type="primary" @click="rollback(scope.row)">回滚到此版</el-button></template></el-table-column>
      </el-table>
    </el-dialog>
  </div>
</template>

<style scoped>
.inline{display:flex;align-items:center;gap:10px;width:100%}.inline .el-input{max-width:260px}.section-head{display:flex;justify-content:space-between;align-items:center}.add-rule{margin-top:12px}.mapping-list{display:flex;flex-direction:column;gap:8px;width:100%}.mapping-row{display:grid;grid-template-columns:minmax(160px,1fr) auto minmax(220px,1.4fr) auto;gap:8px;align-items:center}.advanced-row{display:grid;grid-template-columns:minmax(300px,1fr) 190px;gap:10px;width:100%}
</style>
