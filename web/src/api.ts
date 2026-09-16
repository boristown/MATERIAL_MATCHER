import axios from 'axios'

import { handleAuthRequired } from './auth'

export const api = axios.create({
  baseURL: '/api',
  withCredentials: true,
})

api.interceptors.response.use(
  (response) => response,
  (error) => {
    const status = error.response?.status
    const code = error.response?.data?.error?.code
    if (status === 401 && code === 'AUTH_REQUIRED') {
      handleAuthRequired()
    }
    const normalized = new Error(error.response?.data?.error?.message ?? '请求失败') as Error & {
      status?: number
      code?: string
    }
    normalized.status = status
    normalized.code = code
    return Promise.reject(normalized)
  },
)
