import axios from 'axios'

export const api = axios.create({
  baseURL: '/api',
  withCredentials: true,
})

api.interceptors.response.use(
  (response) => response,
  (error) => Promise.reject(new Error(error.response?.data?.error?.message ?? '请求失败')),
)
