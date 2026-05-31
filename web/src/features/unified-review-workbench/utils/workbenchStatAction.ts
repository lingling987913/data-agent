import type { UnifiedReviewWorkbenchDetail, UnifiedWorkbenchTabKey } from '@/features/unified-review-workbench/types'
import { normalizeBucketKey } from '@/features/unified-review-workbench/utils/bucketTone'
import { resolveBucketFilterLabel } from '@/features/unified-review-workbench/utils/findingsBucketFilter'

/** Super Agent 工作台可点击统计项标识 */
export type SuperAgentStatKey =
  | 'run_status'
  | 'workbench_phase'
  | 'material_count'
  | 'review_route_label'
  | 'finding_count'
  | 'pending_confirm'
  | 'quality_status'
  | 'coverage_check_items'
  | 'coverage_verified'
  | 'coverage_evidence'
  | 'coverage_rate'
  | 'quality_parse'
  | 'quality_execution'
  | 'quality_evidence'
  | 'quality_output'
  | 'quality_degradation'
  | 'quality_trace'
  | 'routes_overview'
  | 'routes_flow'
  | 'routes_committee'
  | 'routes_events'
  | 'materials_count'
  | 'findings_total'
  | 'closure_buckets'

export interface WorkbenchStatAction {
  tab: UnifiedWorkbenchTabKey
  bucket?: string | null
  anchor?: string
  hint?: string
  disabled?: boolean
}

export interface WorkbenchNavigateOptions {
  bucket?: string | null
  hint?: string
  anchor?: string
}

const BUCKET_STAT_PREFIX = 'bucket:'

export function isBucketStatKey(key: string): boolean {
  return key.startsWith(BUCKET_STAT_PREFIX)
}

export function bucketKeyFromStatKey(key: string): string | null {
  if (!isBucketStatKey(key)) return null
  const raw = key.slice(BUCKET_STAT_PREFIX.length).trim()
  return normalizeBucketKey(raw) || null
}

export function statKeyForBucket(bucketKey: string): string {
  return `${BUCKET_STAT_PREFIX}${normalizeBucketKey(bucketKey) || bucketKey}`
}

function pendingConfirmCount(detail: UnifiedReviewWorkbenchDetail): number {
  const openRid = Number(detail.metrics.open_rid_count) || 0
  const manual = Number(detail.conclusion_overview?.issue_buckets?.manual_review) || 0
  return openRid + manual
}

function qualityLandingHint(detail: UnifiedReviewWorkbenchDetail): string {
  if (detail.workbench_phase === 'failed') return '运行失败，请查看运行质量中的异常与 Trace。'
  if (detail.error) return '运行存在需关注项，请查看运行质量详情。'
  return '查看解析质量、输出完整性与 Trace 记录。'
}

/** 将统计项映射为 Tab 跳转 / 分桶筛选 / 页内锚点 */
export function resolveSuperAgentStatAction(
  key: SuperAgentStatKey | string,
  detail?: UnifiedReviewWorkbenchDetail,
): WorkbenchStatAction | null {
  const bucketFromKey = bucketKeyFromStatKey(key)
  if (bucketFromKey) {
    const label = resolveBucketFilterLabel(bucketFromKey)
    return {
      tab: 'findings',
      bucket: bucketFromKey,
      hint: `已按「${label}」筛选发现与证据明细。`,
    }
  }

  switch (key as SuperAgentStatKey) {
    case 'run_status':
      return {
        tab: 'quality',
        anchor: 'quality-trace',
        hint: '查看运行状态对应的 Trace 与异常记录。',
      }
    case 'workbench_phase':
      return {
        tab: 'routes',
        anchor: 'routes-flow',
        hint: '查看当前阶段的执行节点与流程进度。',
      }
    case 'material_count':
    case 'materials_count':
      return {
        tab: 'materials',
        hint: '查看送审材料、解析状态与结构化摘要。',
      }
    case 'review_route_label':
    case 'routes_overview':
      return {
        tab: 'routes',
        hint: '查看审查路线、路由决策与执行节点。',
      }
    case 'finding_count':
    case 'findings_total':
      return {
        tab: 'findings',
        hint: '查看全部问题、检查项与证据摘录。',
      }
    case 'pending_confirm': {
      const count = detail ? pendingConfirmCount(detail) : 0
      return {
        tab: 'findings',
        bucket: 'manual_review',
        hint: count > 0
          ? '已筛选待人工确认分桶；开放 RID 明细需后端补充投影。'
          : '暂无待确认统计，可查看全部发现。',
        disabled: detail ? count <= 0 : false,
      }
    }
    case 'quality_status':
      return {
        tab: 'quality',
        hint: detail ? qualityLandingHint(detail) : '查看运行质量详情。',
      }
    case 'coverage_check_items':
      return {
        tab: 'findings',
        hint: '检查项明细在发现与证据页展示；可按分桶进一步筛选。',
      }
    case 'coverage_verified':
      return {
        tab: 'findings',
        bucket: 'verified',
        hint: '已筛选「已通过/已印证」分桶。',
      }
    case 'coverage_evidence':
      return {
        tab: 'findings',
        hint: '证据条数对应证据摘录；若列表为空请查看运行质量中的输出完整性。',
      }
    case 'coverage_rate':
      return {
        tab: 'findings',
        hint: '覆盖率由检查项与证据汇总；请在发现与证据中核对明细。',
      }
    case 'quality_parse':
      return { tab: 'quality', anchor: 'quality-parse', hint: '查看解析质量指标。' }
    case 'quality_execution':
      return { tab: 'quality', anchor: 'quality-execution', hint: '查看执行质量综合得分。' }
    case 'quality_evidence':
      return { tab: 'quality', anchor: 'quality-evidence', hint: '查看证据质量与条数。' }
    case 'quality_output':
      return { tab: 'quality', anchor: 'quality-output', hint: '查看输出完整性与报告状态。' }
    case 'quality_degradation':
      return { tab: 'quality', anchor: 'quality-degradation', hint: '查看链路降级说明。' }
    case 'quality_trace':
      return { tab: 'quality', anchor: 'quality-trace', hint: '查看运行 Trace 与异常记录。' }
    case 'routes_flow':
      return { tab: 'routes', anchor: 'routes-flow', hint: '查看执行流程与各步骤状态。' }
    case 'routes_committee':
      return { tab: 'routes', anchor: 'routes-committee', hint: '查看总师调度与审查单元输出。' }
    case 'routes_events':
      return { tab: 'routes', anchor: 'routes-events', hint: '查看阶段性输出与 Trace 事件。' }
    case 'closure_buckets':
      return {
        tab: 'closure',
        hint: '完整裁定与分桶统计在结论与闭环页；可再跳转发现与证据查看明细。',
      }
    default:
      return null
  }
}

export function resolveStatActionAriaLabel(
  label: string,
  action: WorkbenchStatAction | null | undefined,
): string {
  if (!action || action.disabled) return `${label}：暂无下钻`
  const tabHints: Record<string, string> = {
    materials: '材料与底稿',
    routes: '审查路线',
    findings: '发现与证据',
    closure: '结论与闭环',
    quality: '运行质量',
    overview: '总览',
  }
  const target = tabHints[action.tab] || action.tab
  if (action.bucket) {
    return `${label}：跳转到${target}并按分桶筛选`
  }
  return `${label}：跳转到${target}`
}
