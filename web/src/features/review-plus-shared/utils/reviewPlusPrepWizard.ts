export type PrepWizardStep = 1 | 2 | 3 | 4 | 5

export type PrepWizardOptions = {
  parseComplete?: boolean
  parsing?: boolean
  taskStatus?: string
}

export function resolvePrepWizardStep(
  materials: Array<{ role?: string; role_confirmed?: boolean }>,
  gateStatus: string,
  missingRequiredCount: number,
  options: PrepWizardOptions = {},
): { step: PrepWizardStep; label: string } {
  const { parseComplete = false, parsing = false, taskStatus = '' } = options
  const status = String(taskStatus || '')

  if (missingRequiredCount > 0) {
    return { step: 1, label: '请先补齐四类必需材料' }
  }
  const unknownCount = materials.filter((m) => String(m.role || '') === 'unknown').length
  const unconfirmedCount = materials.filter(
    (m) => !m.role_confirmed && String(m.role || '') !== 'unknown',
  ).length
  if (unknownCount > 0 || unconfirmedCount > 0) {
    return { step: 2, label: '请确认或修正材料角色' }
  }
  if (parsing || status === 'parsing') {
    return { step: 3, label: '正在解析材料，请稍候…' }
  }
  if (!parseComplete) {
    return { step: 3, label: '材料角色已确认，请执行文档解析' }
  }
  if (gateStatus === 'blocked') {
    return { step: 4, label: '送审包准入未通过，请处理阻断项' }
  }
  if (gateStatus === 'limited' || gateStatus === 'unknown') {
    return { step: 4, label: '请完成送审包准入检查' }
  }
  return { step: 5, label: '材料已就绪，可在工作台右上角开始处理' }
}
