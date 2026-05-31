'use client'

import { useMemo, useState } from 'react'
import ActionEmptyState from '@/features/review-plus-v2/components/workbench/ActionEmptyState'
import ResultSummaryBar from '@/features/review-plus-v2/components/workbench/ResultSummaryBar'
import type { ReviewPlusCheckItem, ReviewPlusTaskDetail } from '@/features/review-plus-v2/types'
import { SEVERITY_LABELS } from '@/features/review-plus-v2/types'
import { resolveReviewPlusCheckItemTitle } from '@/features/review-plus-v2/utils/reviewPlusCheckItemLabel'

type SeverityFilter = 'all' | 'critical' | 'major' | 'minor' | 'info'

const SEVERITY_COLORS: Record<string, string> = {
  critical: 'bg-destructive/10 text-destructive border-destructive/20',
  major: 'bg-warning/10 text-warning border-warning/20',
  minor: 'bg-info/10 text-info border-info/20',
  info: 'bg-muted/10 text-muted border-border/20',
}

function ConfidenceBar({ confidence }: { confidence: number }) {
  const percentage = Math.round(confidence * 100)
  const colorClass = percentage >= 80 ? 'bg-positive' : percentage >= 60 ? 'bg-warning' : 'bg-destructive'

  return (
    <div className="flex items-center gap-2">
      <div className="flex-1 h-1.5 bg-muted/10 rounded-full overflow-hidden">
        <div className={`h-full rounded-full ${colorClass}`} style={{ width: `${percentage}%` }} />
      </div>
      <span className="text-[9px] text-muted tabular-nums">{percentage}%</span>
    </div>
  )
}

function mappingSectionCount(mapping: Record<string, unknown>): number {
  const ids = mapping.section_ids
  if (Array.isArray(ids)) return ids.length
  return 0
}

export default function ReviewPlusCheckItemsTab({
  checkItems,
  sectionMappings,
}: {
  checkItems: ReviewPlusCheckItem[]
  sectionMappings: ReviewPlusTaskDetail['section_mappings']
}) {
  const [severityFilter, setSeverityFilter] = useState<SeverityFilter>('all')
  const [searchQuery, setSearchQuery] = useState('')

  const mappingByItem = useMemo(() => {
    const map = new Map<string, Record<string, unknown>>()
    for (const raw of sectionMappings || []) {
      const id = String(raw.check_item_id || '')
      if (id) map.set(id, raw)
    }
    return map
  }, [sectionMappings])

  const severityCounts = useMemo(() => {
    const counts = { critical: 0, major: 0, minor: 0, info: 0, other: 0 }
    for (const item of checkItems) {
      const sev = String(item.severity || '').toLowerCase()
      if (sev in counts) counts[sev as keyof typeof counts] += 1
      else counts.other += 1
    }
    return counts
  }, [checkItems])

  const filteredItems = useMemo(() => {
    let filtered = checkItems

    if (severityFilter !== 'all') {
      filtered = filtered.filter((item) => {
        const sev = String(item.severity || '').toLowerCase()
        return sev === severityFilter
      })
    }

    if (searchQuery.trim()) {
      const query = searchQuery.toLowerCase()
      filtered = filtered.filter((item) => {
        const title = (item.title || '').toLowerCase()
        const reqText = (item.requirement_text || '').toLowerCase()
        const itemNo = (item.item_no || '').toLowerCase()
        const source = (item.source_material_name || '').toLowerCase()
        return title.includes(query) || reqText.includes(query) || itemNo.includes(query) || source.includes(query)
      })
    }

    return filtered
  }, [checkItems, severityFilter, searchQuery])

  const mappedCount = checkItems.filter((item) => mappingSectionCount(mappingByItem.get(item.check_item_id) || {}) > 0).length

  if (!checkItems.length) {
    return (
      <ActionEmptyState
        title="暂无检查项"
        description="完成规则抽取与证据映射后，将在此展示检查项清单、来源材料与章节映射。"
        hint="可先查看送审包与审查流程，确认规则材料已上传。"
      />
    )
  }

  return (
    <div className="max-w-5xl space-y-3">
      <ResultSummaryBar
        items={[
          { label: '检查项', value: checkItems.length, tone: 'brand' },
          { label: '已映射', value: mappedCount, tone: mappedCount > 0 ? 'success' : 'default' },
          { label: '待映射', value: Math.max(0, checkItems.length - mappedCount), tone: checkItems.length - mappedCount > 0 ? 'warning' : 'default' },
        ]}
        hint="检查项来自审查规则/检查单；证据映射将检查项关联到被审文档章节。"
      />

      <div className="flex flex-wrap gap-2 rounded-xl border border-border/15 bg-background px-3 py-2">
        {(['critical', 'major', 'minor', 'info'] as const).map((sev) => {
          const c = severityCounts[sev]
          return c > 0 ? (
            <span key={sev} className={`px-2 py-0.5 rounded-full text-[10px] ${SEVERITY_COLORS[sev]}`}>
              {SEVERITY_LABELS[sev]}: {c}
            </span>
          ) : null
        })}
        {severityCounts.other > 0 ? (
          <span className="px-2 py-0.5 rounded-full text-[10px] bg-muted/10 text-muted border border-border/20">
            其他: {severityCounts.other}
          </span>
        ) : null}
      </div>

      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex gap-1.5 flex-wrap">
          {[
            ['all', '全部'],
            ['critical', '关键'],
            ['major', '主要'],
            ['minor', '一般'],
            ['info', '提示'],
          ].map(([key, label]) => (
            <button
              key={key}
              type="button"
              onClick={() => setSeverityFilter(key as SeverityFilter)}
              className={`px-2.5 py-1 rounded-full text-[10px] transition-colors ${
                severityFilter === key
                  ? 'bg-primaryAccent text-white'
                  : 'bg-background text-muted hover:bg-muted/15'
              }`}
            >
              {label}
            </button>
          ))}
        </div>

        <div className="relative">
          <input
            type="text"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            placeholder="搜索项号、标题、材料..."
            className="w-full sm:w-64 rounded-xl border border-border/25 bg-surface px-3 py-1.5 text-[11px] text-primary placeholder:text-muted/50 focus:border-primaryAccent/40 focus:outline-none"
          />
        </div>

        <span className="text-[10px] text-muted">当前显示 {filteredItems.length} 项</span>
      </div>

      <div className="space-y-2">
        {filteredItems.map((item) => {
          const itemIndex = checkItems.findIndex((candidate) => candidate.check_item_id === item.check_item_id) + 1
          const mapping = mappingByItem.get(item.check_item_id)
          const sectionIds = Array.isArray(mapping?.section_ids) ? (mapping!.section_ids as string[]) : []
          const uniqueSectionIds = sectionIds.filter((sid, index, arr) => arr.indexOf(sid) === index)
          const severity = String(item.severity || 'info').toLowerCase()
          const confidence = typeof item.confidence === 'number' ? item.confidence : null

          return (
            <details key={`${item.check_item_id}-${itemIndex}`} className="group aq-soft-panel rounded-lg p-3">
              <summary className="flex cursor-pointer list-none items-start gap-3">
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap mb-1.5">
                    {severity !== 'info' ? (
                      <span className={`rounded border px-1.5 py-0.5 text-[9px] font-medium ${SEVERITY_COLORS[severity]}`}>
                        {SEVERITY_LABELS[severity] || severity}
                      </span>
                    ) : null}
                    {item.item_no ? (
                      <span className="text-[10px] text-muted font-mono">{item.item_no}</span>
                    ) : null}
                    {item.source_material_name ? (
                      <span className="text-[10px] text-muted">来源: {item.source_material_name}</span>
                    ) : null}
                  </div>
                  <h3 className="text-sm font-medium text-primary">{resolveReviewPlusCheckItemTitle(item, itemIndex)}</h3>
                </div>
                {confidence !== null && (
                  <div className="w-24 shrink-0">
                    <div className="text-[9px] text-muted mb-1">置信度</div>
                    <ConfidenceBar confidence={confidence} />
                  </div>
                )}
              </summary>

              <div className="mt-3 space-y-2 pl-0">
                {item.requirement_text ? (
                  <div>
                    <div className="text-[10px] font-medium text-muted">需求描述</div>
                    <p className="mt-1 text-[11px] leading-relaxed text-primary/80">{item.requirement_text}</p>
                  </div>
                ) : null}

                {item.acceptance_criteria ? (
                  <div>
                    <div className="text-[10px] font-medium text-muted">验收准则</div>
                    <p className="mt-1 text-[11px] leading-relaxed text-primary/80">{item.acceptance_criteria}</p>
                  </div>
                ) : null}

                {item.applicable_scope ? (
                  <div>
                    <div className="text-[10px] font-medium text-muted">适用范围</div>
                    <p className="mt-1 text-[11px] leading-relaxed text-primary/80">{item.applicable_scope}</p>
                  </div>
                ) : null}

                {item.source_quote ? (
                  <div>
                    <div className="text-[10px] font-medium text-muted">源文摘录</div>
                    <p className="mt-1 rounded-md bg-muted/5 px-2 py-1.5 text-[10px] leading-relaxed text-muted line-clamp-3">
                      {item.source_quote}
                    </p>
                  </div>
                ) : null}

                {confidence !== null ? (
                  <div>
                    <div className="text-[10px] font-medium text-muted">置信度详情</div>
                    <div className="mt-1 flex items-center gap-2">
                      <ConfidenceBar confidence={confidence} />
                      <span className="text-[9px] text-muted">
                        {confidence >= 0.8 ? '高' : confidence >= 0.6 ? '中' : '低'}置信度
                      </span>
                    </div>
                  </div>
                ) : null}

                <div className="flex items-start gap-3 pt-2 border-t border-border/10">
                  <div className="flex-1">
                    <div className="text-[10px] font-medium text-muted">章节映射</div>
                    {uniqueSectionIds.length > 0 ? (
                      <div className="mt-1 flex flex-wrap gap-1">
                        {uniqueSectionIds.slice(0, 4).map((sid, sectionIndex) => (
                          <span
                            key={`${item.check_item_id}-${sid}-${sectionIndex}`}
                            className="inline-flex rounded-md border border-border/20 bg-background px-2 py-0.5 text-[9px] font-mono text-primaryAccent"
                          >
                            {sid}
                          </span>
                        ))}
                        {uniqueSectionIds.length > 4 && (
                          <span className="text-[9px] text-muted">另有 {uniqueSectionIds.length - 4} 处</span>
                        )}
                      </div>
                    ) : (
                      <p className="mt-1 text-[10px] text-muted">待映射</p>
                    )}
                  </div>
                  <div className="flex-1">
                    <div className="text-[10px] font-medium text-muted">来源材料</div>
                    <p className="mt-1 text-[10px] text-primary">{item.source_material_name || '—'}</p>
                  </div>
                </div>
              </div>
            </details>
          )
        })}
      </div>

      {!filteredItems.length && checkItems.length > 0 && (
        <div className="aq-soft-panel rounded-xl p-8 text-center space-y-2">
          <p className="text-[13px] font-medium text-primary">当前筛选条件下无检查项</p>
          <p className="text-[11px] leading-6 text-primary/70">请调整过滤器或搜索条件查看全部检查项。</p>
        </div>
      )}
    </div>
  )
}
