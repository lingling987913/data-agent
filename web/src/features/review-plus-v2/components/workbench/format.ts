export function formatMetricValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return '—'
  if (typeof value === 'number' && Number.isFinite(value)) {
    return Number.isInteger(value) ? String(value) : value.toLocaleString('zh-CN', { maximumFractionDigits: 2 })
  }
  return String(value)
}

export function formatPercent(value: unknown): string {
  const num = Number(value)
  if (Number.isNaN(num)) return '—'
  const pct = num <= 1 && num >= -1 ? num * 100 : num
  const sign = pct > 0 ? '+' : ''
  return `${sign}${pct.toFixed(2)}%`
}
