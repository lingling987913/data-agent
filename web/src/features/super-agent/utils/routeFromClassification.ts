import type { MaterialClassification, SuperAgentRoute } from '@/features/super-agent/types'

const REVIEW_SLOT_ROLES = new Set(['review_rule', 'checklist', 'task_book'])
const SUBJECT_ROLES = new Set(['subject_report', 'subject_document', 'supporting_attachment'])

function rolesFromClassification(classification?: MaterialClassification | null): Set<string> {
  const roles = new Set<string>()
  for (const item of classification?.material_roles || []) {
    const role = String(item.role || '').trim()
    if (role) roles.add(role)
  }
  return roles
}

export function materialRolesHintReviewPlus(classification?: MaterialClassification | null): boolean {
  const roles = rolesFromClassification(classification)
  const hasRule = [...roles].some((role) => REVIEW_SLOT_ROLES.has(role))
  const hasTask = roles.has('task_book')
  const hasSubject = [...roles].some((role) => SUBJECT_ROLES.has(role))
  return hasRule && hasTask && hasSubject
}

export function routeFromClassification(
  route: string,
  classification?: MaterialClassification | null,
): SuperAgentRoute {
  if (materialRolesHintReviewPlus(classification)) {
    return 'review_plus'
  }

  const normalized = route.trim().toLowerCase()
  if (normalized === 'smart' || normalized === 'parse_only') return 'smart'
  if (normalized.includes('gnc')) return 'gnc_review_only'
  if (normalized.includes('review')) return 'review_plus'
  if (normalized.includes('structure')) return 'structure_only'
  if (normalized.includes('hybrid')) return 'hybrid'
  return 'auto'
}

export function fallbackClassifyFromFileNames(files: File[]): MaterialClassification {
  const names = files.map((f) => f.name.toLowerCase()).join(' ')
  const materialRoles = files.map((file) => ({
    file_name: file.name,
    role: 'unknown' as const,
    confidence: 0.3,
    reason: '本地推断，待服务端识别',
  }))

  const hasReviewSlots =
    names.includes('检查需求') ||
    names.includes('检查单') ||
    names.includes('checklist') ||
    names.includes('任务书')
  const hasSubject =
    names.includes('报告') ||
    names.includes('方案') ||
    names.includes('设计')

  if (hasReviewSlots && hasSubject) {
    return {
      doc_type: '设计审查材料包',
      domain: '质量保证',
      recommended_route: 'review_plus',
      reason: '检测到文件组审查材料（规则/检查单/任务书 + 被审材料）',
      material_roles: materialRoles,
    }
  }

  if (
    (names.includes('gnc') || names.includes('姿态') || names.includes('轨控')) &&
    !hasReviewSlots
  ) {
    return {
      doc_type: 'GNC 设计报告',
      domain: '控制/导航',
      recommended_route: 'gnc_review_only',
      reason: '检测到 GNC 相关设计文档，推荐使用专项审查',
      material_roles: materialRoles,
    }
  }

  if (names.includes('检查单') || names.includes('checklist')) {
    return {
      doc_type: '设计审查检查单',
      domain: '质量保证',
      recommended_route: 'review_plus',
      reason: '检测到检查单类材料，推荐使用标准审查流程',
      material_roles: materialRoles,
    }
  }

  return {
    doc_type: '工程设计文档',
    domain: '综合',
    recommended_route: 'auto',
    reason: '材料类型较综合，推荐使用智能审查自动匹配场景',
    material_roles: materialRoles,
  }
}
