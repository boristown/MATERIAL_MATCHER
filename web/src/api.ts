import axios from 'axios'

const api = axios.create({ baseURL: '/api' })

export type MappingConfig = {
  source_header: string
  target_header: string
  weight: number
  method: string
  name?: string
  critical?: boolean
}

export type MatchConfig = {
  source_sheet?: string | null
  source_header_row: number
  target_sheet?: string | null
  target_header_row: number
  source_id_column: string
  group_code_column: string
  mappings: MappingConfig[]
  threshold: number
  review_threshold?: number | null
  top_n: number
  candidate_limit: number
}

export function setToken(token: string | null) {
  if (token) {
    api.defaults.headers.common.Authorization = `Bearer ${token}`
    sessionStorage.setItem('material_matcher_token', token)
  } else {
    delete api.defaults.headers.common.Authorization
    sessionStorage.removeItem('material_matcher_token')
  }
}

const saved = sessionStorage.getItem('material_matcher_token')
if (saved) setToken(saved)

export async function login(password: string) {
  const { data } = await api.post('/auth/login', { username: 'admin', password })
  setToken(data.token)
  return data
}

export async function getSystemInfo() {
  const { data } = await api.get('/system/info')
  return data
}

export async function getHealth() {
  const { data } = await api.get('/health')
  return data
}

export async function uploadExcel(file: File, role: 'source' | 'target' | 'supplement') {
  const form = new FormData()
  form.append('file', file)
  const { data } = await api.post(`/files/upload?role=${role}`, form, {
    headers: { 'Content-Type': 'multipart/form-data' },
  })
  return data
}

export async function dryRun(sourceFileId: string, targetFileId: string, config: MatchConfig) {
  const { data } = await api.post('/wizard/dry-run', {
    source_file_id: sourceFileId,
    target_file_id: targetFileId,
    config,
    sample_rows: 30,
    target_sample_rows: 10000,
  })
  return data
}

export async function publishProfile(name: string, description: string, config: MatchConfig) {
  const { data } = await api.post('/profiles/publish', { name, description, config })
  return data
}

export async function listProfiles() {
  const { data } = await api.get('/profiles')
  return data
}

export async function listProfileVersions(name: string) {
  const { data } = await api.get(`/profiles/${encodeURIComponent(name)}/versions`)
  return data
}

export async function createTask(profileName: string, sourceFileId: string, targetFileId: string) {
  const { data } = await api.post('/tasks', {
    profile_name: profileName,
    source_file_id: sourceFileId,
    target_file_id: targetFileId,
  })
  return data
}

export async function listTasks() {
  const { data } = await api.get('/tasks')
  return data
}

export async function listFiles() {
  const { data } = await api.get('/files')
  return data
}

export async function cleanupFiles(olderThanHours?: number) {
  const { data } = await api.post('/files/cleanup', {
    older_than_hours: olderThanHours ?? null,
  })
  return data
}

export async function deleteFile(fileId: string) {
  const { data } = await api.delete(`/files/${fileId}`)
  return data
}

export function taskResultUrl(taskId: string) {
  return `/api/tasks/${encodeURIComponent(taskId)}/result`
}

export default api
