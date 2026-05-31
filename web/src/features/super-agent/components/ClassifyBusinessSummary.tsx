'use client'

import { AlertTriangle, CheckCircle2, XCircle } from 'lucide-react'
import { ROUTE_LABELS } from '@/lib/aeroTerminology'
import type { MaterialClassification, SuperAgentRoute } from '@/features/super-agent/types'

const SLOT_LABELS: Record<string, string> = {
  review_rule: '审查规则/检查单',
  task_book: '研制任务书',
  subject_material: '被审材料',
}

export default function ClassifyBusinessSummary({
  classification,
  effectiveRoute,
  recommendedScene,
  reviewPlusSlotBlocked,
  missingSlots,
  canProceed,
}: {
  classification: MaterialClassification
  effectiveRoute: SuperAgentRoute
  recommendedScene: string
  reviewPlusSlotBlocked: boolean
  missingSlots?: string[]
  canProceed: boolean
}) {
  const routeLabel = ROUTE_LABELS[effectiveRoute] || effectiveRoute
  const slotsReady = classification.review_plus_ready === true
  const missingSlotLabels = (missingSlots || [])
    .map((slot) => SLOT_LABELS[slot] || slot)
    .filter(Boolean)

  return (
    <section
      className="rounded-xl border border-primaryAccent/25 bg-primaryAccent/5 p-4"
      data-testid="super-agent-classify-business-summary"
    >
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-[10px] font-medium uppercase tracking-wide text-muted">解析前准入判断</div>
          <div className="mt-1 text-[16px] font-semibold text-primary">
            初始建议：{routeLabel}
          </div>
          <p className="mt-1 text-[12px] text-muted">
            {classification.doc_type} · {classification.domain} · {recommendedScene}
          </p>
        </div>
        <span
          className={`inline-flex shrink-0 items-center gap-1 rounded-full border px-2.5 py-1 text-[10px] font-medium ${
            canProceed
              ? 'border-positive/25 bg-positive/10 text-positive'
              : 'border-destructive/25 bg-destructive/10 text-destructive'
          }`}
        >
          {canProceed ? (
            <CheckCircle2 className="h-3.5 w-3.5" aria-hidden />
          ) : (
            <XCircle className="h-3.5 w-3.5" aria-hidden />
          )}
          {canProceed ? '可进入解析' : '需补充材料或调整模式'}
        </span>
      </div>

      <div className="mt-4 grid gap-2 sm:grid-cols-3">
        <InfoTile
          label="材料齐套"
          value={slotsReady ? '槽位已闭合' : '槽位未闭合'}
          ok={slotsReady}
        />
        <InfoTile
          label="缺失项"
          value={missingSlotLabels.length ? missingSlotLabels.join('、') : '无'}
          ok={!missingSlotLabels.length}
        />
        <InfoTile
          label="下一步"
          value={reviewPlusSlotBlocked ? '补充材料或选智能模式' : '确认模式后进入解析'}
          ok={!reviewPlusSlotBlocked}
        />
      </div>

      {classification.reason ? (
        <p className="mt-3 text-[11px] leading-relaxed text-muted">{classification.reason}</p>
      ) : null}

      {reviewPlusSlotBlocked ? (
        <div className="mt-3 flex items-start gap-2 rounded-lg border border-amber-500/25 bg-amber-500/10 px-3 py-2 text-[11px] text-amber-800 dark:text-amber-200">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
          <span>
            当前材料包缺少 {missingSlotLabels.join('、') || '必需槽位'}。可补充材料后选「标准」模式，或在「智能」模式下填写审查要点后继续。
          </span>
        </div>
      ) : null}
    </section>
  )
}

function InfoTile({
  label,
  value,
  ok,
}: {
  label: string
  value: string
  ok: boolean
}) {
  return (
    <div className="rounded-lg border border-border/10 bg-background/80 px-3 py-2">
      <div className="text-[10px] text-muted">{label}</div>
      <div className={`mt-1 text-[12px] font-medium ${ok ? 'text-primary' : 'text-[rgb(var(--color-sa-gold))]'}`}>
        {value}
      </div>
    </div>
  )
}
