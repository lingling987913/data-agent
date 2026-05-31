export const DEFAULT_REVIEW_OBJECTIVE = '对上传材料执行智能审查'
export const DRAFT_REVIEW_OBJECTIVE = '等待上传材料后执行智能审查。'

export function resolveReviewObjective(
  reviewObjective: string,
  runObjective?: string,
  fallback?: string,
): string {
  const trimmed = reviewObjective.trim()
  if (trimmed) return trimmed
  const runTrimmed = runObjective?.trim()
  if (runTrimmed && !runTrimmed.startsWith('等待上传材料')) return runTrimmed
  const fallbackTrimmed = fallback?.trim()
  if (fallbackTrimmed) return fallbackTrimmed
  return DEFAULT_REVIEW_OBJECTIVE
}

export function isPersistableReviewObjective(objective: string): boolean {
  const trimmed = objective.trim()
  return Boolean(trimmed) && trimmed !== DEFAULT_REVIEW_OBJECTIVE && trimmed !== DRAFT_REVIEW_OBJECTIVE
}
