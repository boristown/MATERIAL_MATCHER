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
    const canceled = (axios.isCancel && axios.isCancel(error))
      || error?.code === 'ERR_CANCELED' || error?.name === 'CanceledError' || error?.name === 'AbortError'
    const normalized = new Error(error.response?.data?.error?.message ?? (canceled ? '请求已中断' : '请求失败')) as Error & {
      status?: number
      code?: string
      canceled?: boolean
    }
    normalized.status = status
    normalized.code = code
    normalized.canceled = canceled
    return Promise.reject(normalized)
  },
)
