import { api } from './api'

export type FileRecord = { file_id: string; original_name: string; sha256?: string; role?: string }
export type ColumnInfo = { header: string; business_hint?: string | null; samples?: string[] }
export type CompositeChildRef = { profile_id: string; version_no: number }
export type CompositeChildView = CompositeChildRef & {
  name: string
  source_fields: string[]
  target_fields: string[]
  group_code_field: string
}
export type CompositeTargetInput = {
  file: FileRecord
  columns: ColumnInfo[]
  inspection?: unknown
}
export type CompositeAssignment = {
  file_id: string
  group_code_column: string
  catalog_version_id?: string
}
type ProfileVersion = { version_no: number; status: string; document: Record<string, any> }
type ProfileDetail = { profile_id: string; name: string; latest_published?: ProfileVersion | null }

function unique(values: unknown[]): string[] {
  return [...new Set(values.map(value => String(value ?? '').trim()).filter(Boolean))]
}

export function isCompositeDocument(document: Record<string, any> | null | undefined): boolean {
  return String(document?.advanced?.profile_kind ?? 'single') === 'composite'
}

export function compositeRefsFromDocument(document: Record<string, any> | null | undefined): CompositeChildRef[] {
  const raw = document?.advanced?.composite_children
  if (!Array.isArray(raw)) return []
  return raw
    .map(item => ({
      profile_id: String(item?.profile_id ?? ''),
      version_no: Number(item?.version_no ?? 0),
    }))
    .filter(item => item.profile_id && item.version_no > 0)
}

export function childViewFromDocument(
  profileId: string,
  versionNo: number,
  name: string,
  document: Record<string, any>,
): CompositeChildView {
  const schema = document?.advanced?.template_schema ?? {}
  const rules = Array.isArray(document?.rules) ? document.rules : []
  return {
    profile_id: profileId,
    version_no: versionNo,
    name,
    source_fields: unique([
      ...(Array.isArray(schema.source_fields) ? schema.source_fields : []),
      document?.source_id_column,
      document?.source_filter?.field,
      ...rules.flatMap((rule: any) => Array.isArray(rule?.source?.fields) ? rule.source.fields : []),
    ]),
    target_fields: unique([
      ...(Array.isArray(schema.target_fields) ? schema.target_fields : []),
      ...rules.flatMap((rule: any) => Array.isArray(rule?.target?.fields) ? rule.target.fields : []),
    ]),
    group_code_field: String(schema.group_code_field ?? ''),
  }
}

export async function getPublishedProfileVersion(profileId: string, versionNo?: number): Promise<CompositeChildView> {
  const detail = (await api.get(`/profiles/${profileId}`)).data as ProfileDetail
  let published: ProfileVersion | null | undefined = detail.latest_published
  if (versionNo && Number(published?.version_no ?? 0) !== versionNo) {
    const versions = ((await api.get(`/profiles/${profileId}/versions`)).data ?? []) as ProfileVersion[]
    published = versions.find(item => item.status === 'PUBLISHED' && Number(item.version_no) === versionNo)
  }
  if (!published) throw new Error(`子方案「${detail.name}」没有可用的已发布版本`)
  const resolvedVersion = versionNo || Number(published.version_no)
  if (isCompositeDocument(published.document)) {
    throw new Error(`「${detail.name}」本身是跨类目组合方案，暂不能作为子方案`)
  }
  return childViewFromDocument(profileId, resolvedVersion, detail.name, published.document ?? {})
}

export async function hydrateCompositeChildren(refs: CompositeChildRef[]): Promise<CompositeChildView[]> {
  const children: CompositeChildView[] = []
  for (const ref of refs) children.push(await getPublishedProfileVersion(ref.profile_id, ref.version_no))
  return children
}

export function targetCompatibility(
  child: CompositeChildView,
  input: CompositeTargetInput,
): { matched: number; total: number; ratio: number; missing: string[] } {
  const available = new Set(input.columns.map(column => column.header))
  const required = unique([...child.target_fields, child.group_code_field])
  const matchedFields = required.filter(field => available.has(field))
  return {
    matched: matchedFields.length,
    total: required.length,
    ratio: required.length ? matchedFields.length / required.length : 0,
    missing: required.filter(field => !available.has(field)),
  }
}

function findGroupCode(child: CompositeChildView, input: CompositeTargetInput): string {
  const headers = new Set(input.columns.map(column => column.header))
  if (child.group_code_field && headers.has(child.group_code_field)) return child.group_code_field
  return input.columns.find(column => column.business_hint === 'group_code')?.header ?? ''
}

export function recommendCompositeAssignments(
  children: CompositeChildView[],
  inputs: CompositeTargetInput[],
  current: Record<string, CompositeAssignment> = {},
): Record<string, CompositeAssignment> {
  const next: Record<string, CompositeAssignment> = {}
  const used = new Set<string>()
  for (const child of children) {
    const assignment = current[child.profile_id]
    if (assignment && inputs.some(input => input.file.file_id === assignment.file_id)) {
      next[child.profile_id] = assignment
      used.add(assignment.file_id)
    }
  }

  const pairs = children.flatMap(child =>
    inputs
      .filter(input => !used.has(input.file.file_id))
      .map(input => ({ child, input, score: targetCompatibility(child, input) })),
  ).sort((a, b) =>
    b.score.ratio - a.score.ratio
    || b.score.matched - a.score.matched
    || a.child.name.localeCompare(b.child.name, 'zh-CN')
    || a.input.file.original_name.localeCompare(b.input.file.original_name, 'zh-CN'),
  )

  const assignedChildren = new Set(Object.keys(next))
  for (const pair of pairs) {
    if (assignedChildren.has(pair.child.profile_id) || used.has(pair.input.file.file_id)) continue
    if (pair.score.total > 0 && pair.score.matched === 0) continue
    next[pair.child.profile_id] = {
      file_id: pair.input.file.file_id,
      group_code_column: findGroupCode(pair.child, pair.input),
    }
    assignedChildren.add(pair.child.profile_id)
    used.add(pair.input.file.file_id)
  }
  return next
}

export async function ensureCatalogVersion(
  input: CompositeTargetInput,
  groupCodeColumn: string,
  schemeTitle: string,
): Promise<string> {
  if (!groupCodeColumn) throw new Error(`请为「${input.file.original_name}」选择集团码字段`)
  const catalogs = ((await api.get('/catalogs')).data ?? []) as Array<Record<string, any>>
  const existing = catalogs.find(item =>
    item.status === 'READY'
    && String(item.source_file_id ?? '') === input.file.file_id
    && String(item.group_code_column ?? '') === groupCodeColumn,
  )
  if (existing?.version_id) return String(existing.version_id)
  const created = (await api.post('/catalogs', {
    name: `${schemeTitle}-${input.file.original_name}`,
    source_file_id: input.file.file_id,
    group_code_column: groupCodeColumn,
  })).data
  return String(created.version_id)
}

export async function resolveCompositeTargetBindings(
  children: CompositeChildView[],
  inputs: CompositeTargetInput[],
  assignments: Record<string, CompositeAssignment>,
  schemeTitle: string,
): Promise<{ bindings: Array<CompositeChildRef & { catalog_version_id: string }>; assignments: Record<string, CompositeAssignment> }> {
  const bindings: Array<CompositeChildRef & { catalog_version_id: string }> = []
  const next = { ...assignments }
  for (const child of children) {
    const assignment = next[child.profile_id]
    if (!assignment?.file_id) throw new Error(`请为子方案「${child.name}」分配本次集团文件`)
    const input = inputs.find(item => item.file.file_id === assignment.file_id)
    if (!input) throw new Error(`子方案「${child.name}」对应的集团文件已不存在，请重新选择`)
    if (!assignment.group_code_column) throw new Error(`请确认子方案「${child.name}」对应文件的集团码字段`)
    const catalogVersionId = assignment.catalog_version_id
      || await ensureCatalogVersion(input, assignment.group_code_column, schemeTitle)
    next[child.profile_id] = { ...assignment, catalog_version_id: catalogVersionId }
    bindings.push({ profile_id: child.profile_id, version_no: child.version_no, catalog_version_id: catalogVersionId })
  }
  return { bindings, assignments: next }
}
