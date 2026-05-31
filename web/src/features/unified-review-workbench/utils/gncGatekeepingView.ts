import type { StatusBadgeTone } from '@aqua/ui-core'

const GNC_MATERIAL_ROLE_LABELS: Record<string, string> = {
  top_requirement: '上级需求文档',
  decomposed_requirement: '需求分解文档',
  design_solution: '设计方案文档',
  interface_control: '接口控制文件',
  simulation_report: '仿真分析报告',
  verification_plan: '验证计划',
  verification_result: '验证结果',
  supporting_attachment: '支撑附件',
  primary_doc: '主文档',
  subject_document: '审查对象',
  unknown: '未识别',
}

export interface GatekeepingIssueGroup {
  key: 'blocking' | 'warnings' | 'missing'
  title: string
  tone: StatusBadgeTone
  items: string[]
}

export function resolveGncMaterialRoleLabel(role?: string): string {
  const normalized = String(role || '').trim()
  if (!normalized) return '未识别'
  return GNC_MATERIAL_ROLE_LABELS[normalized] || normalized
}

export function resolveGncParseStatusLabel(status?: string): string {
  if (status === 'parsed' || status === 'ok') return '已解析'
  if (status === 'failed') return '解析失败'
  if (status === 'parsing') return '解析中'
  if (status === 'degraded' || status === 'partial') return '解析受限'
  return '待解析'
}

export function resolveGncParseStatusTone(status?: string): StatusBadgeTone {
  if (status === 'parsed' || status === 'ok') return 'positive'
  if (status === 'degraded' || status === 'partial') return 'warning'
  if (status === 'failed') return 'destructive'
  if (status === 'parsing') return 'brand'
  return 'neutral'
}

export function resolveGncGateStatusLabel(status?: string): string {
  if (status === 'passed' || status === 'pass') return '准入通过'
  if (status === 'limited' || status === 'limited_pass') return '有条件准入'
  if (status === 'blocked') return '准入阻断'
  if (status === 'pass_with_note') return '带说明通过'
  return status || '待检查'
}

export function resolveGncGateStatusTone(status?: string): StatusBadgeTone {
  if (status === 'passed' || status === 'pass' || status === 'pass_with_note') return 'positive'
  if (status === 'limited' || status === 'limited_pass') return 'warning'
  if (status === 'blocked') return 'destructive'
  return 'neutral'
}

export function resolveGncRoleConfirmTone(confirmed?: boolean): StatusBadgeTone {
  if (confirmed === false) return 'warning'
  if (confirmed === true) return 'positive'
  return 'neutral'
}

export function resolveGncRoleConfirmLabel(confirmed?: boolean): string {
  if (confirmed === false) return '角色待确认'
  if (confirmed === true) return '角色已确认'
  return '角色未标注'
}

export function groupGatekeepingIssues(gate: {
  blocking_reasons?: string[]
  warnings?: string[]
  missing_materials?: string[]
}): GatekeepingIssueGroup[] {
  const groups: GatekeepingIssueGroup[] = []
  const blocking = (gate.blocking_reasons || []).filter(Boolean)
  const warnings = (gate.warnings || []).filter(Boolean)
  const missing = (gate.missing_materials || []).filter(Boolean)

  if (blocking.length) {
    groups.push({ key: 'blocking', title: '阻塞原因', tone: 'destructive', items: blocking })
  }
  if (warnings.length) {
    groups.push({ key: 'warnings', title: '警告', tone: 'warning', items: warnings })
  }
  if (missing.length) {
    groups.push({ key: 'missing', title: '缺失材料', tone: 'neutral', items: missing })
  }
  return groups
}
