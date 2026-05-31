'use client'

import { useMemo, useState } from 'react'
import { useGncResource } from '@/features/unified-review-workbench/hooks/useGncResource'
import { useOptionalGncWorkbenchLink } from '@/features/unified-review-workbench/components/GncWorkbenchLinkContext'
import { extractEvidenceRidId } from '@/features/unified-review-workbench/utils/gncWorkbenchLinks'

interface EvidenceItem {
  evidence_id?: string
  quote?: string
  content?: string
  finding_id?: string
  rule_id?: string
  unit_key?: string
  source?: string
  section_id?: string
  document_name?: string
  page_ref?: string
  rid_id?: string
  review_item_id?: string
}

type GroupMode = 'unit' | 'rule' | 'finding'

function groupEvidences(items: EvidenceItem[], mode: GroupMode): Array<[string, EvidenceItem[]]> {
  const buckets = new Map<string, EvidenceItem[]>()
  for (const item of items) {
    const key = mode === 'unit'
      ? String(item.unit_key || '未分组单元')
      : mode === 'rule'
        ? String(item.rule_id || '未关联规则')
        : String(item.finding_id || '未关联发现')
    const list = buckets.get(key) || []
    list.push(item)
    buckets.set(key, list)
  }
  return Array.from(buckets.entries()).sort(([a], [b]) => a.localeCompare(b))
}

export function GncEvidencesTab({ reviewId, enabled }: { reviewId: string; enabled: boolean }) {
  const link = useOptionalGncWorkbenchLink()
  const { data, loading, error } = useGncResource<EvidenceItem[]>(reviewId, 'evidences', enabled)
  const [groupMode, setGroupMode] = useState<GroupMode>('finding')

  const items = Array.isArray(data) ? data : []
  const selectedFindingId = link?.selectedFindingId || ''

  const filteredItems = useMemo(() => {
    if (selectedFindingId) {
      return items.filter((item) => String(item.finding_id || '') === selectedFindingId)
    }
    if (link?.selectedEvidenceId) {
      return items.filter((item) => String(item.evidence_id || '') === link.selectedEvidenceId)
    }
    return items
  }, [items, link?.selectedEvidenceId, selectedFindingId])

  const grouped = useMemo(() => groupEvidences(filteredItems, groupMode), [filteredItems, groupMode])

  const selectedEvidence = useMemo(() => {
    const id = link?.selectedEvidenceId || ''
    if (!id) return null
    return items.find((item) => String(item.evidence_id || '') === id) || null
  }, [items, link?.selectedEvidenceId])

  const selectedEvidenceRidId = useMemo(() => {
    if (!selectedEvidence) return ''
    return extractEvidenceRidId(selectedEvidence as Record<string, unknown>)
  }, [selectedEvidence])

  if (loading) return <p className="text-[11px] text-muted">加载证据链…</p>
  if (error) return <p className="text-[11px] text-destructive">{error}</p>

  return (
    <div className="space-y-4 text-[11px]">
      {(link?.selectedFindingId || link?.selectedRidId) ? (
        <div className="rounded-lg border border-primaryAccent/20 bg-primaryAccent/5 px-3 py-2 text-[10px] text-muted">
          联动上下文：
          {link?.selectedFindingId ? (
            <button
              type="button"
              className="ml-1 text-primaryAccent hover:underline"
              onClick={() => link.openLinkedTab('findings')}
            >
              发现 {link.selectedFindingId}
            </button>
          ) : null}
          {link?.selectedRidId ? (
            <button
              type="button"
              className="ml-1 text-primaryAccent hover:underline"
              onClick={() => link.openLinkedTab('rid')}
            >
              RID {link.selectedRidId}
            </button>
          ) : null}
        </div>
      ) : null}

      <div className="flex flex-wrap items-center gap-2">
        <span className="text-[10px] text-muted">分组：</span>
        {([
          ['finding', '按发现'],
          ['rule', '按规则'],
          ['unit', '按单元'],
        ] as const).map(([mode, label]) => (
          <button
            key={mode}
            type="button"
            onClick={() => setGroupMode(mode)}
            className={`rounded-lg border px-2 py-0.5 text-[10px] ${
              groupMode === mode
                ? 'border-primaryAccent/40 bg-primaryAccent/10 text-primaryAccent'
                : 'border-border/20 text-muted hover:text-primary'
            }`}
          >
            {label}
          </button>
        ))}
        {selectedFindingId ? (
          <button
            type="button"
            onClick={() => link?.setSelectedFindingId('')}
            className="ml-auto text-[10px] text-primaryAccent hover:underline"
          >
            清除发现筛选 ({selectedFindingId})
          </button>
        ) : null}
      </div>

      <div className={`grid gap-4 ${selectedEvidence ? 'lg:grid-cols-[1fr,minmax(240px,320px)]' : ''}`}>
        <div className="min-w-0 space-y-4">
      {!filteredItems.length ? (
        <p className="text-[10px] text-muted">暂无证据{selectedFindingId ? '（当前发现无关联证据）' : ''}</p>
      ) : (
        grouped.map(([groupKey, groupItems]) => (
          <section key={groupKey} className="rounded-xl border border-border/15 bg-background p-3">
            <div className="flex items-center justify-between gap-2">
              <div className="text-[10px] font-medium text-muted">{groupKey}</div>
              <span className="text-[10px] text-muted">{groupItems.length} 条</span>
            </div>
            <ul className="mt-2 space-y-2">
              {groupItems.map((item) => {
                const evidenceId = String(item.evidence_id || '')
                return (
                  <li
                    key={evidenceId || `${groupKey}-${item.quote}`}
                    className={`rounded-lg border px-2 py-1.5 ${
                      link?.selectedEvidenceId === evidenceId
                        ? 'border-primaryAccent/40 bg-primaryAccent/5'
                        : 'border-border/10'
                    }`}
                  >
                    <button
                      type="button"
                      className="w-full text-left"
                      onClick={() => {
                        link?.setSelectedEvidenceId(evidenceId)
                        if (item.finding_id) link?.setSelectedFindingId(String(item.finding_id))
                      }}
                    >
                      <div className="font-medium text-primary">{evidenceId || '证据'}</div>
                      {item.quote ? <p className="mt-1 line-clamp-3 text-[10px] leading-relaxed text-muted">{item.quote}</p> : null}
                    </button>
                    <div className="mt-1 flex flex-wrap gap-2 text-[10px] text-muted">
                      {item.rule_id ? <span>规则：{item.rule_id}</span> : null}
                      {item.unit_key ? <span>单元：{item.unit_key}</span> : null}
                      {item.finding_id ? (
                        <button
                          type="button"
                          className="text-primaryAccent hover:underline"
                          onClick={() => link?.setSelectedFindingId(String(item.finding_id))}
                        >
                          发现：{item.finding_id}
                        </button>
                      ) : null}
                    </div>
                  </li>
                )
              })}
            </ul>
          </section>
        ))
      )}
        </div>

        {selectedEvidence ? (
          <aside className="lg:sticky lg:top-4 lg:self-start">
            <div className="rounded-xl border border-primaryAccent/30 bg-surface p-3 shadow-sm">
              <div className="flex items-center justify-between gap-2">
                <div className="text-[10px] font-medium text-muted">证据详情</div>
                <button
                  type="button"
                  onClick={() => link?.setSelectedEvidenceId('')}
                  className="text-[10px] text-primaryAccent hover:underline"
                >
                  关闭
                </button>
              </div>
              <div className="mt-2 font-medium text-primary">
                {String(selectedEvidence.evidence_id || '证据')}
              </div>
              {selectedEvidence.source || selectedEvidence.document_name ? (
                <p className="mt-2 text-[10px] text-muted">
                  来源：{String(selectedEvidence.source || selectedEvidence.document_name)}
                  {selectedEvidence.page_ref ? ` · ${selectedEvidence.page_ref}` : ''}
                  {selectedEvidence.section_id ? ` · 章节 ${selectedEvidence.section_id}` : ''}
                </p>
              ) : null}
              <div className="mt-2 max-h-[200px] overflow-auto rounded-lg border border-border/10 bg-background p-2">
                <p className="text-[10px] leading-relaxed text-primary whitespace-pre-wrap">
                  {String(selectedEvidence.quote || selectedEvidence.content || '（无摘录正文）')}
                </p>
              </div>
              <div className="mt-3 space-y-1.5 text-[10px]">
                {selectedEvidence.finding_id ? (
                  <button
                    type="button"
                    className="block text-primaryAccent hover:underline"
                    onClick={() => {
                      link?.setSelectedFindingId(String(selectedEvidence.finding_id))
                      link?.openLinkedTab('findings')
                    }}
                  >
                    关联发现：{selectedEvidence.finding_id}
                  </button>
                ) : null}
                {selectedEvidence.rule_id ? (
                  <button
                    type="button"
                    className="block text-primaryAccent hover:underline"
                    onClick={() => link?.openLinkedTab('committee')}
                  >
                    关联规则：{selectedEvidence.rule_id}
                  </button>
                ) : null}
                {selectedEvidenceRidId ? (
                  <button
                    type="button"
                    className="block text-primaryAccent hover:underline"
                    onClick={() => {
                      link?.setSelectedRidId(selectedEvidenceRidId)
                      link?.openLinkedTab('rid')
                    }}
                  >
                    关联 RID：{selectedEvidenceRidId}
                  </button>
                ) : null}
                {selectedEvidence.unit_key ? (
                  <span className="block text-muted">审查单元：{selectedEvidence.unit_key}</span>
                ) : null}
              </div>
            </div>
          </aside>
        ) : null}
      </div>
    </div>
  )
}

export default GncEvidencesTab
