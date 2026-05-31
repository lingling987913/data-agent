'use client'

import { useMemo, useState } from 'react'
import ActionEmptyState from '@/features/review-plus-v2/components/workbench/ActionEmptyState'
import ResultSummaryBar from '@/features/review-plus-v2/components/workbench/ResultSummaryBar'
import { CROSS_DOC_ITEM_TYPE_LABELS } from '@/features/review-plus-v2/utils/reviewPlusPipeline'
import { SEVERITY_LABELS } from '@/features/review-plus-v2/types'

type SortOption = 'severity' | 'item_type' | 'status'

const SEVERITY_ORDER: Record<string, number> = { critical: 0, major: 1, minor: 2, info: 3 }

const STATUS_LABELS: Record<string, string> = {
  open: '待处理',
  confirmed: '已确认',
  resolved: '已解决',
  closed: '已关闭',
}

const STATUS_COLORS: Record<string, string> = {
  open: 'bg-destructive/10 text-destructive',
  confirmed: 'bg-warning/10 text-warning',
  resolved: 'bg-info/10 text-info',
  closed: 'bg-positive/10 text-positive',
}

const DETECTION_METHOD_LABELS: Record<string, string> = {
  semantic_matching: '语义匹配',
  rule_based: '规则检查',
  cross_reference: '交叉引用',
  manual_review: '人工审查',
  automated: '自动检测',
}

export default function ReviewPlusCrossDocTab({
  items,
  onOpenEvidenceCompare,
}: {
  items: Array<Record<string, unknown>>
  onOpenEvidenceCompare?: (item: Record<string, unknown>) => void
}) {
  const [itemTypeFilter, setItemTypeFilter] = useState('all')
  const [severityFilter, setSeverityFilter] = useState('all')
  const [statusFilter, setStatusFilter] = useState('all')
  const [sortBy, setSortBy] = useState<SortOption>('severity')
  const [activeRowId, setActiveRowId] = useState<string | undefined>()

  const itemTypeOptions = useMemo(() => {
    const types = new Set(items.map((item) => String(item.item_type || '')).filter(Boolean))
    return Array.from(types)
  }, [items])

  const severityOptions = useMemo(() => {
    const sevs = new Set(items.map((item) => String(item.severity || '').toLowerCase()).filter(Boolean))
    return Array.from(sevs)
  }, [items])

  const statusOptions = useMemo(() => {
    const stats = new Set(items.map((item) => String(item.status || 'open')).filter(Boolean))
    return Array.from(stats)
  }, [items])

  const filteredAndSortedItems = useMemo(() => {
    const filtered = items.filter((item) => {
      const typeMatch = itemTypeFilter === 'all' || String(item.item_type || '') === itemTypeFilter
      const sev = String(item.severity || '').toLowerCase()
      const sevMatch = severityFilter === 'all' || sev === severityFilter
      const statMatch = statusFilter === 'all' || String(item.status || 'open') === statusFilter
      return typeMatch && sevMatch && statMatch
    })

    filtered.sort((a, b) => {
      if (sortBy === 'severity') {
        const sevA = SEVERITY_ORDER[String(a.severity || '').toLowerCase()] ?? 999
        const sevB = SEVERITY_ORDER[String(b.severity || '').toLowerCase()] ?? 999
        return sevA - sevB
      }
      if (sortBy === 'item_type') {
        const typeA = String(a.item_type || '')
        const typeB = String(b.item_type || '')
        return typeA.localeCompare(typeB, 'zh-CN')
      }
      if (sortBy === 'status') {
        const statA = String(a.status || 'open')
        const statB = String(b.status || 'open')
        return statA.localeCompare(statB, 'zh-CN')
      }
      return 0
    })

    return filtered
  }, [items, itemTypeFilter, severityFilter, statusFilter, sortBy])

  const severityCounts = useMemo(() => {
    const counts = { critical: 0, major: 0, minor: 0, info: 0, other: 0 }
    for (const item of items) {
      const sev = String(item.severity || '').toLowerCase()
      if (sev in counts) counts[sev as keyof typeof counts] += 1
      else counts.other += 1
    }
    return counts
  }, [items])

  const itemTypeCounts = useMemo(() => {
    const counts = new Map<string, number>()
    for (const item of items) {
      const type = String(item.item_type || '')
      counts.set(type, (counts.get(type) || 0) + 1)
    }
    return counts
  }, [items])

  if (!items.length) {
    return (
      <ActionEmptyState
        title="暂无跨文档问题"
        description="跨文档审查将核对指标口径、版本基线与引用关系等多材料一致性。"
        hint="完成跨文档审查步骤后，可在此查看需闭环的问题清单。"
      />
    )
  }

  return (
    <div className="max-w-5xl space-y-3">
      <ResultSummaryBar
        items={[
          { label: '问题总数', value: items.length, tone: 'brand' },
          { label: '关键', value: severityCounts.critical, tone: severityCounts.critical > 0 ? 'danger' : 'default' },
          { label: '主要', value: severityCounts.major, tone: severityCounts.major > 0 ? 'warning' : 'default' },
          { label: '一般', value: severityCounts.minor + severityCounts.other, tone: 'default' },
        ]}
        hint="跨文档问题来自指标、版本与引用关系等多材料比对，需在整改中逐项闭环。"
      />

      <div className="flex flex-wrap gap-2 rounded-xl border border-border/15 bg-background px-3 py-2">
        {Array.from(itemTypeCounts.entries()).map(([type, count]) => {
          const label = CROSS_DOC_ITEM_TYPE_LABELS[type] || type
          return count > 0 ? (
            <span key={type} className="px-2 py-0.5 rounded-full text-[10px] bg-muted/10 text-muted border border-border/20">
              {label}: {count}
            </span>
          ) : null
        })}
      </div>

      <div className="flex flex-wrap gap-2 items-center">
        <select
          value={itemTypeFilter}
          onChange={(e) => setItemTypeFilter(e.target.value)}
          className="rounded-xl border border-border/25 bg-surface px-3 py-1.5 text-[11px] text-primary focus:border-primaryAccent/40 focus:outline-none"
        >
          <option value="all">全部类型</option>
          {itemTypeOptions.map((type) => (
            <option key={type} value={type}>{CROSS_DOC_ITEM_TYPE_LABELS[type] || type}</option>
          ))}
        </select>

        <select
          value={severityFilter}
          onChange={(e) => setSeverityFilter(e.target.value)}
          className="rounded-xl border border-border/25 bg-surface px-3 py-1.5 text-[11px] text-primary focus:border-primaryAccent/40 focus:outline-none"
        >
          <option value="all">全部严重度</option>
          {severityOptions.map((sev) => (
            <option key={sev} value={sev}>{SEVERITY_LABELS[sev] || sev}</option>
          ))}
        </select>

        <select
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          className="rounded-xl border border-border/25 bg-surface px-3 py-1.5 text-[11px] text-primary focus:border-primaryAccent/40 focus:outline-none"
        >
          <option value="all">全部状态</option>
          {statusOptions.map((stat) => (
            <option key={stat} value={stat}>{STATUS_LABELS[stat] || stat}</option>
          ))}
        </select>

        <select
          value={sortBy}
          onChange={(e) => setSortBy(e.target.value as SortOption)}
          className="rounded-xl border border-border/25 bg-surface px-3 py-1.5 text-[11px] text-primary focus:border-primaryAccent/40 focus:outline-none"
        >
          <option value="severity">按严重度</option>
          <option value="item_type">按类型</option>
          <option value="status">按状态</option>
        </select>

        <span className="text-[10px] text-muted">当前显示 {filteredAndSortedItems.length} 项</span>
      </div>

      <div className="space-y-2">
        {filteredAndSortedItems.map((item, index) => {
          const itemType = String(item.item_type || '')
          const severity = String(item.severity || 'info').toLowerCase()
          const status = String(item.status || 'open')
          const typeLabel = CROSS_DOC_ITEM_TYPE_LABELS[itemType] || itemType || '跨文档问题'

          const itemId = String(item.review_item_id || index)
          const isActive = activeRowId === itemId
          const hasEvidence = Array.isArray(item.evidence_ids) && item.evidence_ids.length > 0

          return (
            <details
              key={itemId}
              className={`group aq-soft-panel rounded-lg p-3 border transition-colors ${
                isActive ? 'border-primaryAccent bg-primaryAccent/5 ring-1 ring-primaryAccent/30' : 'border-border/15'
              }`}
              data-testid={`review-plus-v2-cross-doc-${index}`}
              onToggle={(e) => {
                if ((e.target as HTMLDetailsElement).open) {
                  setActiveRowId(itemId)
                }
              }}
            >
              <summary className="flex cursor-pointer list-none flex-wrap items-center gap-2">
                <span className="rounded-full border border-border/30 bg-background px-2 py-0.5 text-[9px] text-muted">
                  {typeLabel}
                </span>
                <span
                  className={`rounded-full border px-2 py-0.5 text-[9px] font-medium ${
                    severity === 'critical'
                      ? 'border-destructive/20 bg-destructive/5 text-destructive'
                      : severity === 'major'
                        ? 'border-warning/20 bg-warning/8 text-warning'
                        : severity === 'minor'
                          ? 'border-info/20 bg-info/8 text-info'
                          : 'border-border/30 bg-muted/10 text-muted'
                  }`}
                >
                  {SEVERITY_LABELS[severity] || severity}
                </span>
                <span className={`rounded-full border px-2 py-0.5 text-[9px] font-medium ${STATUS_COLORS[status] || 'bg-muted/10 text-muted'}`}>
                  {STATUS_LABELS[status] || status}
                </span>
                <h4 className="flex-1 text-sm font-medium text-primary">{String(item.title || '跨文档问题')}</h4>
              </summary>

              <div className="mt-3 space-y-2">
                {item.description ? (
                  <div>
                    <p className="text-[11px] leading-relaxed text-primary/80">{String(item.description)}</p>
                  </div>
                ) : null}

                {item.detection_method ? (
                  <div>
                    <div className="flex items-center gap-1.5 flex-wrap">
                      <span className="text-[10px] font-medium text-muted">检测方法</span>
                      <span className="rounded-md bg-primaryAccent/8 px-1.5 py-0.5 text-[9px] text-primaryAccent">
                        {DETECTION_METHOD_LABELS[String(item.detection_method)] || String(item.detection_method)}
                      </span>
                    </div>
                  </div>
                ) : null}

                {item.related_documents && Array.isArray(item.related_documents) && item.related_documents.length > 0 ? (
                  <div>
                    <div className="text-[10px] font-medium text-muted">关联文档</div>
                    <div className="mt-1 flex flex-wrap gap-1">
                      {(item.related_documents as string[]).slice(0, 4).map((doc, idx) => (
                        <span key={idx} className="inline-flex rounded-md border border-border/20 bg-background px-2 py-0.5 text-[9px] text-primary">
                          {doc}
                        </span>
                      ))}
                      {(item.related_documents as string[]).length > 4 && (
                        <span className="text-[9px] text-muted">等 {(item.related_documents as string[]).length} 份</span>
                      )}
                    </div>
                  </div>
                ) : null}

                {item.source_quotes && Array.isArray(item.source_quotes) && item.source_quotes.length > 0 ? (
                  <div>
                    <div className="text-[10px] font-medium text-muted">源文摘录</div>
                    <div className="mt-1 space-y-1">
                      {(item.source_quotes as string[]).slice(0, 2).map((quote, idx) => (
                        <p key={idx} className="rounded-md bg-muted/5 px-2 py-1.5 text-[10px] leading-relaxed text-muted line-clamp-3">
                          {quote}
                        </p>
                      ))}
                      {(item.source_quotes as string[]).length > 2 && (
                        <p className="text-[9px] text-muted">另有 {(item.source_quotes as string[]).length - 2} 条摘录</p>
                      )}
                    </div>
                  </div>
                ) : item.source_quote ? (
                  <div>
                    <div className="text-[10px] font-medium text-muted">源文摘录</div>
                    <p className="mt-1 rounded-md bg-muted/5 px-2 py-1.5 text-[10px] leading-relaxed text-muted line-clamp-3">
                      {String(item.source_quote)}
                    </p>
                  </div>
                ) : null}

                {item.recommendation ? (
                  <div>
                    <div className="text-[10px] font-medium text-muted">整改建议</div>
                    <p className="mt-1 rounded-lg border border-border/20 bg-background px-3 py-2 text-[10px] leading-relaxed text-primary">
                      {String(item.recommendation)}
                    </p>
                  </div>
                ) : null}

                {item.evidence_ids && Array.isArray(item.evidence_ids) && item.evidence_ids.length > 0 ? (
                  <div>
                    <div className="text-[10px] font-medium text-muted">证据定位</div>
                    <div className="mt-1 flex flex-wrap gap-1">
                      {(item.evidence_ids as string[]).slice(0, 5).map((ref, idx) => (
                        <span key={idx} className="inline-flex rounded-md border border-border/20 bg-background px-2 py-0.5 text-[9px] text-primaryAccent">
                          {ref}
                        </span>
                      ))}
                      {(item.evidence_ids as string[]).length > 5 && (
                        <span className="text-[9px] text-muted">等 {(item.evidence_ids as string[]).length} 条</span>
                      )}
                    </div>
                  </div>
                ) : null}

                {item.artifact_refs && Array.isArray(item.artifact_refs) && item.artifact_refs.length > 0 ? (
                  <div>
                    <div className="text-[10px] font-medium text-muted">引用依据</div>
                    <div className="mt-1 flex flex-wrap gap-1">
                      {(item.artifact_refs as string[]).slice(0, 5).map((ref, idx) => (
                        <span key={idx} className="inline-flex rounded-md border border-border/20 bg-background px-2 py-0.5 text-[9px] text-primaryAccent">
                          {ref}
                        </span>
                      ))}
                      {(item.artifact_refs as string[]).length > 5 && (
                        <span className="text-[9px] text-muted">等 {(item.artifact_refs as string[]).length} 条</span>
                      )}
                    </div>
                  </div>
                ) : null}

                {item.section_id ? (
                  <div>
                    <div className="text-[10px] font-medium text-muted">关联章节</div>
                    <div className="mt-1">
                      <span className="inline-flex rounded-md border border-border/20 bg-background px-2 py-0.5 text-[9px] font-mono text-primaryAccent">
                        {String(item.section_id)}
                      </span>
                    </div>
                  </div>
                ) : null}

                {hasEvidence ? (
                  <div className="border-t border-border/10 pt-2">
                    <button
                      type="button"
                      onClick={() => onOpenEvidenceCompare?.(item)}
                      className="rounded-xl border border-border/25 px-3 py-1.5 text-[10px] font-medium text-primaryAccent hover:border-brand/40"
                    >
                      对照原文证据
                    </button>
                  </div>
                ) : null}
              </div>
            </details>
          )
        })}
      </div>

      {!filteredAndSortedItems.length && (
        <div className="aq-soft-panel rounded-xl p-8 text-center space-y-2">
          <p className="text-[13px] font-medium text-primary">当前筛选条件下无跨文档问题</p>
          <p className="text-[11px] leading-6 text-primary/70">请调整过滤器查看全部问题。</p>
        </div>
      )}
    </div>
  )
}
