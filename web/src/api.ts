import axios from 'axios'

const api = axios.create({ baseURL: '/api' })

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

export default api
