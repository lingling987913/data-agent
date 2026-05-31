'use client'

import { useEffect, useMemo, useRef, useState } from 'react'
import ActionEmptyState from '@/features/review-plus-v2/components/workbench/ActionEmptyState'
import ResultSummaryBar from '@/features/review-plus-v2/components/workbench/ResultSummaryBar'
import type { ReviewPlusEvent } from '@/features/review-plus-v2/types'
import {
  REVIEW_PLUS_PIPELINE_STEPS,
  formatReviewPlusEventLabel,
  inferReviewPlusStepKeyFromEvent,
} from '@/features/review-plus-v2/utils/reviewPlusPipeline'

function formatEventTime(createdAt?: string): string {
  if (!createdAt) return '—'
  try {
    return new Date(createdAt).toLocaleString('zh-CN', {
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    })
  } catch {
    return createdAt
  }
}

function eventColorClass(eventType: string): string {
  const type = String(eventType || '').toLowerCase()
  if (type.includes('fail') || type.includes('error')) return 'text-destructive'
  if (type.includes('complet') || type.includes('success') || type.includes('done')) return 'text-positive'
  if (type.includes('start') || type.includes('progress') || type.includes('ing')) return 'text-primaryAccent'
  if (type.includes('warning') || type.includes('condition') || type.includes('limited')) return 'text-warning'
  return 'text-primary'
}

export default function ReviewPlusEventsTab({ events }: { events: ReviewPlusEvent[] }) {
  const [eventTypeFilter, setEventTypeFilter] = useState('all')
  const [autoScroll, setAutoScroll] = useState(true)
  const containerRef = useRef<HTMLDivElement>(null)
  const endRef = useRef<HTMLDivElement>(null)

  const sorted = useMemo(
    () => [...events].sort((a, b) => {
      const seqA = Number(a.sequence || 0)
      const seqB = Number(b.sequence || 0)
      return seqB - seqA
    }),
    [events],
  )

  const eventTypes = useMemo(() => {
    const types = new Set(sorted.map((e) => String(e.type || '')))
    return Array.from(types).sort()
  }, [sorted])

  const filteredEvents = useMemo(() => {
    if (eventTypeFilter === 'all') return sorted
    return sorted.filter((e) => String(e.type || '') === eventTypeFilter)
  }, [sorted, eventTypeFilter])

  const grouped = useMemo(() => {
    const byStep = new Map<string, ReviewPlusEvent[]>()
    for (const event of filteredEvents) {
      const stepKey = inferReviewPlusStepKeyFromEvent(String(event.type || '')) || '_other'
      const list = byStep.get(stepKey) || []
      list.push(event)
      byStep.set(stepKey, list)
    }
    return byStep
  }, [filteredEvents])

  const failedCount = sorted.filter((e) => String(e.type || '').toLowerCase().includes('fail')).length

  useEffect(() => {
    if (autoScroll && endRef.current) {
      endRef.current.scrollIntoView({ behavior: 'smooth', block: 'end' })
    }
  }, [filteredEvents.length, autoScroll])

  if (!sorted.length) {
    return (
      <ActionEmptyState
        title="暂无执行事件"
        description="任务操作与审查九步链路将记录在此，便于跟踪处理进度。"
        hint="事件会在审查启动后开始记录。"
      />
    )
  }

  return (
    <div className="max-w-4xl space-y-4">
      <ResultSummaryBar
        items={[
          { label: '事件数', value: sorted.length, tone: 'brand' },
          { label: '失败', value: failedCount, tone: failedCount > 0 ? 'danger' : 'default' },
          { label: '当前显示', value: filteredEvents.length, tone: 'default' },
        ]}
        hint="按审查执行链路分组展示；最新事件排在各组前列。"
        actions={
          <label className="flex items-center gap-2 text-[10px] text-muted cursor-pointer">
            <input
              type="checkbox"
              checked={autoScroll}
              onChange={(e) => setAutoScroll(e.target.checked)}
              className="rounded border-border/30"
            />
            自动滚动
          </label>
        }
      />

      <div className="flex flex-wrap gap-2 items-center">
        <select
          value={eventTypeFilter}
          onChange={(e) => setEventTypeFilter(e.target.value)}
          className="rounded-xl border border-border/25 bg-surface px-3 py-1.5 text-[11px] text-primary focus:border-primaryAccent/40 focus:outline-none"
        >
          <option value="all">全部事件类型</option>
          {eventTypes.map((type) => (
            <option key={type} value={type}>{formatReviewPlusEventLabel(type)}</option>
          ))}
        </select>
      </div>

      <div ref={containerRef} className="space-y-4">
        {REVIEW_PLUS_PIPELINE_STEPS.map((step) => {
          const stepEvents = grouped.get(step.step_key)
          if (!stepEvents?.length) return null

          return (
            <section key={step.step_key} className="space-y-2">
              <div className="flex items-center gap-2 px-1">
                <div className="w-2 h-2 rounded-full bg-primaryAccent/50" />
                <h3 className="text-[11px] font-medium text-primary">{step.label}</h3>
                <span className="text-[10px] text-muted/70">{step.description}</span>
                <span className="ml-auto text-[9px] text-muted">({stepEvents.length} 条)</span>
              </div>

              <div className="relative pl-4 space-y-1.5 before:absolute before:left-0 before:top-2 before:bottom-2 before:w-px before:bg-border/10">
                {stepEvents.map((event, index) => {
                  const type = String(event.type || '')
                  const payload = (event.payload || {}) as Record<string, unknown>
                  const detail = String(payload.summary || payload.error || payload.detail || payload.message || '')
                  const colorClass = eventColorClass(type)

                  return (
                    <details
                      key={`${step.step_key}-${event.sequence}-${index}`}
                      className="group aq-soft-panel rounded-xl px-4 py-3 text-[11px]"
                    >
                      <summary className="flex cursor-pointer list-none flex-wrap items-start justify-between gap-2">
                        <div className="flex items-start gap-2 min-w-0 flex-1">
                          <div className="w-1.5 h-1.5 rounded-full bg-border/30 mt-1.5 shrink-0" />
                          <div className="min-w-0 flex-1">
                            <div className={`font-medium ${colorClass}`}>
                              {formatReviewPlusEventLabel(type)}
                            </div>
                            {detail ? (
                              <p className="mt-1 text-[10px] leading-relaxed text-muted line-clamp-2">{detail}</p>
                            ) : null}
                          </div>
                        </div>
                        <span className="shrink-0 tabular-nums text-[9px] text-muted">
                          {formatEventTime(event.created_at)}
                        </span>
                      </summary>

                      <div className="mt-3 pl-4 space-y-2 border-l-2 border-border/10">
                        {event.created_at && (
                          <div className="text-[9px] text-muted">
                            时间: {formatEventTime(event.created_at)}
                          </div>
                        )}

                        {event.sequence && (
                          <div className="text-[9px] text-muted">
                            序号: #{event.sequence}
                          </div>
                        )}

                        {detail && (
                          <div className="text-[10px] leading-relaxed text-primary/80">
                            {detail}
                          </div>
                        )}

                        {Object.keys(payload).length > 0 && (
                          <div className="space-y-1.5">
                            <div className="text-[10px] font-medium text-muted">详细信息</div>
                            <div className="rounded-lg border border-border/15 bg-background p-2">
                              <pre className="text-[9px] leading-relaxed text-primary/70 overflow-x-auto">
                                {JSON.stringify(payload, null, 2)}
                              </pre>
                            </div>
                          </div>
                        )}

                        {type.includes('fail') && payload.error != null && (
                          <div className="rounded-lg border border-destructive/20 bg-destructive/5 px-3 py-2">
                            <div className="text-[10px] font-medium text-destructive">错误信息</div>
                            <p className="mt-1 text-[10px] leading-relaxed text-destructive/80">
                              {String(payload.error)}
                            </p>
                          </div>
                        )}
                      </div>
                    </details>
                  )
                })}
              </div>
            </section>
          )
        })}

        {grouped.get('_other')?.length ? (
          <section className="space-y-2">
            <div className="flex items-center gap-2 px-1">
              <div className="w-2 h-2 rounded-full bg-muted/50" />
              <h3 className="text-[11px] font-medium text-primary">其它操作</h3>
              <span className="ml-auto text-[9px] text-muted">({grouped.get('_other')!.length} 条)</span>
            </div>

            <div className="relative pl-4 space-y-1.5 before:absolute before:left-0 before:top-2 before:bottom-2 before:w-px before:bg-border/10">
              {grouped.get('_other')!.map((event, index) => {
                const type = String(event.type || '')
                const payload = (event.payload || {}) as Record<string, unknown>
                const detail = String(payload.summary || payload.error || payload.detail || payload.message || '')
                const colorClass = eventColorClass(type)

                return (
                  <details
                    key={`other-${event.sequence}-${index}`}
                    className="group aq-soft-panel rounded-xl px-4 py-3 text-[11px]"
                  >
                    <summary className="flex cursor-pointer list-none flex-wrap items-start justify-between gap-2">
                      <div className="flex items-start gap-2 min-w-0 flex-1">
                        <div className="w-1.5 h-1.5 rounded-full bg-border/30 mt-1.5 shrink-0" />
                        <div className="min-w-0 flex-1">
                          <div className={`font-medium ${colorClass}`}>
                            {formatReviewPlusEventLabel(type)}
                          </div>
                          {detail ? (
                            <p className="mt-1 text-[10px] leading-relaxed text-muted line-clamp-2">{detail}</p>
                          ) : null}
                        </div>
                      </div>
                      <span className="shrink-0 tabular-nums text-[9px] text-muted">
                        {formatEventTime(event.created_at)}
                      </span>
                    </summary>

                    <div className="mt-3 pl-4 space-y-2 border-l-2 border-border/10">
                      {event.created_at && (
                        <div className="text-[9px] text-muted">
                          时间: {formatEventTime(event.created_at)}
                        </div>
                      )}

                      {detail && (
                        <div className="text-[10px] leading-relaxed text-primary/80">
                          {detail}
                        </div>
                      )}

                      {Object.keys(payload).length > 0 && (
                        <div className="space-y-1.5">
                          <div className="text-[10px] font-medium text-muted">详细信息</div>
                          <div className="rounded-lg border border-border/15 bg-background p-2">
                            <pre className="text-[9px] leading-relaxed text-primary/70 overflow-x-auto">
                              {JSON.stringify(payload, null, 2)}
                            </pre>
                          </div>
                        </div>
                      )}
                    </div>
                  </details>
                )
              })}
            </div>
          </section>
        ) : null}

        <div ref={endRef} />
      </div>
    </div>
  )
}
