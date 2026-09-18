export function businessRatePercent(count: number, total: number): number | null {
  const numericTotal = Number(total)
  if (!Number.isFinite(numericTotal) || numericTotal <= 0) return null

  const numericCount = Number(count)
  const safeCount = Number.isFinite(numericCount) ? Math.max(0, numericCount) : 0
  return (safeCount / numericTotal) * 100
}

export function formatBusinessRate(count: number, total: number): string {
  const rate = businessRatePercent(count, total)
  if (rate === null) return '—'
  if (rate === 0) return '0%'
  return `${rate.toFixed(1)}%`
}

export function businessRateWidth(count: number, total: number): string {
  const rate = businessRatePercent(count, total)
  if (rate === null) return '0%'
  const clamped = Math.min(100, Math.max(0, rate))
  return `${clamped.toFixed(4)}%`
}
