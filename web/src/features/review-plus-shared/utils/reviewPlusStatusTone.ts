import type { StatusBadgeTone } from '@aqua/ui-core'

export function reviewPlusTaskStatusTone(status: string): StatusBadgeTone {
  if (['completed', 'ready'].includes(status)) return 'positive'
  if (['failed', 'blocked'].includes(status)) return 'destructive'
  if (['limited_pass', 'materials_uploaded', 'classified', 'scenario_detected'].includes(status)) {
    return 'warning'
  }
  if (['reviewing', 'mapping', 'structuring', 'rule_extracting', 'reporting', 'traceability_building', 'parsing', 'classifying', 'gatekeeping'].includes(status)) {
    return 'brand'
  }
  return 'neutral'
}

export function reviewPlusJudgmentTone(judgment: string): StatusBadgeTone {
  if (judgment === 'satisfied') return 'positive'
  if (judgment === 'not_satisfied') return 'destructive'
  if (judgment === 'insufficient_evidence') return 'warning'
  return 'neutral'
}

export function reviewPlusParseStatusTone(status?: string): StatusBadgeTone {
  if (status === 'ok' || status === 'parsed') return 'positive'
  if (status === 'degraded' || status === 'partial') return 'warning'
  if (status === 'failed') return 'destructive'
  if (status === 'parsing') return 'brand'
  return 'neutral'
}

export function reviewPlusGateStatusTone(status: string): StatusBadgeTone {
  if (status === 'passed') return 'positive'
  if (status === 'limited') return 'warning'
  if (status === 'blocked') return 'destructive'
  return 'neutral'
}

export function reviewPlusSlotStatusTone(
  materials: Array<{ parse_status?: string; content?: string; role?: string; role_confirmed?: boolean }>,
  required: boolean,
): StatusBadgeTone {
  if (materials.length === 0) {
    return required ? 'destructive' : 'neutral'
  }
  if (materials.some((item) => item.parse_status === 'failed' || !(item.content || '').trim())) {
    return 'warning'
  }
  if (materials.some((item) => !item.role_confirmed && String(item.role || '') !== 'unknown')) {
    return 'warning'
  }
  if (materials.some((item) => String(item.role || '') === 'unknown')) {
    return 'warning'
  }
  return 'positive'
}
