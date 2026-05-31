'use client'

import Link from 'next/link'
import { ArrowUpRight, Loader2, Paperclip, Send, Square, UploadCloud } from 'lucide-react'
import ComprehensiveReviewMessageBubble from '@/features/comprehensive-review/components/ComprehensiveReviewMessageBubble'
import type { ComprehensiveReviewMessage } from '@/features/comprehensive-review/utils/comprehensiveReviewMessages'
import type { SuperAgentRoute, SuperAgentRun } from '@/features/super-agent/types'
import { buildSuperAgentRunUrl } from '@/features/super-agent/utils/superAgentWizardRecovery'
import { AGENT_RUN_STATUS_LABELS, ROUTE_LABELS } from '@/lib/aeroTerminology'

interface Props {
  files: File[]
  objective: string
  selectedRoute: SuperAgentRoute
  draftMessage: string
  messages: ComprehensiveReviewMessage[]
  run?: SuperAgentRun | null
  busy: boolean
  canResume: boolean
  resumeBusy: boolean
  canManualInterrupt?: boolean
  interruptBusy?: boolean
  onObjectiveChange: (value: string) => void
  onSelectedRouteChange: (value: SuperAgentRoute) => void
  onDraftMessageChange: (value: string) => void
  onFilesChange: (files: File[]) => void
  onStart: () => void
  onSendMessage: () => void
  onResume: () => void
  onInterrupt: () => void
  onManualInterrupt?: () => void
}

function statusBadgeClass(status: string): string {
  if (status === 'completed') return 'border-positive/25 bg-positive/10 text-positive'
  if (status === 'failed') return 'border-destructive/25 bg-destructive/10 text-destructive'
  if (status === 'running') return 'border-primaryAccent/25 bg-primaryAccent/10 text-primaryAccent'
  if (status === 'interrupted' || status === 'limited') return 'border-[rgb(var(--color-sa-gold))]/30 bg-[rgb(var(--color-sa-gold))]/10 text-[rgb(var(--color-sa-gold))]'
  return 'border-border/20 bg-surface text-muted'
}

export default function ComprehensiveReviewChat({
  files,
  objective,
  selectedRoute,
  draftMessage,
  messages,
  run,
  busy,
  canResume,
  resumeBusy,
  canManualInterrupt = false,
  interruptBusy = false,
  onObjectiveChange,
  onSelectedRouteChange,
  onDraftMessageChange,
  onFilesChange,
  onStart,
  onSendMessage,
  onResume,
  onInterrupt,
  onManualInterrupt,
}: Props) {
  return (
    <div className="grid min-h-[calc(100vh-96px)] gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
      <section className="flex min-h-[620px] flex-col overflow-hidden rounded-2xl border border-border/15 bg-background shadow-soft">
        <div className="border-b border-border/15 bg-background-secondary/60 px-5 py-4">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h1 className="text-base font-semibold text-primary">综合审查对话</h1>
              <p className="mt-1 text-[11px] text-muted">输入审查目标并附加文件，Agent 会解析材料并返回各审查节点结果。</p>
            </div>
            {run ? (
              <div className="rounded-xl border border-border/15 bg-background px-3 py-2">
                <div className="max-w-[280px] truncate text-[12px] font-medium text-primary">{run.name || run.run_id}</div>
                <div className="mt-1 flex flex-wrap items-center gap-1.5">
                  <span className={`rounded-full border px-2 py-0.5 text-[10px] ${statusBadgeClass(run.status)}`}>
                    {AGENT_RUN_STATUS_LABELS[run.status] || run.status}
                  </span>
                  <span className="rounded-full border border-border/15 bg-surface px-2 py-0.5 text-[10px] text-muted">
                    {ROUTE_LABELS[run.requested_route] || run.requested_route}
                  </span>
                </div>
                {run.run_id ? (
                  <div className="mt-2 flex flex-wrap items-center gap-2">
                    <Link
                      href={buildSuperAgentRunUrl(run.run_id)}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="inline-flex items-center gap-1 text-[11px] font-medium text-primaryAccent hover:underline"
                    >
                      查看详情
                      <ArrowUpRight className="h-3 w-3" aria-hidden />
                    </Link>
                    {canManualInterrupt ? (
                      <button
                        type="button"
                        onClick={onManualInterrupt}
                        disabled={interruptBusy}
                        className="inline-flex items-center gap-1 rounded-lg border border-destructive/25 bg-destructive/8 px-2 py-1 text-[11px] font-medium text-destructive hover:bg-destructive/12 disabled:cursor-not-allowed disabled:opacity-60"
                      >
                        {interruptBusy ? <Loader2 className="h-3 w-3 animate-spin" aria-hidden /> : <Square className="h-3 w-3" aria-hidden />}
                        手动中断
                      </button>
                    ) : null}
                  </div>
                ) : null}
              </div>
            ) : null}
          </div>
        </div>
        <div className="flex-1 space-y-4 overflow-y-auto bg-gradient-to-b from-background-secondary/30 to-background px-5 py-5">
          {messages.length ? messages.map((message) => (
            <ComprehensiveReviewMessageBubble key={message.id} message={message} />
          )) : (
            <div className="flex h-full min-h-[360px] items-center justify-center rounded-2xl border border-dashed border-border/20 bg-surface/40 px-6 text-center">
              <div>
                <UploadCloud className="mx-auto h-8 w-8 text-primaryAccent" aria-hidden />
                <p className="mt-3 text-sm font-medium text-primary">上传材料并输入审查目标后开始综合审查</p>
                <p className="mt-1 text-[11px] text-muted">支持一个或多个文件，系统会先生成 Markdown，再进入 GNC 与文件组审查。</p>
              </div>
            </div>
          )}
        </div>
        {canManualInterrupt ? (
          <div className="border-t border-border/15 bg-background-secondary/70 px-5 py-3">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <p className="text-[12px] text-primary">审查正在执行中，如需停止可手动中断；中断后可继续审查恢复进度。</p>
              <button
                type="button"
                onClick={onManualInterrupt}
                disabled={interruptBusy}
                className="inline-flex items-center gap-2 rounded-lg border border-destructive/25 bg-destructive/8 px-3 py-2 text-[12px] font-medium text-destructive hover:bg-destructive/12 disabled:cursor-not-allowed disabled:opacity-60"
              >
                {interruptBusy ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : <Square className="h-3.5 w-3.5" aria-hidden />}
                手动中断
              </button>
            </div>
          </div>
        ) : null}
        {canResume ? (
          <div className="border-t border-border/15 bg-[rgb(var(--color-sa-gold))]/8 px-5 py-3">
            <div className="flex flex-wrap items-center justify-between gap-3">
              <p className="text-[12px] text-primary">审查已中断或长时间无进展，可以继续审查或中断本次会话。</p>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={onResume}
                  disabled={resumeBusy}
                  className="inline-flex items-center gap-2 rounded-lg bg-primaryAccent px-3 py-2 text-[12px] font-medium text-white disabled:opacity-60"
                >
                  {resumeBusy ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : <Send className="h-3.5 w-3.5" aria-hidden />}
                  继续审查
                </button>
                <button
                  type="button"
                  onClick={onInterrupt}
                  className="inline-flex items-center gap-2 rounded-lg border border-border/20 bg-background px-3 py-2 text-[12px] font-medium text-primary hover:bg-surface"
                >
                  <Square className="h-3.5 w-3.5" aria-hidden />
                  中断审查
                </button>
              </div>
            </div>
          </div>
        ) : null}
        <div className="border-t border-border/20 bg-background-secondary/80 px-4 py-3">
          {files.length ? (
            <div className="mb-2 flex flex-wrap gap-2">
              {files.map((file) => (
                <span key={`${file.name}-${file.size}`} className="inline-flex max-w-[220px] items-center gap-1 truncate rounded-full border border-primaryAccent/15 bg-primaryAccent/8 px-2 py-1 text-[10px] text-primaryAccent">
                  <Paperclip className="h-3 w-3 shrink-0" aria-hidden />
                  <span className="truncate">{file.name}</span>
                </span>
              ))}
            </div>
          ) : null}
          <div className="rounded-2xl border border-border/15 bg-background p-2 shadow-soft">
            <textarea
              value={draftMessage}
              onChange={(event) => onDraftMessageChange(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter' && !event.shiftKey) {
                  event.preventDefault()
                  onSendMessage()
                }
              }}
              placeholder="输入审查目标，例如：请对这些材料做综合审查，重点关注 GNC 设计一致性和文件组符合性。"
              className="min-h-[72px] w-full resize-none bg-transparent px-2 py-2 text-[13px] leading-relaxed text-primary outline-none placeholder:text-muted"
            />
            <div className="flex items-center justify-between gap-2 border-t border-border/10 pt-2">
              <label className="inline-flex cursor-pointer items-center gap-2 rounded-lg border border-border/15 bg-background px-3 py-2 text-[11px] font-medium text-primary hover:bg-background-secondary">
                <Paperclip className="h-3.5 w-3.5" aria-hidden />
                添加文件
                <input
                  type="file"
                  multiple
                  className="hidden"
                  onChange={(event) => onFilesChange(Array.from(event.target.files || []))}
                />
              </label>
              <button
                type="button"
                onClick={onSendMessage}
                disabled={busy || (!draftMessage.trim() && !files.length)}
                className="inline-flex items-center gap-2 rounded-lg bg-primaryAccent px-4 py-2 text-[11px] font-semibold text-white disabled:cursor-not-allowed disabled:opacity-60"
              >
                {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden /> : <Send className="h-3.5 w-3.5" aria-hidden />}
                发送
              </button>
            </div>
          </div>
        </div>
      </section>

      <aside className="rounded-2xl border border-border/15 bg-surface p-4 shadow-soft">
        <div className="text-[11px] font-semibold text-primary">Agent 上下文</div>
        <p className="mt-1 text-[10px] leading-relaxed text-muted">这里显示当前审查目标和附件，也可以直接修改后点击“开始综合审查”。</p>
        <label className="mt-3 block text-[11px] font-semibold text-primary" htmlFor="comprehensive-objective">
          当前审查目标
        </label>
        <textarea
          id="comprehensive-objective"
          value={objective}
          onChange={(event) => onObjectiveChange(event.target.value)}
          className="mt-2 min-h-[112px] w-full resize-none rounded-xl border border-border/15 bg-background px-3 py-2 text-[12px] leading-relaxed text-primary outline-none focus:border-primaryAccent/40"
        />
        <label className="mt-4 block text-[11px] font-semibold text-primary" htmlFor="comprehensive-route">
          路由
        </label>
        <select
          id="comprehensive-route"
          value={selectedRoute}
          onChange={(event) => onSelectedRouteChange(event.target.value as SuperAgentRoute)}
          className="mt-2 w-full rounded-xl border border-border/15 bg-background px-3 py-2 text-[12px] text-primary outline-none focus:border-primaryAccent/40"
        >
          <option value="auto">{ROUTE_LABELS.auto}</option>
          <option value="review_plus">{ROUTE_LABELS.review_plus}</option>
          <option value="gnc_review_only">{ROUTE_LABELS.gnc_review_only}</option>
          <option value="structure_only">{ROUTE_LABELS.structure_only}</option>
          <option value="hybrid">{ROUTE_LABELS.hybrid}</option>
        </select>
        <p className="mt-1 text-[10px] leading-relaxed text-muted">
          默认自动选择；解析后会按推荐场景路由到 GNC 审查或文件组审查。
        </p>
        <label className="mt-4 block text-[11px] font-semibold text-primary" htmlFor="comprehensive-files">
          上传文件
        </label>
        <input
          id="comprehensive-files"
          type="file"
          multiple
          className="mt-2 block w-full rounded-xl border border-dashed border-border/25 bg-background px-3 py-6 text-[11px] text-muted file:mr-3 file:rounded-md file:border-0 file:bg-primaryAccent file:px-3 file:py-1.5 file:text-[11px] file:font-medium file:text-white"
          onChange={(event) => onFilesChange(Array.from(event.target.files || []))}
        />
        {files.length ? (
          <div className="mt-3 space-y-2">
            {files.map((file) => (
              <div key={`${file.name}-${file.size}`} className="rounded-lg border border-border/15 bg-background px-3 py-2 text-[11px] text-primary">
                <div className="truncate font-medium">{file.name}</div>
                <div className="mt-0.5 text-muted">{(file.size / 1024 / 1024).toFixed(2)} MB</div>
              </div>
            ))}
          </div>
        ) : null}
        <button
          type="button"
          onClick={() => onStart()}
          disabled={busy || !files.length}
          className="mt-4 inline-flex w-full items-center justify-center gap-2 rounded-xl bg-primaryAccent px-4 py-2.5 text-[12px] font-semibold text-white shadow-soft transition hover:opacity-95 disabled:cursor-not-allowed disabled:opacity-60"
        >
          {busy ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : <Send className="h-4 w-4" aria-hidden />}
          开始综合审查
        </button>
      </aside>
    </div>
  )
}
