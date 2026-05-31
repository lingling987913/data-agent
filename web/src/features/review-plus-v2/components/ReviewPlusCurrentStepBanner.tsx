'use client'

import { REVIEW_PLUS_PIPELINE_STEPS } from '@/features/review-plus-v2/utils/reviewPlusPipeline'
import type { ReviewPlusWorkbenchTabKey } from '@/features/review-plus-v2/utils/reviewPlusPipeline'
import { STEP_STATUS_LABELS } from '@aqua/workflow-core'
import type { WorkflowStepStatus } from '@aqua/workflow-core'

interface Props {
  currentStepKey: string
  currentStepLabel: string
  stepStatus?: WorkflowStepStatus
  notSatisfiedCount: number
  criticalCount: number
  crossDocOpenCount: number
  visibleTabs: Set<ReviewPlusWorkbenchTabKey>
  isExecuting: boolean
  variant?: 'session' | 'workbench'
  showIssueChips?: boolean
  onOpenTab?: (tab: ReviewPlusWorkbenchTabKey, options?: { judgmentFilter?: 'not_satisfied' }) => void
}

export default function ReviewPlusCurrentStepBanner({
  currentStepKey,
  currentStepLabel,
  stepStatus = 'pending',
  notSatisfiedCount,
  criticalCount,
  crossDocOpenCount,
  visibleTabs,
  isExecuting,
  variant = 'session',
  showIssueChips = true,
  onOpenTab,
}: Props) {
  const stepIndex = REVIEW_PLUS_PIPELINE_STEPS.findIndex((step) => step.step_key === currentStepKey)
  const stepNumber = stepIndex >= 0 ? stepIndex + 1 : 0
  const totalSteps = REVIEW_PLUS_PIPELINE_STEPS.length
  const statusLabel = STEP_STATUS_LABELS[stepStatus] || stepStatus

  const chips: Array<{
    key: string
    label: string
    tab: ReviewPlusWorkbenchTabKey
    filter?: 'not_satisfied'
    tone: string
    visible: boolean
  }> = [
    {
      key: 'not-satisfied',
      label: `不满足 ${notSatisfiedCount}`,
      tab: 'findings',
      filter: 'not_satisfied',
      tone: 'border-destructive/25 bg-destructive/8 text-destructive',
      visible: notSatisfiedCount > 0,
    },
    {
      key: 'critical',
      label: `关键 ${criticalCount}`,
      tab: 'findings',
      filter: 'not_satisfied',
      tone: 'border-destructive/25 bg-destructive/10 text-destructive',
      visible: criticalCount > 0,
    },
    {
      key: 'cross-doc',
      label: `跨文档待闭环 ${crossDocOpenCount}`,
      tab: 'cross_doc',
      tone: 'border-warning/25 bg-warning/8 text-warning',
      visible: crossDocOpenCount > 0,
    },
  ]

  return (
    <div
      className="flex shrink-0 flex-col gap-2 rounded-lg border border-border/20 bg-background px-4 py-2.5"
      data-testid="review-plus-current-step-banner"
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="rounded-full border border-primaryAccent/20 bg-primaryAccent/8 px-2.5 py-1 text-[10px] font-medium text-primaryAccent">
          {isExecuting ? '正在执行' : '当前步骤'}
        </span>
        <span className="text-[11px] font-medium text-primary">
          {currentStepLabel}
          {stepNumber > 0 ? (
            <span className="ml-1.5 font-normal text-muted">· 第 {stepNumber}/{totalSteps} 步</span>
          ) : null}
        </span>
        <span className="rounded-full border border-border/25 bg-surface px-2 py-0.5 text-[9px] text-muted">
          {statusLabel}
        </span>
      </div>

      {variant === 'workbench' && isExecuting ? (
        <p className="text-[10px] text-muted">
          审查进行中。若长时间无变化，请使用右上角「继续处理」。
        </p>
      ) : null}

      {showIssueChips ? (
      <div className="flex flex-wrap gap-1.5">
        {chips.filter((chip) => chip.visible).map((chip) => {
          const canNavigate = visibleTabs.has(chip.tab) && onOpenTab
          if (!canNavigate) {
            return (
              <span
                key={chip.key}
                className={`inline-flex items-center rounded-full border px-2.5 py-1 text-[9px] font-medium ${chip.tone}`}
              >
                {chip.label}
              </span>
            )
          }
          return (
            <button
              key={chip.key}
              type="button"
              onClick={() => onOpenTab(chip.tab, chip.filter ? { judgmentFilter: chip.filter } : undefined)}
              className={`inline-flex min-h-7 items-center rounded-full border px-2.5 py-1 text-[9px] font-medium transition-colors hover:opacity-90 ${chip.tone}`}
              data-testid={`review-plus-banner-chip-${chip.key}`}
            >
              {chip.label}
            </button>
          )
        })}
      </div>
      ) : null}
    </div>
  )
}
