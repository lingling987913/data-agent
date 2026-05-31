import Link from 'next/link'
import { Bot, MessageSquare, Sparkles } from 'lucide-react'
import { APP_TERMS, COMPREHENSIVE_REVIEW_TERMS, SUPER_AGENT_TERMS } from '@/lib/aeroTerminology'

function EntryCard({
  href,
  icon: Icon,
  title,
  formLabel,
  subtitle,
  tags,
}: {
  href: string
  icon: typeof Bot
  formLabel: string
  title: string
  subtitle: string
  tags: readonly string[]
}) {
  return (
    <Link
      href={href}
      className="group rounded-xl border border-border/15 bg-surface p-5 shadow-soft transition hover:border-primaryAccent/30 hover:shadow-medium"
    >
      <div className="flex items-start justify-between gap-3">
        <Icon className="h-7 w-7 shrink-0 text-primaryAccent" aria-hidden />
        <span className="rounded-full border border-primaryAccent/25 bg-primaryAccent/10 px-2.5 py-0.5 text-[10px] font-medium text-primaryAccent">
          {formLabel}
        </span>
      </div>
      <div className="mt-4 text-base font-semibold text-primary group-hover:text-primaryAccent">{title}</div>
      <p className="mt-2 text-[11px] leading-relaxed text-muted">{subtitle}</p>
      <div className="mt-4">
        <p className="mb-2 text-[10px] font-medium text-muted/80">可路由至</p>
        <div className="flex flex-wrap gap-2 text-[10px] text-muted">
          {tags.map((tag) => (
            <span key={tag} className="rounded-full border border-border/15 bg-background px-2 py-0.5">
              {tag}
            </span>
          ))}
        </div>
      </div>
    </Link>
  )
}

export default function HomePage() {
  return (
    <div className="mx-auto flex min-h-[calc(100vh-57px)] max-w-4xl items-center px-4 py-8">
      <div className="w-full">
        <div className="mb-6 flex items-center gap-2">
          <Sparkles className="h-5 w-5 text-primaryAccent" aria-hidden />
          <h1 className="text-lg font-semibold text-primary">{APP_TERMS.brandName}</h1>
        </div>
        <p className="mb-5 text-[11px] leading-relaxed text-muted">
          选择审查入口后，系统将按材料与目标自动路由至 GNC 专家审查、智能动态审查或文件组审查。
        </p>
        <div className="grid gap-4 md:grid-cols-2">
          <EntryCard
            href="/super-agent"
            icon={Bot}
            title={SUPER_AGENT_TERMS.homeTitle}
            formLabel={SUPER_AGENT_TERMS.homeForm}
            subtitle={SUPER_AGENT_TERMS.homeSubtitle}
            tags={SUPER_AGENT_TERMS.homeTags}
          />
          <EntryCard
            href="/comprehensive-review"
            icon={MessageSquare}
            title={COMPREHENSIVE_REVIEW_TERMS.homeTitle}
            formLabel={COMPREHENSIVE_REVIEW_TERMS.homeForm}
            subtitle={COMPREHENSIVE_REVIEW_TERMS.homeSubtitle}
            tags={COMPREHENSIVE_REVIEW_TERMS.homeTags}
          />
        </div>
      </div>
    </div>
  )
}
