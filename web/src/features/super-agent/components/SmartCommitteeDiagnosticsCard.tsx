'use client'

import { AlertTriangle, Workflow } from 'lucide-react'
import type { MaterialClassification, SuperAgentRun } from '@/features/super-agent/types'
import {
  resolveSmartCommitteeDiagnostics,
} from '@/features/super-agent/utils/smartCommitteeDiagnostics'

function executionModeLabel(mode: string): string {
  if (mode === 'harness') return 'Harness 专家审查'
  if (mode === 'generic_llm_harness') return 'LLM Harness 专家审查'
  if (mode === 'deterministic_pre_review') return '确定性预审'
  if (mode === 'blocked') return '阻塞'
  if (mode === 'failed') return '失败'
  return mode || '未知'
}

export default function SmartCommitteeDiagnosticsCard({
  run,
  classification,
  className = '',
  testId,
}: {
  run: SuperAgentRun
  classification?: MaterialClassification
  className?: string
  testId?: string
}) {
  const diagnostics = resolveSmartCommitteeDiagnostics(run, classification)
  if (!diagnostics.visible) return null

  const summary = diagnostics.executionModeSummary
  const board = diagnostics.taskBoardSummary
  const showLimitedWarning = diagnostics.limited

  return (
    <section
      className={`rounded-xl border border-border/15 bg-background/70 p-4 ${className}`.trim()}
      data-testid={testId}
    >
      <div className="mb-3 flex items-center gap-2 text-[12px] font-medium text-primary">
        <Workflow className="h-4 w-4 text-primaryAccent" aria-hidden />
        执行诊断 / 调度详情
      </div>
      <p className="text-[11px] text-muted">本次为智能审查调度结果</p>

      {diagnostics.executionModeSummaryLines.length ? (
        <ul className="mt-2 space-y-1 text-[11px] text-primary">
          {diagnostics.executionModeSummaryLines.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      ) : null}

      <div className="mt-3 grid gap-2 sm:grid-cols-2">
        <div className="rounded-lg border border-border/10 px-3 py-2">
          <div className="text-[10px] text-muted/70">执行模式</div>
          <div className="mt-1 text-[12px] font-medium text-primary">{diagnostics.executionModeLabel}</div>
          {summary ? (
            <div className="mt-1 text-[10px] text-muted">
              Harness {summary.harness_count || 0}
              {' · '}LLM Harness {summary.generic_llm_harness_count || 0}
              {' · '}确定性 {summary.deterministic_count || 0}
              {' · '}失败 {summary.failed_count || 0} · 阻塞 {summary.blocked_count || 0}
            </div>
          ) : null}
        </div>

        {board ? (
          <div className="rounded-lg border border-border/10 px-3 py-2">
            <div className="text-[10px] text-muted/70">TaskBoard</div>
            <div className="mt-1 text-[12px] font-medium text-primary">
              共 {board.task_count || 0} 任务
              {diagnostics.taskSpecCount ? ` · TaskSpec ${diagnostics.taskSpecCount}` : ''}
            </div>
            <div className="mt-1 text-[10px] text-muted">
              完成 {board.completed || 0} · 失败 {board.failed || 0}
              {' · '}阻塞 {board.blocked || 0}
              {(board.skipped ?? board.status_counts?.skipped) ? (
                <> · 跳过 {board.skipped ?? board.status_counts?.skipped ?? 0}</>
              ) : null}
              {' · '}受限 {board.limited || 0}
            </div>
          </div>
        ) : diagnostics.taskSpecCount ? (
          <div className="rounded-lg border border-border/10 px-3 py-2">
            <div className="text-[10px] text-muted/70">TaskSpec</div>
            <div className="mt-1 text-[12px] font-medium text-primary">
              共 {diagnostics.taskSpecCount} 任务规格
            </div>
          </div>
        ) : null}

        {diagnostics.domainId ? (
          <div className="rounded-lg border border-border/10 px-3 py-2">
            <div className="text-[10px] text-muted/70">Domain</div>
            <div className="mt-1 text-[12px] font-medium text-primary">{diagnostics.domainId}</div>
            {diagnostics.routeSignalHits?.length ? (
              <div className="mt-1 text-[10px] text-muted">
                路由信号：{diagnostics.routeSignalHits.slice(0, 6).join(' · ')}
              </div>
            ) : null}
          </div>
        ) : null}

        {diagnostics.bootstrapSummary?.synthetic_context_label ? (
          <div className="rounded-lg border border-border/10 px-3 py-2 sm:col-span-2">
            <div className="text-[10px] text-muted/70">合成审查上下文</div>
            <div className="mt-1 text-[12px] font-medium text-primary">
              {diagnostics.bootstrapSummary.synthetic_context_label}
            </div>
            <div className="mt-1 text-[10px] text-muted">
              合成检查项 {diagnostics.bootstrapSummary.synthetic_check_item_count || 0}
              {' · '}证据引用 {diagnostics.bootstrapSummary.source_evidence_ref_count || 0}
            </div>
          </div>
        ) : null}
      </div>

      {diagnostics.citationCoverage != null ? (
        <div className="mt-2 text-[10px] text-muted">
          引用/证据覆盖率：{Math.round(diagnostics.citationCoverage * 100)}%
          {diagnostics.citationCoverageSource ? `（${diagnostics.citationCoverageSource}）` : ''}
        </div>
      ) : null}

      {diagnostics.hasArbiterSummary ? (
        <div className="mt-2 rounded-lg border border-border/10 px-3 py-2 text-[10px] text-muted">
          <div className="text-[10px] text-muted/70">Arbiter 汇总</div>
          <div className="mt-1 text-[11px] text-primary">
            {diagnostics.arbiterConsensusSummary || '已完成委员会汇总仲裁'}
          </div>
        </div>
      ) : null}

      {diagnostics.replanSuggestions.length ? (
        <div className="mt-2">
          <div className="mb-1 text-[10px] text-muted/70">重规划建议</div>
          <ul className="space-y-1 text-[10px] text-muted">
            {diagnostics.replanSuggestions.slice(0, 4).map((item) => (
              <li key={item}>{item}</li>
            ))}
          </ul>
        </div>
      ) : null}

      {diagnostics.specialistModes.length ? (
        <div className="mt-3">
          <div className="mb-1 text-[10px] text-muted/70">专家 execution_mode</div>
          <div className="flex flex-wrap gap-1.5">
            {diagnostics.specialistModes.map((item) => (
              <span
                key={item.agentId}
                className="rounded-full border border-border/15 bg-surface px-2 py-0.5 text-[10px] text-primary"
                title={item.fallbackReason || undefined}
              >
                {item.title}: {executionModeLabel(item.executionMode)}
                {item.fallbackReason ? ` · ${item.fallbackReason}` : ''}
              </span>
            ))}
          </div>
        </div>
      ) : null}

      {showLimitedWarning ? (
        <div className="mt-3 flex gap-2 rounded-lg border border-[rgb(var(--color-sa-gold))]/30 bg-[rgb(var(--color-sa-gold))]/10 px-3 py-2 text-[11px] text-[rgb(var(--color-sa-gold))]">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
          <p>
            当前包含确定性预审或降级执行，不等同完整 LLM 专家审查。建议补充检查单/任务书后进行完整 Review-Plus，或启用/验证 Harness 专家审查。
          </p>
        </div>
      ) : null}

      {diagnostics.degradationNotes.length ? (
        <ul className="mt-3 space-y-1 text-[10px] text-muted">
          {diagnostics.degradationNotes.slice(0, 4).map((note) => (
            <li key={note}>{note}</li>
          ))}
        </ul>
      ) : null}
    </section>
  )
}
