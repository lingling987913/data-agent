import type { UnifiedReviewWorkbenchDetail } from '@/features/unified-review-workbench/types'
import {
  buildConclusionOverviewFromDetail,
  deriveReviewTaskDisplayName,
} from '@/features/unified-review-workbench/utils/conclusionOverviewModel'
import { resolvePhaseLabel } from '@/features/unified-review-workbench/phaseResolver'
import {
  resolveWorkbenchPendingConfirm,
  resolveWorkbenchProblemCount,
} from '@/features/unified-review-workbench/utils/workbenchIssueStats'
import { resolveWorkbenchStatusText } from '@/features/unified-review-workbench/utils/zhWorkbenchText'

function numberValue(value: unknown): number {
  const n = Number(value)
  return Number.isFinite(n) ? n : 0
}

function escapeTableCell(value: unknown): string {
  return String(value ?? '').replace(/\|/g, '\\|').replace(/\n/g, '<br>')
}

export function markdownHasWorkbenchOverview(markdown: string): boolean {
  return /##\s*2\.\s*审查总览/.test(markdown)
}

export function buildWorkbenchOverviewMarkdown(
  detail: UnifiedReviewWorkbenchDetail,
): string {
  const model = buildConclusionOverviewFromDetail(
    detail,
    detail.review_type,
  )
  const scope = detail.conclusion_overview?.review_scope || {}
  const pendingConfirm = resolveWorkbenchPendingConfirm(detail)
  const problemCount = resolveWorkbenchProblemCount(detail)
  const qualityHint = detail.workbench_phase === 'failed'
    ? '异常'
    : detail.error
      ? '需关注'
      : '正常'
  const materialCount = detail.metrics.material_count
    ?? numberValue((scope as Record<string, unknown>).material_count)
    ?? model.reviewSubjectLines.length
    ?? '—'
  const phaseLabel = resolvePhaseLabel(detail.workbench_phase)
  const step = String(detail.current_step || '').trim()
  const phaseDisplay = step && !/[\u4e00-\u9fff]/.test(step)
    ? `${phaseLabel}（${step.replace(/_/g, ' ')}）`
    : step
      ? `${phaseLabel}（${step}）`
      : phaseLabel

  const situationRows: Array<[string, string]> = [
    ['运行状态', resolveWorkbenchStatusText(detail.status)],
    ['当前阶段', phaseDisplay],
    ['材料数量', String(materialCount)],
    ['审查路线', model.reviewModeLabel || '待识别'],
    ['问题数量', String(problemCount || '—')],
    ['待确认事项', String(pendingConfirm)],
    ['质量状态', qualityHint],
  ]

  const lines: string[] = [
    '## 2. 审查总览',
    '',
    '### 2.1 审查概况',
    '',
    '| 项目 | 内容 |',
    '| --- | --- |',
    ...situationRows.map(([label, value]) => `| ${label} | ${escapeTableCell(value)} |`),
    '',
    '### 2.2 审查任务详情',
    '',
    `- 审查任务：${deriveReviewTaskDisplayName(detail)}`,
  ]

  if (model.reviewSubjectLines.length) {
    lines.push('- 审查对象：')
    model.reviewSubjectLines.forEach((line) => lines.push(`  - ${line}`))
  }
  if (model.reviewPlanLines.length) {
    lines.push('- 审查方案：')
    model.reviewPlanLines.forEach((line) => lines.push(`  - ${line}`))
  }

  lines.push(
    '',
    '### 2.3 裁定结论',
    '',
    `- 裁定结论：${model.verdictLabel || '待形成结论'}`,
  )
  if (model.rationaleDisplay) {
    lines.push(`- 结论说明：${model.rationaleDisplay}`)
  }
  lines.push(`- 一句话结论：${model.oneLineConclusion || model.headlineVerdict || model.verdictLabel || '待形成结论'}`)
  lines.push('')

  return lines.join('\n')
}

/** Insert overview after section 1 when backend markdown lacks it. */
export function mergeWorkbenchOverviewIntoMarkdown(
  markdown: string,
  detail: UnifiedReviewWorkbenchDetail,
): string {
  const body = String(markdown || '').trim()
  if (!body || markdownHasWorkbenchOverview(body)) return body

  const overview = buildWorkbenchOverviewMarkdown(detail).trim()
  const materialHeading = /^##\s*2\.\s*材料质量结论/m
  const basicInfoEnd = body.search(/^##\s*2\./m)
  if (materialHeading.test(body)) {
    return body.replace(materialHeading, `${overview}\n## 3. 材料质量结论`)
      .replace(/^##\s*3\.\s*总体审查结论/m, '## 4. 总体审查结论')
      .replace(/^##\s*4\.\s*专业审查发现/m, '## 5. 专业审查发现')
      .replace(/^##\s*5\.\s*证据定位汇总/m, '## 6. 证据定位汇总')
      .replace(/^##\s*6\.\s*结论草稿/m, '## 7. 结论草稿')
      .replace(/^##\s*7\.\s*审签栏/m, '## 8. 审签栏')
  }
  if (basicInfoEnd >= 0) {
    const nextSection = body.indexOf('\n## ', basicInfoEnd + 1)
    const insertAt = nextSection >= 0 ? nextSection : body.length
    return `${body.slice(0, insertAt).trimEnd()}\n\n${overview}\n${body.slice(insertAt).trimStart()}`.trim()
  }
  return `${body}\n\n${overview}`.trim()
}
