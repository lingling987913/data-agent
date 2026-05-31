'use client'

import { useGncResource } from '@/features/unified-review-workbench/hooks/useGncResource'
import { hasGncMinutesVisibleSections, hasRichMinutesStruct, summarizeRecordMap } from '@/features/unified-review-workbench/utils/gncRichPanels'

function KeyValueGrid({
  title,
  rows,
}: {
  title: string
  rows: Array<{ key: string; detail: string }>
}) {
  if (!rows.length) return null
  return (
    <section className="rounded-xl border border-border/15 bg-background p-3">
      <div className="text-[10px] font-medium text-muted">{title}</div>
      <ul className="mt-2 max-h-[240px] space-y-1 overflow-auto">
        {rows.map((row) => (
          <li key={row.key} className="flex flex-wrap justify-between gap-2 rounded border border-border/10 px-2 py-1">
            <span className="font-medium text-primary">{row.key}</span>
            <span className="text-[10px] text-muted">{row.detail}</span>
          </li>
        ))}
      </ul>
    </section>
  )
}

function SummaryObjectBlock({ title, value }: { title: string; value: unknown }) {
  if (!value || typeof value !== 'object') return null
  const rows = summarizeRecordMap(value)
  if (!rows.length && !Array.isArray(value)) return null
  if (Array.isArray(value)) {
    return (
      <section className="rounded-xl border border-border/15 bg-background p-3">
        <div className="text-[10px] font-medium text-muted">{title}</div>
        <ul className="mt-2 space-y-1">
          {value.map((item, index) => (
            <li key={index} className="text-[10px] text-primary">
              • {typeof item === 'string' ? item : JSON.stringify(item)}
            </li>
          ))}
        </ul>
      </section>
    )
  }
  return <KeyValueGrid title={title} rows={rows} />
}

export function GncMinutesTab({ reviewId, enabled }: { reviewId: string; enabled: boolean }) {
  const { data, loading, error } = useGncResource<Record<string, unknown>>(reviewId, 'minutes', enabled)

  if (loading) return <p className="text-[11px] text-muted">加载纪要…</p>
  if (error) return <p className="text-[11px] text-destructive">{error}</p>

  const minutes = data || {}
  if (!hasRichMinutesStruct(minutes)) {
    return (
      <div className="rounded-xl border border-dashed border-border/20 px-4 py-8 text-center text-[11px]">
        <p className="font-medium text-primary">审查纪要尚未生成</p>
        <p className="mt-2 text-muted">合稿与 editorial_synthesis 完成后将展示结构化纪要。</p>
      </div>
    )
  }

  if (typeof minutes.text === 'string' && minutes.text.trim() && !minutes.conclusion_draft) {
    return (
      <article className="rounded-xl border border-border/15 bg-background p-4 text-[11px] leading-relaxed text-primary whitespace-pre-wrap">
        {minutes.text}
      </article>
    )
  }

  const members = Array.isArray(minutes.committee_members)
    ? (minutes.committee_members as string[])
    : []

  if (!hasGncMinutesVisibleSections(minutes)) {
    return (
      <div className="rounded-xl border border-dashed border-border/20 px-4 py-8 text-center text-[11px]">
        <p className="font-medium text-primary">结构化纪要暂无可见内容</p>
        <p className="mt-2 text-muted">已检测到纪要结构字段，但当前各区块均为空；合稿完成后将展示结论、映射与跟踪项。</p>
      </div>
    )
  }

  return (
    <div className="space-y-3 text-[11px]">
      {minutes.conclusion_draft ? (
        <section className="rounded-xl border border-primaryAccent/20 bg-primaryAccent/5 px-4 py-3">
          <div className="text-[10px] font-medium text-muted">结论草案</div>
          <p className="mt-1 leading-relaxed text-primary">{String(minutes.conclusion_draft)}</p>
        </section>
      ) : null}

      {members.length ? (
        <section className="rounded-xl border border-border/15 bg-background p-3">
          <div className="text-[10px] font-medium text-muted">committee_members</div>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {members.map((name) => (
              <span
                key={name}
                className="rounded-full border border-border/20 px-2 py-0.5 text-[10px] text-primary"
              >
                {name}
              </span>
            ))}
          </div>
        </section>
      ) : null}

      <KeyValueGrid title="section_rid_map" rows={summarizeRecordMap(minutes.section_rid_map)} />
      <KeyValueGrid title="rule_coverage_summary" rows={summarizeRecordMap(minutes.rule_coverage_summary)} />
      <SummaryObjectBlock title="traceability_matrix_summary" value={minutes.traceability_matrix_summary} />
      <SummaryObjectBlock title="unit_review_summary" value={minutes.unit_review_summary} />
      <SummaryObjectBlock title="prior_cycle_summary" value={minutes.prior_cycle_summary} />

      {(minutes.follow_up_items as unknown[] | undefined)?.length ? (
        <section className="rounded-xl border border-border/15 bg-background p-3">
          <div className="text-[10px] font-medium text-muted">后续跟踪</div>
          <ul className="mt-2 space-y-1">
            {(minutes.follow_up_items as unknown[]).map((item, index) => (
              <li key={index} className="text-[10px] text-primary">• {String(item)}</li>
            ))}
          </ul>
        </section>
      ) : null}
    </div>
  )
}

export default GncMinutesTab
