export function formatTimePoint(value: string | null | undefined): string {
  if (!value) return '—'
  return String(value).slice(0, 19).replace('T', ' ')
}

export function formatDurationMs(
  value: number | string | null | undefined,
  unavailable = '暂无准确记录',
): string {
  if (value === null || value === undefined || value === '') return unavailable
  const milliseconds = Number(value)
  if (!Number.isFinite(milliseconds) || milliseconds < 0) return unavailable
  const totalSeconds = Math.round(milliseconds / 1000)
  if (totalSeconds < 60) return `${totalSeconds} 秒`
  const minutes = Math.floor(totalSeconds / 60)
  const seconds = totalSeconds % 60
  if (minutes < 60) return `${minutes} 分 ${seconds} 秒`
  const hours = Math.floor(minutes / 60)
  return `${hours} 小时 ${minutes % 60} 分 ${seconds} 秒`
}
