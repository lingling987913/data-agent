'use client'

import { useGncResource } from '@/features/unified-review-workbench/hooks/useGncResource'
import { useOptionalGncWorkbenchLink } from '@/features/unified-review-workbench/components/GncWorkbenchLinkContext'
import {
  collectRelatedEvidenceIds,
  collectRelatedRidIds,
} from '@/features/unified-review-workbench/utils/gncWorkbenchLinks'

export function GncFindingsTab({ reviewId, enabled }: { reviewId: string; enabled: boolean }) {
  const link = useOptionalGncWorkbenchLink()
  const { data, loading, error } = useGncResource<Array<Record<string, unknown>>>(reviewId, 'findings', enabled)

  if (loading) return <p className="text-[11px] text-muted">加载发现…</p>
  if (error) return <p className="text-[11px] text-destructive">{error}</p>
  const items = Array.isArray(data) ? data : []
  if (!items.length) return <p className="text-[11px] text-muted">暂无发现</p>

  return (
    <ul className="space-y-2">
      {items.map((item) => {
        const findingId = String(item.finding_id || '')
        const isSelected = link?.selectedFindingId === findingId
        const relatedEvidences = collectRelatedEvidenceIds(item)
        const relatedRids = collectRelatedRidIds(item)

        return (
          <li
            key={findingId || String(item.title || item.description || '')}
            className={`rounded-lg border px-3 py-2 text-[11px] ${
              isSelected ? 'border-primaryAccent/40 bg-primaryAccent/5' : 'border-border/15'
            }`}
          >
            <button
              type="button"
              className="w-full text-left"
              onClick={() => link?.setSelectedFindingId(findingId)}
            >
              <div className="flex flex-wrap items-center gap-2">
                <span className="font-medium text-primary">{findingId || '发现'}</span>
                {item.severity ? (
                  <span className="rounded border border-border/20 px-1.5 py-0.5 text-[10px] text-muted">
                    {String(item.severity)}
                  </span>
                ) : null}
              </div>
              <p className="mt-1 text-muted">
                {String(item.title || item.description || '')}
              </p>
              {item.status ? <p className="mt-0.5 text-muted">状态：{String(item.status)}</p> : null}
            </button>

            <div className="mt-2 flex flex-wrap items-center gap-2">
              {relatedEvidences.length ? (
                <button
                  type="button"
                  onClick={() => {
                    link?.setSelectedFindingId(findingId)
                    link?.setSelectedEvidenceId(String(relatedEvidences[0]))
                    link?.openLinkedTab('evidences')
                  }}
                  className="text-[10px] text-primaryAccent hover:underline"
                >
                  关联证据 {relatedEvidences.length}
                </button>
              ) : null}
              {relatedRids.length ? (
                <button
                  type="button"
                  onClick={() => {
                    link?.setSelectedFindingId(findingId)
                    link?.setSelectedRidId(String(relatedRids[0]))
                    link?.openLinkedTab('rid')
                  }}
                  className="text-[10px] text-primaryAccent hover:underline"
                >
                  关联 RID {relatedRids.length}
                </button>
              ) : null}
            </div>
          </li>
        )
      })}
    </ul>
  )
}

export default GncFindingsTab
