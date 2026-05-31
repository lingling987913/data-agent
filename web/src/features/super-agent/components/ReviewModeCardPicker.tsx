'use client'

import { Brain, ClipboardList, Search } from 'lucide-react'

export type ReviewModeCardId = 'smart' | 'standard' | 'special' | 'specialized'

const CARDS = [
  { id: 'special' as const, icon: Search, title: 'GNC 专项', desc: '制导导航与控制专项审查' },
  { id: 'standard' as const, icon: ClipboardList, title: '文件组审查', desc: '规则/任务书/被审材料对齐审查' },
  { id: 'smart' as const, icon: Brain, title: '通用审查', desc: '智能综合审查与动态专家组队' },
] as const

export default function ReviewModeCardPicker({
  reviewModeCard,
  onChange,
  recommendedCard,
  title = '审查模式',
  testId = 'super-agent-review-mode-cards',
}: {
  reviewModeCard: ReviewModeCardId
  onChange: (card: ReviewModeCardId) => void
  recommendedCard?: ReviewModeCardId
  title?: string
  testId?: string
}) {
  return (
    <div data-testid={testId}>
      <div className="mb-2 text-[11px] font-medium text-muted">{title}</div>
      <div className="grid gap-2 sm:grid-cols-3">
        {CARDS.map((card) => {
          const Icon = card.icon
          const selected =
            reviewModeCard === card.id
            || (card.id === 'special' && reviewModeCard === 'specialized')
          const recommended =
            recommendedCard === card.id
            || (card.id === 'special' && recommendedCard === 'specialized')
          return (
            <button
              key={card.id}
              type="button"
              onClick={() => onChange(card.id)}
              className={`rounded-lg border px-3 py-3 text-left transition ${
                selected
                  ? 'border-primaryAccent/45 bg-primaryAccent/10 ring-1 ring-primaryAccent/30'
                  : 'border-border/15 bg-background/60 hover:border-primaryAccent/25'
              }`}
            >
              <div className="flex items-center justify-between gap-2">
                <Icon className={`h-4 w-4 ${selected ? 'text-primaryAccent' : 'text-muted'}`} aria-hidden />
                {recommended ? (
                  <span className="rounded-full bg-brand/15 px-2 py-0.5 text-[10px] font-medium text-brand">
                    推荐
                  </span>
                ) : null}
              </div>
              <div className="mt-1.5 text-[13px] font-semibold text-primary">{card.title}</div>
              <div className="mt-0.5 text-[10px] text-muted">{card.desc}</div>
            </button>
          )
        })}
      </div>
    </div>
  )
}
