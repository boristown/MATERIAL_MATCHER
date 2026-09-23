import { api } from './api'

let pendingVersion: Promise<string> | undefined

export function fetchAppVersion(): Promise<string> {
  if (!pendingVersion) {
    pendingVersion = api.get('/health')
      .then(response => String(response.data?.version ?? '').trim())
      .catch(() => {
        pendingVersion = undefined
        return ''
      })
  }
  return pendingVersion
}
