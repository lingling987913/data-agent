'use client'

import { useState } from 'react'
import { Users } from 'lucide-react'
import ReviewPlusAgentTraceDrawer from '@/features/review-plus-shared/components/harness/ReviewPlusAgentTraceDrawer'
import ReviewPlusCoverageMatrixPanel from '@/features/review-plus-shared/components/harness/ReviewPlusCoverageMatrixPanel'
import { formatElapsedMs } from '@/lib/aeroTerminology'
import type { ReviewPlusTaskDetail } from '@/features/review-plus-shared/types'
import { COVERAGE_STATUS_LABELS } from '@/features/review-plus-shared/types'
import {
  buildHarnessSummaryMetrics,
  formatAgentIdLabel,
  formatMaterialRoleLabel,
  getHarnessPlan,
  hasHarnessArtifacts,
  isCoreAgent,
  getTraceByAgentId,
  getDelegatedSpecialists,
} from '@/features/review-plus-shared/utils/reviewPlusHarnessViewModel'

function metricChip(label: string, value: string | number, tone?: 'default' | 'success' | 'warning' | 'danger' | 'brand') {
  const cls = tone === 'success' ? 'border-positive/20 bg-positive/8 text-positive'
    : tone === 'warning' ? 'border-warning/20 bg-warning/8 text-warning'
      : tone === 'danger' ? 'border-destructive/20 bg-destructive/8 text-destructive'
        : tone === 'brand' ? 'border-primaryAccent/20 bg-primaryAccent/8 text-primaryAccent'
          : 'border-border/25 bg-background text-primary'
  return (
    <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-[9px] font-medium ${cls}`}>
      <span className="text-muted/80">{label}</span>
      <span>{value}</span>
    </span>
  )
}

interface Props {
  task: ReviewPlusTaskDetail
  compact?: boolean
  onViewFindings?: () => void
  onOpenCoverage?: () => void
}

export default function ReviewPlusHarnessTeamPanel({
  task,
  compact = false,
  onViewFindings,
  onOpenCoverage,
}: Props) {
  const [traceAgentId, setTraceAgentId] = useState('')
  const [traceDrawerOpen, setTraceDrawerOpen] = useState(false)

  const openTraceDrawer = (agentId: string) => {
    setTraceAgentId(agentId)
    setTraceDrawerOpen(true)
  }

  if (!hasHarnessArtifacts(task)) {
    return (
      <p className="text-[10px] leading-relaxed text-muted">
        动态审查组结果尚未生成，请在本步骤完成后刷新查看。
      </p>
    )
  }

  const plan = getHarnessPlan(task)
  const traces = task.agent_run_traces || []
  const matrix = task.coverage_matrix
  const metrics = buildHarnessSummaryMetrics(plan, traces, matrix)
  const selectedIds = plan?.selected_agent_ids || []
  const reasons = plan?.selection_reasons || {}
  const signals = plan?.matched_signals || {}

  return (
    <>
      <div
        className={`space-y-3 ${compact ? '' : 'rounded-xl border border-border/20 bg-background p-3'}`}
        data-testid="review-plus-harness-panel"
      >
        {!compact ? (
          <div className="flex items-center gap-2">
            <span className="flex size-7 shrink-0 items-center justify-center rounded-lg border border-border/20 bg-surface text-primaryAccent">
              <Users size={14} aria-hidden />
            </span>
            <div>
              <h3 className="text-[12px] font-medium text-primary">动态审查组</h3>
              <p className="text-[10px] text-muted">按材料信号组队并逐环节执行，生成覆盖矩阵。</p>
            </div>
          </div>
        ) : null}

        <section className="space-y-2">
          <p className="text-[9px] font-medium text-muted">组队概要</p>
          <div className="flex flex-wrap gap-1.5">
            {metricChip('审查组', metrics.teamId !== '—' ? metrics.teamId : '默认组', 'brand')}
            {metricChip('选中环节', metrics.selectedCount)}
            {metricChip('核心必选', metrics.requiredCount)}
            {plan?.material_roles?.length ? metricChip('材料角色', plan.material_roles.length) : null}
          </div>
          {plan?.material_roles?.length ? (
            <div className="flex flex-wrap gap-1">
              {plan.material_roles.map((role) => (
                <span
                  key={role}
                  className="rounded-full border border-border/20 bg-surface px-2 py-0.5 text-[9px] text-muted"
                >
                  {formatMaterialRoleLabel(role)}
                </span>
              ))}
            </div>
          ) : null}
        </section>

        {selectedIds.length > 0 ? (
          <section className="space-y-2">
            <p className="text-[9px] font-medium text-muted">选中成员</p>
            <ul className="space-y-2">
              {selectedIds.map((agentId) => {
                const core = isCoreAgent(agentId, plan)
                const reason = String(reasons[agentId] || '').trim()
                const agentSignals = signals[agentId] || []
                const trace = getTraceByAgentId(task, agentId)
                const traceStatus = String(trace?.status || '')
                const traceFailed = traceStatus === 'failed'
                const delegated = getDelegatedSpecialists(task, agentId)

                return (
                  <li key={agentId} className={`rounded-lg border px-3 py-2 ${traceFailed ? 'border-destructive/25 bg-destructive/5' : 'border-border/15 bg-surface'}`}>
                    <button
                      type="button"
                      onClick={() => openTraceDrawer(agentId)}
                      className="flex w-full flex-wrap items-center gap-1.5 text-left"
                    >
                      <span className={`text-[11px] font-medium ${traceFailed ? 'text-destructive' : 'text-primary hover:text-primaryAccent'}`}>
                        {formatAgentIdLabel(agentId)}
                      </span>
                      {core ? (
                        <span className="rounded-full border border-primaryAccent/25 bg-primaryAccent/10 px-1.5 py-0.5 text-[9px] text-primaryAccent">
                          核心
                        </span>
                      ) : null}
                      {traceFailed ? (
                        <span className="rounded-full border border-destructive/25 bg-destructive/10 px-1.5 py-0.5 text-[9px] text-destructive">
                          执行失败
                        </span>
                      ) : null}
                      <span className="text-[9px] text-primaryAccent">查看详情</span>
                    </button>
                    {traceFailed && trace?.error_message ? (
                      <p className="mt-1 text-[10px] leading-relaxed text-destructive/90">{trace.error_message}</p>
                    ) : null}
                    {reason ? (
                      <p className="mt-1 text-[10px] leading-relaxed text-muted">{reason}</p>
                    ) : null}
                    {agentSignals.length > 0 ? (
                      <div className="mt-1.5 flex flex-wrap gap-1">
                        {agentSignals.map((sig) => (
                          <span
                            key={`${agentId}-${sig}`}
                            className="rounded-full border border-border/20 px-1.5 py-0.5 text-[9px] text-muted"
                          >
                            {sig}
                          </span>
                        ))}
                      </div>
                    ) : null}

                    {/* 委派执行专家 (Delegate Specialists) 展现 */}
                    {delegated.length > 0 ? (
                      <div className="mt-2.5 border-t border-border/10 pt-2.5">
                        <div className="flex items-center gap-1 mb-1.5 text-[9px] font-medium text-muted">
                          <span className="inline-block size-1 rounded-full bg-primaryAccent/60" />
                          <span>总师委派专家 (Delegate Specialists)</span>
                        </div>
                        <ul className="space-y-2 pl-2">
                          {delegated.map((spec) => (
                            <li key={spec.agent_id} className="rounded-md border border-border/10 bg-background/50 px-2 py-1.5 text-[10px]">
                              <div className="flex flex-wrap items-center gap-1.5">
                                <span className="font-medium text-primary">
                                  {spec.agent_name}
                                </span>
                                {spec.required ? (
                                  <span className="rounded bg-muted/15 px-1 py-0.2 text-[8px] text-muted">
                                    必选
                                  </span>
                                ) : (
                                  <span className="rounded border border-primaryAccent/15 bg-primaryAccent/5 px-1 py-0.2 text-[8px] text-primaryAccent">
                                    动态组队
                                  </span>
                                )}
                              </div>
                              <p className="mt-1 text-muted leading-relaxed text-[9px]">
                                <span className="font-semibold text-primary/70">职责：</span>{spec.role}
                              </p>
                              {spec.reason ? (
                                <p className="mt-0.5 text-muted/80 leading-relaxed text-[9px]">
                                  <span className="font-semibold text-primary/70">组队理由：</span>{spec.reason}
                                </p>
                              ) : null}
                              {spec.matched_signals?.length > 0 ? (
                                <div className="mt-1.5 flex flex-wrap gap-0.5">
                                  {spec.matched_signals.map((sig) => (
                                    <span
                                      key={`${spec.agent_id}-${sig}`}
                                      className="rounded bg-muted/5 border border-border/10 px-1 py-0.2 text-[8px] text-muted/80"
                                    >
                                      {sig}
                                    </span>
                                  ))}
                                </div>
                              ) : null}
                            </li>
                          ))}
                        </ul>
                      </div>
                    ) : null}
                  </li>
                )
              })}
            </ul>
          </section>
        ) : null}

        {traces.length > 0 ? (
          <section className="space-y-2">
            <p className="text-[9px] font-medium text-muted">执行轨迹</p>
            <div className="overflow-x-auto rounded-lg border border-border/20">
              <table className="w-full min-w-[360px] border-collapse text-left text-[10px]">
                <thead>
                  <tr className="border-b border-border/20 bg-background/80 text-muted">
                    <th className="px-2 py-1.5 font-medium">审查环节</th>
                    <th className="px-2 py-1.5 font-medium">状态</th>
                    <th className="px-2 py-1.5 font-medium">耗时</th>
                    <th className="px-2 py-1.5 font-medium" />
                  </tr>
                </thead>
                <tbody>
                  {traces.map((trace) => {
                    const status = String(trace.status || '')
                    const ok = status === 'completed'
                    const ms = trace.elapsed_ms
                    return (
                      <tr key={trace.agent_id} className="border-b border-border/10 align-top">
                        <td className="px-2 py-1.5">
                          <button
                            type="button"
                            onClick={() => openTraceDrawer(trace.agent_id)}
                            className="font-medium text-primary hover:text-primaryAccent hover:underline"
                          >
                            {formatAgentIdLabel(trace.agent_id)}
                          </button>
                        </td>
                        <td className="px-2 py-1.5">
                          <span className={`inline-flex rounded-full border px-1.5 py-0.5 text-[9px] font-medium ${ok ? 'border-positive/20 bg-positive/8 text-positive' : 'border-destructive/20 bg-destructive/8 text-destructive'}`}>
                            {ok ? '已完成' : status === 'failed' ? '失败' : status || '—'}
                          </span>
                        </td>
                        <td className="px-2 py-1.5 tabular-nums text-muted">
                          {formatElapsedMs(ms)}
                        </td>
                        <td className="px-2 py-1.5">
                          <button
                            type="button"
                            onClick={() => openTraceDrawer(trace.agent_id)}
                            className="text-[9px] font-medium text-primaryAccent hover:underline"
                          >
                            详情
                          </button>
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
            <div className="flex flex-wrap gap-1.5">
              {metricChip('已完成', metrics.traceCompleted, 'success')}
              {metrics.traceFailed > 0 ? metricChip('失败', metrics.traceFailed, 'danger') : null}
            </div>
          </section>
        ) : null}

        {matrix?.summary ? (
          <section className="space-y-2">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <p className="text-[9px] font-medium text-muted">覆盖矩阵</p>
              {onOpenCoverage ? (
                <button
                  type="button"
                  onClick={onOpenCoverage}
                  className="text-[9px] font-medium text-primaryAccent hover:underline"
                >
                  查看完整覆盖矩阵
                </button>
              ) : null}
            </div>
            <div className="flex flex-wrap gap-1.5">
              {metricChip('已闭合', metrics.closedCount, 'success')}
              {metricChip(COVERAGE_STATUS_LABELS.task_only, metrics.taskOnlyCount, 'warning')}
              {metricChip(COVERAGE_STATUS_LABELS.subject_only, metrics.subjectOnlyCount, 'warning')}
              {metricChip(COVERAGE_STATUS_LABELS.missing, metrics.missingCount, metrics.missingCount > 0 ? 'danger' : 'default')}
              {metricChip('总行数', metrics.rowCount, 'brand')}
            </div>
            {!compact && matrix.rows?.length ? (
              <ReviewPlusCoverageMatrixPanel
                matrix={matrix}
                maxRows={8}
                onViewFindings={onViewFindings}
                onOpenCoverage={onOpenCoverage}
              />
            ) : null}
          </section>
        ) : null}
      </div>

      <ReviewPlusAgentTraceDrawer
        task={task}
        agentId={traceAgentId}
        open={traceDrawerOpen}
        onClose={() => setTraceDrawerOpen(false)}
        onSelectAgentId={(id) => setTraceAgentId(id)}
      />
    </>
  )
}
