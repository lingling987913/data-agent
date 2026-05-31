export type ReviewPlusVerdictTone = 'pass' | 'fail' | 'conditional' | null

export function inferReviewPlusVerdict(conclusion?: string | null): ReviewPlusVerdictTone {
  const concl = String(conclusion || '').toLowerCase()
  if (!concl) return null
  if (concl.includes('通过') && !concl.includes('不通过') && !concl.includes('条件')) return 'pass'
  if (concl.includes('不通过') || concl.includes('未通过')) return 'fail'
  if (concl.includes('条件') || concl.includes('保留')) return 'conditional'
  return null
}

export const REVIEW_PLUS_VERDICT_LABELS: Record<Exclude<ReviewPlusVerdictTone, null>, string> = {
  pass: '通过',
  fail: '不通过',
  conditional: '有条件通过',
}

export const REVIEW_PLUS_VERDICT_COLORS: Record<Exclude<ReviewPlusVerdictTone, null>, string> = {
  pass: 'bg-positive/10 text-positive border-positive/20',
  fail: 'bg-destructive/10 text-destructive border-destructive/20',
  conditional: 'bg-warning/10 text-warning border-warning/20',
}

export function formatReviewPlusPassRate(total: number, satisfied: number): string {
  if (total <= 0) return '—'
  return `${Math.round((satisfied / total) * 100)}%`
}
