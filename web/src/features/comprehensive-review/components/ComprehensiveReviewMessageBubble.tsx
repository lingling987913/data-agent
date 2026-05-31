'use client'

import { Bot, CheckCircle2, Loader2, User, Wrench, XCircle } from 'lucide-react'
import MarkdownRenderer from '@/vendor/ui-core/MarkdownRenderer'
import type { ComprehensiveReviewMessage } from '@/features/comprehensive-review/utils/comprehensiveReviewMessages'
import { cn } from '@/lib/utils'

function statusIcon(status: ComprehensiveReviewMessage['status']) {
  if (status === 'running') return <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
  if (status === 'failed' || status === 'interrupted') return <XCircle className="h-3.5 w-3.5" aria-hidden />
  if (status === 'completed') return <CheckCircle2 className="h-3.5 w-3.5" aria-hidden />
  return null
}

function roleIcon(role: ComprehensiveReviewMessage['role']) {
  if (role === 'user') return <User className="h-4 w-4" aria-hidden />
  if (role === 'tool') return <Wrench className="h-3.5 w-3.5" aria-hidden />
  return <Bot className="h-4 w-4" aria-hidden />
}

function MessageChips({ chips, messageId }: { chips?: string[]; messageId: string }) {
  if (!chips?.length) return null
  return (
    <div className="mt-2 flex flex-wrap gap-1.5">
      {chips.map((chip) => (
        <span
          key={`${messageId}-${chip}`}
          className="rounded-full border border-border/15 bg-background/80 px-2 py-0.5 text-[10px] text-muted"
        >
          {chip}
        </span>
      ))}
    </div>
  )
}

export default function ComprehensiveReviewMessageBubble({ message }: { message: ComprehensiveReviewMessage }) {
  const failed = message.status === 'failed' || message.status === 'interrupted'

  if (message.role === 'result') {
    return (
      <article className="rounded-2xl border border-positive/25 bg-positive/5 shadow-soft">
        <div className="flex items-center gap-2 border-b border-positive/15 px-4 py-3">
          <CheckCircle2 className="h-4 w-4 text-positive" aria-hidden />
          <h3 className="text-[13px] font-semibold text-primary">{message.title}</h3>
        </div>
        <div className="max-h-[480px] overflow-y-auto px-4 py-4">
          <MarkdownRenderer className="max-w-none text-[13px] leading-relaxed text-primary/90">
            {message.body}
          </MarkdownRenderer>
        </div>
      </article>
    )
  }

  if (message.role === 'tool') {
    return (
      <article className="flex gap-3 pl-1">
        <div className="flex w-5 shrink-0 flex-col items-center pt-1">
          <span className={cn('h-2 w-2 rounded-full', failed ? 'bg-destructive' : message.status === 'completed' ? 'bg-positive' : 'bg-primaryAccent')} />
          <span className="mt-1 w-px flex-1 bg-border/30" />
        </div>
        <div className="min-w-0 flex-1 rounded-xl border border-border/10 bg-background/90 px-3 py-2.5">
          <div className="flex flex-wrap items-center gap-2">
            <span className="inline-flex items-center gap-1 text-[11px] font-semibold text-primary/85">
              {statusIcon(message.status)}
              {message.title}
            </span>
          </div>
          <p className="mt-1.5 whitespace-pre-wrap text-[12px] leading-relaxed text-muted">{message.body}</p>
          <MessageChips chips={message.chips} messageId={message.id} />
        </div>
      </article>
    )
  }

  const isUser = message.role === 'user'

  return (
    <article className={cn('flex gap-2', isUser ? 'justify-end' : 'justify-start')}>
      {!isUser ? (
        <div className="mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-border/15 bg-surface text-primaryAccent">
          {roleIcon(message.role)}
        </div>
      ) : null}
      <div
        className={cn(
          'max-w-[85%] rounded-2xl border px-4 py-3 shadow-soft',
          isUser
            ? 'border-primaryAccent/25 bg-primaryAccent/10'
            : failed
              ? 'border-destructive/20 bg-destructive/8'
              : 'border-border/15 bg-background',
        )}
      >
        <div className="flex flex-wrap items-center gap-2">
          <span className="inline-flex items-center gap-1 text-[11px] font-semibold text-primary">
            {statusIcon(message.status)}
            {isUser ? '你' : message.title}
          </span>
        </div>
        <p className={cn('mt-2 whitespace-pre-wrap text-[13px] leading-relaxed', isUser ? 'text-primary' : 'text-primary/85')}>
          {message.body}
        </p>
        <MessageChips chips={message.chips} messageId={message.id} />
      </div>
      {isUser ? (
        <div className="mt-1 flex h-8 w-8 shrink-0 items-center justify-center rounded-full border border-primaryAccent/20 bg-primaryAccent/10 text-primaryAccent">
          {roleIcon(message.role)}
        </div>
      ) : null}
    </article>
  )
}
