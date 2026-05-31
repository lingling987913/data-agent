'use client'

import { forwardRef, useImperativeHandle, useRef } from 'react'
import MarkdownRenderer from '@aqua/ui-core/typography/MarkdownRenderer'
import type { ReviewPlusTaskDetail } from '@/features/review-plus-v2/types'

export interface ReviewPlusConclusionPanelHandle {
  expandFullReport: () => void
}

type ReviewPlusConclusionPanelProps = {
  task: ReviewPlusTaskDetail
  markdown: string
}

/** 深读层：剩余风险 + 折叠完整报告正文（统计与待办由 Overview 总览区承担） */
const ReviewPlusConclusionPanel = forwardRef<ReviewPlusConclusionPanelHandle, ReviewPlusConclusionPanelProps>(
  function ReviewPlusConclusionPanel({ task, markdown }, ref) {
    const report = task.report
    const fullReportDetailsRef = useRef<HTMLDetailsElement | null>(null)
    const residualRisks = report?.residual_risks || []

    useImperativeHandle(ref, () => ({
      expandFullReport: () => {
        const el = fullReportDetailsRef.current
        if (!el) return
        el.open = true
        el.scrollIntoView({ behavior: 'smooth', block: 'start' })
      },
    }))

    if (!report && !markdown) {
      return (
        <section className="aq-soft-panel rounded-xl p-6 text-center">
          <p className="text-[13px] font-medium text-primary">报告尚未生成</p>
          <p className="mt-2 text-[11px] leading-relaxed text-muted">
            审查完成后将在此展示完整报告正文；归档导出请使用右上角「导出报告」。
          </p>
        </section>
      )
    }

    return (
      <div className="space-y-3">
        {residualRisks.length > 0 ? (
          <details className="aq-soft-panel group rounded-xl p-4">
            <summary className="flex cursor-pointer list-none items-center justify-between gap-3">
              <h2 className="text-sm font-medium text-primary">剩余风险</h2>
              <span className="text-[10px] text-muted">{residualRisks.length} 项 · 点击展开</span>
            </summary>
            <ul className="mt-4 space-y-1.5 border-t border-border/15 pt-4">
              {residualRisks.map((risk, i) => (
                <li key={i} className="flex items-start gap-2 text-[11px] leading-relaxed text-destructive/80">
                  <span className="mt-1.5 size-1 shrink-0 rounded-full bg-destructive/50" />
                  <span>{risk}</span>
                </li>
              ))}
            </ul>
          </details>
        ) : null}

        <details
          id="review-plus-full-report"
          ref={fullReportDetailsRef}
          className="aq-soft-panel group rounded-xl p-4"
          data-testid="review-plus-full-report"
        >
          <summary className="flex cursor-pointer list-none items-center justify-between gap-3">
            <h2 className="text-sm font-medium text-primary">完整报告正文</h2>
            <span className="text-[10px] text-muted group-open:hidden">点击展开</span>
            <span className="hidden text-[10px] text-muted group-open:inline">点击收起</span>
          </summary>
          <div className="mt-4 border-t border-border/15 pt-4">
            {markdown ? (
              <div className="prose prose-sm max-w-none">
                <MarkdownRenderer>{markdown}</MarkdownRenderer>
              </div>
            ) : (
              <p className="text-[11px] text-muted">报告正文尚未生成，请稍后刷新或查看执行日志。</p>
            )}
          </div>
        </details>
      </div>
    )
  },
)

export default ReviewPlusConclusionPanel
