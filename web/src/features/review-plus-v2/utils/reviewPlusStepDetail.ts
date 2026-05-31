import type { WorkflowStepStatus } from '@aqua/workflow-core'
import { STEP_STATUS_LABELS } from '@aqua/workflow-core'
import type { ReviewPlusEvent, ReviewPlusTaskDetail } from '@/features/review-plus-v2/types'
import { COVERAGE_STATUS_LABELS, JUDGMENT_LABELS, MATERIAL_ROLE_LABELS } from '@/features/review-plus-v2/types'
import {
  buildHarnessSummaryMetrics,
  formatAgentIdLabel,
  getHarnessPlan,
  hasHarnessArtifacts,
  pickTopSelectionReasons,
} from '@/features/review-plus-shared/utils/reviewPlusHarnessViewModel'
import {
  REVIEW_PLUS_PIPELINE_STEPS,
  formatReviewPlusEventLabel,
  type ReviewPlusPipelineStepKey,
  type ReviewPlusWorkbenchTabKey,
  workflowStepToWorkbenchTab,
} from '@/features/review-plus-v2/utils/reviewPlusPipeline'
import {
  buildReviewPlusCheckItemIndexMap,
  resolveReviewPlusFindingTitle,
} from '@/features/review-plus-v2/utils/reviewPlusCheckItemLabel'

export interface ReviewPlusStepMetric {
  label: string
  value: string | number
  tone?: 'default' | 'brand' | 'success' | 'warning' | 'danger'
}

export interface ReviewPlusStepFindingPreview {
  id: string
  title: string
  subtitle?: string
  tone?: 'warning' | 'danger'
}

export interface ReviewPlusStepEventLine {
  type: string
  label: string
  summary: string
  at?: string
}

export interface ReviewPlusStepDetail {
  stepKey: ReviewPlusPipelineStepKey
  label: string
  description: string
  status: WorkflowStepStatus
  statusLabel: string
  startedAt?: string
  completedAt?: string
  outputSummary?: string
  summaryLines: string[]
  metrics: ReviewPlusStepMetric[]
  highlights: string[]
  findingPreviews: ReviewPlusStepFindingPreview[]
  recentEvents: ReviewPlusStepEventLine[]
  relatedTab: ReviewPlusWorkbenchTabKey
  pendingHint?: string
  showHarnessPanel?: boolean
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {}
}

function textValue(value: unknown, fallback = ''): string {
  const text = String(value ?? '').trim()
  return text || fallback
}

function numValue(value: unknown, fallback = 0): number {
  const n = Number(value)
  return Number.isFinite(n) ? n : fallback
}

function percentValue(value: unknown): string {
  const n = numValue(value, 0)
  const pct = n <= 1 ? Math.round(n * 100) : Math.round(n)
  return `${pct}%`
}

function formatTime(iso?: string | null): string {
  if (!iso) return ''
  try {
    return new Date(iso).toLocaleString('zh-CN', {
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    })
  } catch {
    return iso
  }
}

function eventsForStep(events: ReviewPlusEvent[], stepKey: string): ReviewPlusEvent[] {
  const step = REVIEW_PLUS_PIPELINE_STEPS.find((item) => item.step_key === stepKey)
  if (!step) return []
  return (events || []).filter((event) => {
    const type = String(event.type || '')
    return type === step.completeEvent
      || (step.startEvent && type === step.startEvent)
      || type.includes(stepKey)
  })
}

function latestEvent(events: ReviewPlusEvent[]): ReviewPlusEvent | null {
  if (!events.length) return null
  return [...events].sort((a, b) => numValue(b.sequence) - numValue(a.sequence))[0] ?? null
}

function latestCompleteEvent(events: ReviewPlusEvent[], completeEvent: string): ReviewPlusEvent | null {
  const matched = events.filter((e) => String(e.type || '') === completeEvent)
  return latestEvent(matched)
}

/** 将 event payload 格式化为可读摘要行（无 summary 字段时） */
export function formatEventPayloadSummary(eventType: string, payload: Record<string, unknown>): string {
  const direct = textValue(payload.summary || payload.message || payload.detail)
  if (direct) return direct

  const type = String(eventType || '').toLowerCase()
  const lines: string[] = []

  if (payload.scenario) lines.push(`场景：${textValue(payload.scenario)}`)
  if (payload.confidence != null) lines.push(`置信度：${percentValue(payload.confidence)}`)
  if (payload.reason) lines.push(textValue(payload.reason))
  if (payload.check_item_count != null) lines.push(`检查项 ${numValue(payload.check_item_count)} 条`)
  if (payload.mapped_count != null && payload.total_count != null) {
    lines.push(`映射 ${numValue(payload.mapped_count)}/${numValue(payload.total_count)} 项`)
  }
  if (payload.avg_confidence != null) lines.push(`平均置信度 ${percentValue(payload.avg_confidence)}`)
  if (payload.finding_count != null) lines.push(`审查记录 ${numValue(payload.finding_count)} 条`)
  if (payload.satisfied != null) lines.push(`满足 ${numValue(payload.satisfied)}`)
  if (payload.not_satisfied != null) lines.push(`不满足 ${numValue(payload.not_satisfied)}`)
  if (payload.insufficient != null) lines.push(`证据不足 ${numValue(payload.insufficient)}`)
  if (payload.critical != null && numValue(payload.critical) > 0) lines.push(`关键 ${numValue(payload.critical)}`)
  if (payload.agent_count != null) lines.push(`调度专家 ${numValue(payload.agent_count)} 个`)
  if (payload.harness_team_id) lines.push(`审查组 ${textValue(payload.harness_team_id)}`)
  if (payload.selected_agent_count != null) lines.push(`动态选中 ${numValue(payload.selected_agent_count)} 个环节`)
  if (payload.trace_completed != null) lines.push(`执行完成 ${numValue(payload.trace_completed)}`)
  if (payload.trace_failed != null && numValue(payload.trace_failed) > 0) {
    lines.push(`执行失败 ${numValue(payload.trace_failed)}`)
  }
  if (payload.coverage_closed != null) lines.push(`覆盖已闭合 ${numValue(payload.coverage_closed)}`)
  if (payload.coverage_missing != null && numValue(payload.coverage_missing) > 0) {
    lines.push(`覆盖缺失 ${numValue(payload.coverage_missing)}`)
  }
  if (payload.document_format_finding_count != null) {
    lines.push(`格式问题 ${numValue(payload.document_format_finding_count)} 条`)
  }
  if (payload.document_format_gate_status) {
    lines.push(`格式门禁：${textValue(payload.document_format_gate_status)}`)
  }
  if (payload.material_count != null) lines.push(`材料 ${numValue(payload.material_count)} 份`)
  if (payload.trace_link_count != null) lines.push(`追溯链 ${numValue(payload.trace_link_count)} 条`)
  if (payload.requirement_count != null) lines.push(`需求 ${numValue(payload.requirement_count)} 条`)
  if (payload.design_closure_coverage != null) {
    lines.push(`设计闭合覆盖 ${percentValue(payload.design_closure_coverage)}`)
  }
  if (payload.verification_coverage != null) {
    lines.push(`验证覆盖 ${percentValue(payload.verification_coverage)}`)
  }
  if (payload.warning) lines.push(textValue(payload.warning))
  if (payload.error) lines.push(textValue(payload.error))

  const stats = asRecord(payload.stats)
  if (Object.keys(stats).length > 0) {
    const chunkCount = numValue(stats.chunk_count ?? stats.total_chunks)
    const sectionCount = numValue(stats.section_count ?? stats.sections)
    if (chunkCount) lines.push(`语块 ${chunkCount} 个`)
    if (sectionCount) lines.push(`章节 ${sectionCount} 个`)
  }

  const warnings = Array.isArray(payload.warnings) ? payload.warnings : []
  if (warnings.length > 0) lines.push(`告警 ${warnings.length} 条`)

  const roles = Array.isArray(payload.roles) ? payload.roles : []
  if (roles.length > 0) lines.push(`已分类 ${roles.length} 份材料`)

  if (type.includes('fail') && payload.error) return textValue(payload.error)
  if (lines.length > 0) return lines.slice(0, 3).join('；')

  const keys = Object.keys(payload).filter((k) => !['from_status', 'to_status', 'step', 'timestamp'].includes(k))
  if (keys.length === 0) return ''
  return keys.slice(0, 4).map((k) => `${k}: ${String(payload[k] ?? '')}`).join('；')
}

function buildStepDomainDetail(
  stepKey: ReviewPlusPipelineStepKey,
  task: ReviewPlusTaskDetail,
  payload: Record<string, unknown>,
): Pick<ReviewPlusStepDetail, 'summaryLines' | 'metrics' | 'highlights'> {
  const summaryLines: string[] = []
  const metrics: ReviewPlusStepMetric[] = []
  const highlights: string[] = []

  switch (stepKey) {
    case 'material_classification': {
      const materials = task.materials || []
      const roleCounts = new Map<string, number>()
      for (const m of materials) {
        const role = String(m.role || 'unknown')
        roleCounts.set(role, (roleCounts.get(role) || 0) + 1)
      }
      metrics.push({ label: '材料数', value: materials.length })
      for (const [role, count] of roleCounts) {
        if (count > 0) {
          metrics.push({
            label: MATERIAL_ROLE_LABELS[role] || role,
            value: count,
          })
        }
      }
      const confirmed = materials.filter((m) => m.role_confirmed).length
      if (confirmed > 0) metrics.push({ label: '已确认角色', value: confirmed, tone: 'success' })
      if (materials.length > 0) {
        summaryLines.push(`已完成 ${materials.length} 份材料的角色识别与归类。`)
      }
      break
    }
    case 'scenario_detection': {
      if (task.scenario) {
        metrics.push({ label: '场景', value: task.scenario, tone: 'brand' })
        metrics.push({
          label: '置信度',
          value: percentValue(task.scenario_confidence ?? payload.confidence),
        })
        summaryLines.push(task.scenario_reason || textValue(payload.reason))
      } else if (payload.scenario) {
        metrics.push({ label: '场景', value: textValue(payload.scenario), tone: 'brand' })
        summaryLines.push(textValue(payload.reason))
      }
      break
    }
    case 'document_structuring': {
      const stats = asRecord(payload.stats)
      const chunkCount = numValue(stats.chunk_count ?? stats.total_chunks)
      const sectionCount = numValue(stats.section_count ?? stats.sections)
      const parsedDocs = (task as ReviewPlusTaskDetail & { parsed_documents?: unknown[] }).parsed_documents
      const parsedLen = Array.isArray(parsedDocs) ? parsedDocs.length : 0
      if (chunkCount) metrics.push({ label: '语块', value: chunkCount })
      if (sectionCount) metrics.push({ label: '章节', value: sectionCount })
      if (parsedLen) metrics.push({ label: '解析批次', value: parsedLen })
      const warnings = Array.isArray(payload.warnings) ? payload.warnings : []
      if (warnings.length > 0) {
        metrics.push({ label: '告警', value: warnings.length, tone: 'warning' })
        highlights.push(`结构化过程产生 ${warnings.length} 条告警，建议在送审包中核对。`)
      }
      summaryLines.push('已完成待审文档的章节树与证据池构建。')
      break
    }
    case 'chief_orchestration': {
      const plan = task.chief_review_plan || {}
      const formatReview = task.document_format_review || {}
      const agents = Array.isArray(plan.selected_agents) ? plan.selected_agents : []
      const specialists = task.specialist_reviews || []
      const formatFindings = Array.isArray(formatReview.findings) ? formatReview.findings : []
      metrics.push({ label: '预审方向', value: agents.length || specialists.length || numValue(payload.agent_count) })
      metrics.push({ label: '格式问题', value: formatFindings.length || numValue(payload.document_format_finding_count) })
      const gate = textValue(formatReview.gate_status || payload.document_format_gate_status)
      if (gate) metrics.push({ label: '格式门禁', value: gate, tone: gate === 'passed' ? 'success' : 'warning' })
      const focusQuestions = Array.isArray(plan.focus_questions) ? plan.focus_questions : []
      if (focusQuestions.length > 0) {
        highlights.push(`本轮聚焦 ${Math.min(focusQuestions.length, 4)} 个审查问题。`)
      }
      for (const raw of (agents.length ? agents : specialists).slice(0, 4)) {
        const rec = asRecord(raw)
        const name = textValue(rec.agent_name || rec.specialist_name, '预审方向')
        const reason = textValue(rec.reason || rec.assignment_reason)
        if (name) highlights.push(`${name}${reason ? `：${reason}` : ''}`)
      }
      summaryLines.push('已完成送审包格式审查与预审分工建议；动态审查组将在下一步「动态组队符合性审查」中生成。')
      break
    }
    case 'rule_extraction': {
      const count = task.check_items?.length ?? numValue(payload.check_item_count)
      metrics.push({ label: '检查项', value: count, tone: count > 0 ? 'brand' : 'warning' })
      if (payload.warning) highlights.push(textValue(payload.warning))
      if (count > 0) summaryLines.push(`从规则材料抽取 ${count} 条可审查检查项。`)
      else summaryLines.push('未识别到检查项，后续审查结果可能受限。')
      break
    }
    case 'rule_section_mapping': {
      const mappings = task.section_mappings || []
      const mapped = mappings.filter((m) => {
        const rec = asRecord(m)
        const sections = Array.isArray(rec.section_ids) ? rec.section_ids : []
        return sections.length > 0
      }).length
      const total = task.check_items?.length ?? numValue(payload.total_count)
      metrics.push({ label: '已映射', value: `${mapped}/${total || mappings.length}` })
      if (payload.avg_confidence != null) {
        metrics.push({ label: '平均置信度', value: percentValue(payload.avg_confidence) })
      }
      summaryLines.push(mapped > 0
        ? `${mapped} 条检查项已关联到文档章节与证据。`
        : '检查项与文档章节的映射尚未完成。')
      break
    }
    case 'item_review': {
      const harnessPlan = getHarnessPlan(task)
      const traces = task.agent_run_traces || []
      const matrix = task.coverage_matrix
      const harnessMetrics = buildHarnessSummaryMetrics(harnessPlan, traces, matrix)

      if (hasHarnessArtifacts(task)) {
        metrics.push({ label: '选中环节', value: harnessMetrics.selectedCount, tone: 'brand' })
        metrics.push({ label: '核心必选', value: harnessMetrics.requiredCount })
        metrics.push({ label: '执行完成', value: harnessMetrics.traceCompleted, tone: 'success' })
        if (harnessMetrics.traceFailed > 0) {
          metrics.push({ label: '执行失败', value: harnessMetrics.traceFailed, tone: 'danger' })
        }
        metrics.push({ label: COVERAGE_STATUS_LABELS.closed, value: harnessMetrics.closedCount, tone: 'success' })
        metrics.push({
          label: COVERAGE_STATUS_LABELS.missing,
          value: harnessMetrics.missingCount,
          tone: harnessMetrics.missingCount > 0 ? 'danger' : 'default',
        })
        metrics.push({ label: COVERAGE_STATUS_LABELS.task_only, value: harnessMetrics.taskOnlyCount, tone: 'warning' })
        metrics.push({ label: COVERAGE_STATUS_LABELS.subject_only, value: harnessMetrics.subjectOnlyCount, tone: 'warning' })

        for (const item of pickTopSelectionReasons(harnessPlan, 3)) {
          highlights.push(`${item.label}：${item.reason}`)
        }
        summaryLines.push('动态组队审查已执行，下方为组队与覆盖结果。')
      }

      const findings = task.findings || []
      const counts = { satisfied: 0, not_satisfied: 0, insufficient_evidence: 0, not_checked: 0 }
      for (const f of findings) {
        const j = String(f.judgment || 'not_checked') as keyof typeof counts
        if (j in counts) counts[j] += 1
      }
      if (!hasHarnessArtifacts(task)) {
        metrics.push({ label: '审查记录', value: findings.length || numValue(payload.finding_count) })
        metrics.push({ label: '满足', value: counts.satisfied || numValue(payload.satisfied), tone: 'success' })
        metrics.push({
          label: '不满足',
          value: counts.not_satisfied || numValue(payload.not_satisfied),
          tone: counts.not_satisfied > 0 ? 'danger' : 'default',
        })
        metrics.push({
          label: '证据不足',
          value: counts.insufficient_evidence || numValue(payload.insufficient),
          tone: counts.insufficient_evidence > 0 ? 'warning' : 'default',
        })
        summaryLines.push('已完成检查项的逐项符合性判定。')
      } else if (findings.length > 0) {
        metrics.push({ label: '审查记录', value: findings.length })
        const critical = findings.filter((f) => String(f.severity) === 'critical').length
        if (critical > 0) {
          metrics.push({ label: '关键', value: critical, tone: 'danger' })
          highlights.push(`发现 ${critical} 条关键级别审查记录。`)
        }
      }
      break
    }
    case 'traceability': {
      const summary = asRecord(asRecord(task.traceability_result).summary)
      metrics.push({ label: '需求', value: numValue(summary.requirement_count ?? payload.requirement_count) })
      metrics.push({ label: '追溯链', value: numValue(summary.trace_link_count ?? payload.trace_link_count) })
      metrics.push({
        label: '设计闭合',
        value: percentValue(summary.design_closure_coverage ?? payload.design_closure_coverage),
      })
      metrics.push({
        label: '验证覆盖',
        value: percentValue(summary.verification_coverage ?? payload.verification_coverage),
      })
      summaryLines.push('已构建需求—设计—验证闭环追溯矩阵。')
      break
    }
    case 'cross_document_review': {
      const items = task.cross_document_review_items || []
      const open = items.filter((item) => !['closed', 'resolved'].includes(String(item.status || 'open'))).length
      metrics.push({ label: '问题项', value: items.length })
      metrics.push({ label: '待闭环', value: open, tone: open > 0 ? 'danger' : 'success' })
      summaryLines.push(open > 0
        ? `跨文档一致性审查发现 ${open} 项待闭环问题。`
        : '跨文档一致性审查未发现待处理问题。')
      break
    }
    case 'report_composition': {
      const report = task.report
      if (report) {
        metrics.push({ label: '检查项', value: report.total_check_items ?? task.check_items?.length ?? 0 })
        metrics.push({ label: '不满足', value: report.not_satisfied_count ?? 0, tone: 'danger' })
        metrics.push({ label: '证据不足', value: report.insufficient_evidence_count ?? 0, tone: 'warning' })
        const chiefCount = report.chief_comprehensive_review?.engineering_conclusions?.length ?? 0
        if (chiefCount > 0) {
          metrics.push({ label: '工程结论', value: chiefCount, tone: 'warning' })
        }
        if (report.chief_comprehensive_review?.overall_assessment) {
          summaryLines.push(report.chief_comprehensive_review.overall_assessment)
        } else if (report.conclusion) summaryLines.push(report.conclusion)
        else if (report.summary) summaryLines.push(report.summary)
      } else {
        summaryLines.push('审查报告生成中或尚未产出。')
      }
      break
    }
    default:
      break
  }

  return { summaryLines: summaryLines.filter(Boolean), metrics, highlights }
}

function buildNotSatisfiedFindingPreviews(task: ReviewPlusTaskDetail): ReviewPlusStepFindingPreview[] {
  const checkItems = task.check_items || []
  const checkItemMap = new Map(checkItems.map((item) => [item.check_item_id, item]))
  const indexMap = buildReviewPlusCheckItemIndexMap(checkItems)
  return (task.findings || [])
    .filter((f) => String(f.judgment) === 'not_satisfied')
    .slice(0, 8)
    .map((finding) => {
      const item = checkItemMap.get(finding.check_item_id)
      const index = indexMap.get(finding.check_item_id)
      return {
        id: finding.finding_id || finding.check_item_id,
        title: resolveReviewPlusFindingTitle(
          finding,
          item || { check_item_id: finding.check_item_id, title: '' },
          index,
        ),
        subtitle: finding.reasoning || finding.recommendation || undefined,
        tone: String(finding.severity) === 'critical' ? 'danger' as const : 'warning' as const,
      }
    })
}

function buildStepFindingPreviews(
  stepKey: ReviewPlusPipelineStepKey,
  task: ReviewPlusTaskDetail,
): ReviewPlusStepFindingPreview[] {
  if (stepKey === 'document_structuring') {
    const completeEvent = [...(task.events || [])]
      .reverse()
      .find((event) => String(event.type || '') === 'document_structuring_completed')
    const payload = asRecord(completeEvent?.payload)
    const warnings = (Array.isArray(payload.warnings) ? payload.warnings : [])
      .map((warning) => String(warning || '').trim())
      .filter(Boolean)
    if (warnings.length > 0) {
      return [{
        id: 'structuring-warnings',
        title: `文档结构化产生 ${warnings.length} 条告警`,
        subtitle: warnings.slice(0, 2).join('；'),
        tone: 'warning',
      }]
    }
    return []
  }

  if (stepKey === 'chief_orchestration') {
    const formatReview = task.document_format_review || {}
    const formatFindings = Array.isArray(formatReview.findings) ? formatReview.findings : []
    const previews = formatFindings.slice(0, 6).map((raw, index) => {
      const item = asRecord(raw)
      return {
        id: String(item.finding_id || item.id || `format-${index}`),
        title: textValue(item.title || item.summary, '送审包格式问题'),
        subtitle: textValue(item.description || item.recommendation || item.reason) || undefined,
        tone: String(item.severity) === 'critical' ? 'danger' as const : 'warning' as const,
      }
    })
    const gate = textValue(formatReview.gate_status)
    if (gate && gate !== 'passed' && previews.length === 0) {
      previews.push({
        id: 'format-gate-blocked',
        title: '送审包格式门禁未通过',
        subtitle: textValue((formatReview as any).gate_summary || formatReview.summary) || '请先修复格式问题后继续审查。',
        tone: 'warning',
      })
    }
    return previews
  }

  if (stepKey === 'item_review') {
    const previews: ReviewPlusStepFindingPreview[] = []

    if (hasHarnessArtifacts(task)) {
      for (const trace of task.agent_run_traces || []) {
        if (String(trace.status || '') !== 'failed') continue
        previews.push({
          id: `trace-failed-${trace.agent_id}`,
          title: `${formatAgentIdLabel(trace.agent_id)} 执行失败`,
          subtitle: textValue(trace.error_message || trace.error_code, '审查环节未完成，请查看执行轨迹详情。'),
          tone: 'danger',
        })
      }

      const summary = task.coverage_matrix?.summary || {}
      const missingCount = numValue(summary.missing_count)
      const taskOnlyCount = numValue(summary.task_only_count)
      const subjectOnlyCount = numValue(summary.subject_only_count)

      if (missingCount > 0) {
        previews.push({
          id: 'coverage-missing',
          title: `${missingCount} 条检查项缺少双向证据`,
          subtitle: '覆盖状态为缺失，需在覆盖矩阵中补证或确认不适用。',
          tone: 'danger',
        })
      }
      if (taskOnlyCount > 0) {
        previews.push({
          id: 'coverage-task-only',
          title: `${taskOnlyCount} 条检查项仅有任务书依据`,
          subtitle: '被审报告/待审文档缺少直接印证。',
          tone: 'warning',
        })
      }
      if (subjectOnlyCount > 0) {
        previews.push({
          id: 'coverage-subject-only',
          title: `${subjectOnlyCount} 条检查项仅有报告证据`,
          subtitle: '任务书依据不足，证据链未闭合。',
          tone: 'warning',
        })
      }
    }

    previews.push(...buildNotSatisfiedFindingPreviews(task))
    return previews
  }

  if (stepKey === 'cross_document_review') {
    return (task.cross_document_review_items || [])
      .filter((item) => !['closed', 'resolved'].includes(String(item.status || 'open')))
      .slice(0, 6)
      .map((item, index) => ({
        id: String(item.item_id || item.id || index),
        title: String(item.title || item.name || '跨文档问题'),
        subtitle: String(item.summary || item.description || '') || undefined,
        tone: 'warning' as const,
      }))
  }

  return []
}

function buildStepRecentEvents(
  stepEvents: ReviewPlusEvent[],
): ReviewPlusStepEventLine[] {
  return [...stepEvents]
    .sort((a, b) => numValue(b.sequence) - numValue(a.sequence))
    .slice(0, 5)
    .map((event) => {
      const payload = asRecord(event.payload)
      const type = String(event.type || '')
      return {
        type,
        label: formatReviewPlusEventLabel(type),
        summary: formatEventPayloadSummary(type, payload),
        at: formatTime(event.created_at),
      }
    })
    .filter((line) => line.label || line.summary)
}

export function buildReviewPlusStepDetail(
  stepKey: ReviewPlusPipelineStepKey,
  task: ReviewPlusTaskDetail,
  nodeStatus: WorkflowStepStatus,
  node?: {
    started_at?: string | null
    completed_at?: string | null
    blocked_reason?: string
    output_summary?: string | null
  },
): ReviewPlusStepDetail {
  const stepDef = REVIEW_PLUS_PIPELINE_STEPS.find((s) => s.step_key === stepKey)
  const label = stepDef?.label || stepKey
  const description = stepDef?.description || ''
  const stepEvents = eventsForStep(task.events || [], stepKey)
  const completeEv = latestCompleteEvent(stepEvents, stepDef?.completeEvent || '')
  const startEv = stepDef?.startEvent
    ? stepEvents.find((e) => String(e.type || '') === stepDef.startEvent)
    : null
  const payload = asRecord((completeEv || latestEvent(stepEvents))?.payload)
  const eventSummary = completeEv
    ? formatEventPayloadSummary(String(completeEv.type || ''), payload)
    : ''

  const domain = buildStepDomainDetail(stepKey, task, payload)
  const summaryLines = [...domain.summaryLines]
  if (eventSummary && !summaryLines.some((line) => line.includes(eventSummary.slice(0, 20)))) {
    summaryLines.unshift(eventSummary)
  }

  const highlights = [...domain.highlights]
  if (node?.blocked_reason) highlights.unshift(node.blocked_reason)
  const outputSummary = textValue(node?.output_summary)
  if (outputSummary && !summaryLines.includes(outputSummary)) {
    summaryLines.push(outputSummary)
  }

  let pendingHint: string | undefined
  if (nodeStatus === 'pending') {
    pendingHint = `尚未执行。${description}`
  } else if (nodeStatus === 'running') {
    pendingHint = '正在执行本步骤，完成后将展示详细指标。'
  }

  const showHarnessPanel = stepKey === 'item_review' && hasHarnessArtifacts(task)
  const relatedTab = stepKey === 'item_review' && showHarnessPanel
    ? 'coverage' as ReviewPlusWorkbenchTabKey
    : workflowStepToWorkbenchTab(stepKey)

  return {
    stepKey,
    label,
    description,
    status: nodeStatus,
    statusLabel: STEP_STATUS_LABELS[nodeStatus] || nodeStatus,
    startedAt: node?.started_at || startEv?.created_at || undefined,
    completedAt: node?.completed_at || completeEv?.created_at || undefined,
    summaryLines: summaryLines.filter(Boolean),
    metrics: domain.metrics,
    highlights,
    findingPreviews: buildStepFindingPreviews(stepKey, task),
    recentEvents: buildStepRecentEvents(stepEvents),
    outputSummary: outputSummary || undefined,
    relatedTab,
    pendingHint,
    showHarnessPanel,
  }
}

/** 用于 workflow graph 节点收起态的一行摘要 */
export function buildReviewPlusStepOutputSummary(
  stepKey: ReviewPlusPipelineStepKey,
  task: ReviewPlusTaskDetail,
  nodeStatus: WorkflowStepStatus,
  latestPayload?: Record<string, unknown>,
): string {
  const detail = buildReviewPlusStepDetail(stepKey, task, nodeStatus, {
    blocked_reason: textValue(latestPayload?.error),
  })
  if (detail.summaryLines[0]) return detail.summaryLines[0]
  if (detail.metrics.length > 0) {
    return detail.metrics.slice(0, 3).map((m) => `${m.label} ${m.value}`).join(' · ')
  }
  if (nodeStatus === 'pending') return detail.description
  if (nodeStatus === 'running') return '执行中…'
  return detail.description
}

export function formatStepTimeRange(detail: ReviewPlusStepDetail): string {
  const start = formatTime(detail.startedAt)
  const end = formatTime(detail.completedAt)
  if (start && end) return `${start} → ${end}`
  if (end) return `完成 ${end}`
  if (start) return `开始 ${start}`
  return ''
}
