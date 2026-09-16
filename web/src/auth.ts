const RETURN_TO_KEY = 'mm_auth_return_to'
const EXPIRED_NOTICE_KEY = 'mm_auth_expired_notice'

let authRedirectInFlight = false

function safeSet(key: string, value: string): void {
  try {
    window.sessionStorage.setItem(key, value)
  } catch {
    // Storage can be unavailable in hardened/private browser modes; redirect must still work.
  }
}

function safeGet(key: string): string | null {
  try {
    return window.sessionStorage.getItem(key)
  } catch {
    return null
  }
}

function safeRemove(key: string): void {
  try {
    window.sessionStorage.removeItem(key)
  } catch {
    // Best effort only.
  }
}

export function handleAuthRequired(): void {
  if (authRedirectInFlight) return
  authRedirectInFlight = true

  if (window.location.pathname !== '/login') {
    // Preserve the complete URL (path + query + hash, including origin) exactly once.
    safeSet(RETURN_TO_KEY, window.location.href)
  }
  safeSet(EXPIRED_NOTICE_KEY, '1')

  if (window.location.pathname === '/login') return
  window.location.replace('/login')
}

export function consumeAuthExpiredNotice(): boolean {
  const pending = safeGet(EXPIRED_NOTICE_KEY) === '1'
  if (pending) safeRemove(EXPIRED_NOTICE_KEY)
  return pending
}

export function consumeAuthReturnTo(fallback = '/tasks'): string {
  const stored = safeGet(RETURN_TO_KEY)
  safeRemove(RETURN_TO_KEY)
  if (!stored) return fallback

  try {
    const target = new URL(stored, window.location.origin)
    if (target.origin !== window.location.origin || target.pathname === '/login') return fallback
    return `${target.pathname}${target.search}${target.hash}` || fallback
  } catch {
    return fallback
  }
}
