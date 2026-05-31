'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import Link from 'next/link'
import {
  Activity,
  Bot,
  CheckCircle2,
  GitBranch,
  Loader2,
  Play,
  RefreshCw,
  Route,
  ShieldAlert,
  Sparkles,
} from 'lucide-react'
import {
  AGENT_RUN_STATUS_LABELS,
  PROCESSING_MODE_LABELS,
  REVIEW_MODE_LABELS,
  REVIEW_PLUS_TERMS,
  ROUTE_LABELS,
  SUPER_AGENT_TERMS,
  formatElapsedMs,
} from '@/lib/aeroTerminology'
import {
  createSuperAgentRun,
  executeSuperAgentRun,
  getSuperAgentCapabilities,
  listSuperAgentRuns,
  runSuperAgentBenchmark,
} from '@/features/super-agent/api'
import SuperAgentProcessingView from '@/features/super-agent/components/SuperAgentProcessingView'
import type {
  CreateSuperAgentRunInput,
  SuperAgentCapabilities,
  SuperAgentRun,
  SuperAgentSkillTrace,
} from '@/features/super-agent/types'
import ExecutionMetricsPanel from '@/features/super-agent/components/ExecutionMetricsPanel'
import { filterBusinessLines } from '@/features/super-agent/utils/diagnosticsSanitizer'

const STATUS_LABELS = AGENT_RUN_STATUS_LABELS

function relativeTime(isoStr: string): string {
  if (!isoStr) return ''
  const diff = Date.now() - new Date(isoStr).getTime()
  const mins = Math.floor(diff / 60000)
  if (mins < 1) return '刚刚'
  if (mins < 60) return `${mins} 分钟前`
  const hours = Math.floor(mins / 60)
  if (hours < 24) return `${hours} 小时前`
  return new Date(isoStr).toLocaleDateString('zh-CN', { month: 'short', day: 'numeric' })
}

function statusTone(status: string): string {
  if (status === 'completed') return 'border-positive/25 bg-positive/10 text-positive'
  if (status === 'limited') return 'border-[rgb(var(--color-sa-gold))]/30 bg-[rgb(var(--color-sa-gold))]/10 text-[rgb(var(--color-sa-gold))]'
  if (status === 'failed') return 'border-destructive/25 bg-destructive/10 text-destructive'
  if (status === 'interrupted') return 'border-[rgb(var(--color-sa-gold))]/30 bg-[rgb(var(--color-sa-gold))]/10 text-[rgb(var(--color-sa-gold))]'
  if (status === 'running') return 'border-primaryAccent/25 bg-primaryAccent/10 text-primaryAccent'
  return 'border-border/20 bg-surface text-muted'
}

function compactJson(value: unknown): string {
  if (!value || (typeof value === 'object' && Object.keys(value as Record<string, unknown>).length === 0)) {
    return '{}'
  }
  return JSON.stringify(value, null, 2)
}

function SkillTraceRow({ trace }: { trace: SuperAgentSkillTrace }) {
  return (
    <details className="rounded-lg border border-border/15 bg-surface px-3 py-2">
      <summary className="flex cursor-pointer list-none items-center gap-3">
        <span className={`h-2 w-2 shrink-0 rounded-full ${trace.status === 'completed' ? 'bg-positive' : trace.status === 'failed' ? 'bg-destructive' : trace.status === 'skipped' ? 'bg-[rgb(var(--color-sa-gold))]' : 'bg-primaryAccent'}`} />
        <span className="min-w-0 flex-1 truncate text-[12px] font-medium text-primary">{trace.skill_id}</span>
        <span className="shrink-0 text-[10px] text-muted/55">{formatElapsedMs(trace.elapsed_ms)}</span>
      </summary>
      <div className="mt-3 grid gap-3 text-[11px] text-muted md:grid-cols-2">
        <div>
          <div className="mb-1 font-medium text-primary/80">输入</div>
          <pre className="max-h-40 overflow-auto rounded-md bg-background p-2">{compactJson(trace.input_summary)}</pre>
        </div>
        <div>
          <div className="mb-1 font-medium text-primary/80">输出</div>
          <pre className="max-h-40 overflow-auto rounded-md bg-background p-2">{compactJson(trace.output_summary)}</pre>
        </div>
      </div>
      {trace.warnings.length ? (
        <div className="mt-3 space-y-1">
          {trace.warnings.map((warning) => (
            <div key={warning} className="rounded-md bg-[rgb(var(--color-sa-gold))]/10 px-2 py-1 text-[11px] text-[rgb(var(--color-sa-gold))]">
              {warning}
            </div>
          ))}
        </div>
      ) : null}
    </details>
  )
}

function RunDetail({ run, onExecute, executing }: { run: SuperAgentRun | null; onExecute: (runId: string) => void; executing: string }) {
  if (!run) {
    return (
      <div className="flex min-h-[360px] items-center justify-center rounded-xl border border-border/15 bg-surface px-6 text-center shadow-soft">
        <div>
          <Bot className="mx-auto h-8 w-8 text-muted/45" aria-hidden />
          <p className="mt-3 text-sm font-medium text-primary">{SUPER_AGENT_TERMS.selectRun}</p>
        </div>
      </div>
    )
  }

  const route = run.route_decision?.route || run.requested_route
  const warnings = filterBusinessLines([
    ...(run.quality_report?.warnings || []),
    ...(run.trace_report?.degradation_summary || []),
  ])
  const showProcessingLayout =
    run.status === 'running' || run.status === 'interrupted' || (run.status === 'failed' && run.skill_traces.length > 0)

  if (showProcessingLayout) {
    return (
      <div className="rounded-xl border border-border/15 bg-surface shadow-soft">
        <div className="border-b border-border/10 px-4 py-3">
          <div className="flex flex-wrap items-center gap-2">
            <h2 className="truncate text-base font-semibold text-primary">{run.name || run.run_id}</h2>
            <span className={`rounded-full border px-2 py-0.5 text-[10px] ${statusTone(run.status)}`}>
              {STATUS_LABELS[run.status] || run.status}
            </span>
          </div>
        </div>
        <div className="p-4">
          <SuperAgentProcessingView
            run={run}
            classification={run.classification?.doc_type ? run.classification : null}
            isRunning={executing === run.run_id || run.status === 'running'}
            onResume={() => onExecute(run.run_id)}
            resumeBusy={executing === run.run_id}
          />
        </div>
      </div>
    )
  }

  return (
    <div className="rounded-xl border border-border/15 bg-surface shadow-soft">
      <div className="border-b border-border/10 px-4 py-4">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="truncate text-base font-semibold text-primary">{run.name || run.run_id}</h2>
              <span className={`rounded-full border px-2 py-0.5 text-[10px] ${statusTone(run.status)}`}>
                {STATUS_LABELS[run.status] || run.status}
              </span>
            </div>
            <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-muted/70">
              <span>{run.run_id}</span>
              <span>{relativeTime(run.updated_at)}</span>
              {run.source_review_id ? <span>{run.source_review_id}</span> : null}
            </div>
          </div>
          <button
            type="button"
            onClick={() => onExecute(run.run_id)}
            disabled={Boolean(executing)}
            className="inline-flex min-h-9 shrink-0 items-center justify-center gap-2 rounded-lg bg-brand px-3 text-[11px] font-medium text-white disabled:opacity-50"
          >
            {executing === run.run_id ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : <Play className="h-4 w-4" aria-hidden />}
            执行
          </button>
        </div>

        <div className="mt-4 grid gap-3 md:grid-cols-3">
          <div className="rounded-lg border border-border/10 bg-background/70 px-3 py-2">
            <div className="flex items-center gap-2 text-[10px] text-muted/65">
              <Route className="h-3.5 w-3.5" aria-hidden />
              路由
            </div>
            <div className="mt-1 text-sm font-semibold text-primary">{ROUTE_LABELS[route] || route}</div>
          </div>
          <div className="rounded-lg border border-border/10 bg-background/70 px-3 py-2">
            <div className="flex items-center gap-2 text-[10px] text-muted/65">
              <GitBranch className="h-3.5 w-3.5" aria-hidden />
              技能
            </div>
            <div className="mt-1 text-sm font-semibold text-primary">{run.skill_traces.length}</div>
          </div>
          <div className="rounded-lg border border-border/10 bg-background/70 px-3 py-2">
            <div className="flex items-center gap-2 text-[10px] text-muted/65">
              <Activity className="h-3.5 w-3.5" aria-hidden />
              事件
            </div>
            <div className="mt-1 text-sm font-semibold text-primary">{run.trace_report.workflow_events.length}</div>
          </div>
        </div>
      </div>

      <div className="space-y-5 px-4 py-4">
        <ExecutionMetricsPanel snapshot={run.execution_metrics_snapshot} qualityReport={run.quality_report} />

        {run.route_decision ? (
          <section>
            <div className="mb-2 text-[12px] font-medium text-primary">路由依据</div>
            <div className="space-y-1.5">
              {run.route_decision.reasons.map((reason) => (
                <div key={reason} className="rounded-lg border border-border/10 bg-background/70 px-3 py-2 text-[11px] text-muted">
                  {reason}
                </div>
              ))}
            </div>
          </section>
        ) : null}

        {warnings.length ? (
          <section>
            <div className="mb-2 flex items-center gap-2 text-[12px] font-medium text-primary">
              <ShieldAlert className="h-4 w-4 text-[rgb(var(--color-sa-gold))]" aria-hidden />
              需确认项
            </div>
            <div className="space-y-1.5">
              {[...new Set(warnings)].map((warning) => (
                <div key={warning} className="rounded-lg bg-[rgb(var(--color-sa-gold))]/10 px-3 py-2 text-[11px] text-[rgb(var(--color-sa-gold))]">
                  {warning}
                </div>
              ))}
            </div>
          </section>
        ) : null}

        <section>
          <div className="mb-2 text-[12px] font-medium text-primary">{SUPER_AGENT_TERMS.skillTraces}</div>
          <div className="space-y-2">
            {run.skill_traces.length ? run.skill_traces.map((trace, index) => (
              <SkillTraceRow key={`${trace.skill_id}-${index}`} trace={trace} />
            )) : (
              <div className="rounded-lg border border-border/10 bg-background/70 px-3 py-6 text-center text-[11px] text-muted/60">
                暂无执行轨迹
              </div>
            )}
          </div>
        </section>
      </div>
    </div>
  )
}

function RunRow({ run, selected, onSelect }: { run: SuperAgentRun; selected: boolean; onSelect: (run: SuperAgentRun) => void }) {
  const route = run.route_decision?.route || run.requested_route
  return (
    <button
      type="button"
      onClick={() => onSelect(run)}
      className={`w-full rounded-lg border px-3 py-3 text-left transition hover:border-primaryAccent/30 ${selected ? 'border-primaryAccent/40 bg-primaryAccent/8' : 'border-border/15 bg-surface'}`}
    >
      <div className="flex items-center gap-2">
        <span className={`h-2 w-2 shrink-0 rounded-full ${run.status === 'completed' ? 'bg-positive' : run.status === 'failed' ? 'bg-destructive' : run.status === 'limited' ? 'bg-[rgb(var(--color-sa-gold))]' : 'bg-primaryAccent'}`} />
        <span className="min-w-0 flex-1 truncate text-[12px] font-medium text-primary">{run.name || run.run_id}</span>
        <span className="shrink-0 text-[10px] text-muted/45">{relativeTime(run.updated_at)}</span>
      </div>
      <div className="mt-2 flex flex-wrap gap-1.5 text-[10px]">
        <span className={`rounded-full border px-2 py-0.5 ${statusTone(run.status)}`}>{STATUS_LABELS[run.status] || run.status}</span>
        <span className="rounded-full border border-border/15 bg-background px-2 py-0.5 text-muted">{ROUTE_LABELS[route] || route}</span>
      </div>
    </button>
  )
}

export default function SuperAgentConsolePage() {
  const [capabilities, setCapabilities] = useState<SuperAgentCapabilities | null>(null)
  const [runs, setRuns] = useState<SuperAgentRun[]>([])
  const [selectedId, setSelectedId] = useState('')
  const [loading, setLoading] = useState(true)
  const [submitting, setSubmitting] = useState(false)
  const [executing, setExecuting] = useState('')
  const [benchmarking, setBenchmarking] = useState(false)
  const [error, setError] = useState('')
  const [form, setForm] = useState<CreateSuperAgentRunInput>({
    name: `${SUPER_AGENT_TERMS.defaultRunName} ${new Date().toLocaleDateString('zh-CN')}`,
    objective: '审查现有文件组审查任务并汇总智能体执行轨迹。',
    processing_mode: 'OPTIMAL',
    input_mode: 'existing_review_plus',
    source_review_id: '',
    requested_route: 'auto',
    review_mode: 'full',
    execute: true,
  })

  const selectedRun = useMemo(
    () => runs.find((run) => run.run_id === selectedId) || runs[0] || null,
    [runs, selectedId],
  )

  const refresh = useCallback(async () => {
    try {
      setLoading(true)
      const [caps, nextRuns] = await Promise.all([
        getSuperAgentCapabilities(),
        listSuperAgentRuns(),
      ])
      setCapabilities(caps)
      setRuns(nextRuns)
      setError('')
      setSelectedId((current) => current || nextRuns[0]?.run_id || '')
    } catch (err) {
      setError(err instanceof Error ? err.message : '智能审查数据加载失败')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void refresh()
  }, [refresh])

  const handleCreate = useCallback(async () => {
    try {
      setSubmitting(true)
      const run = await createSuperAgentRun(form)
      setRuns((current) => [run, ...current.filter((item) => item.run_id !== run.run_id)])
      setSelectedId(run.run_id)
      setError('')
    } catch (err) {
      setError(err instanceof Error ? err.message : '创建执行任务失败')
    } finally {
      setSubmitting(false)
    }
  }, [form])

  const handleExecute = useCallback(async (runId: string) => {
    try {
      setExecuting(runId)
      const run = await executeSuperAgentRun(runId)
      setRuns((current) => [run, ...current.filter((item) => item.run_id !== run.run_id)])
      setSelectedId(run.run_id)
      setError('')
    } catch (err) {
      setError(err instanceof Error ? err.message : '执行任务失败')
    } finally {
      setExecuting('')
    }
  }, [])

  const handleBenchmark = useCallback(async () => {
    try {
      setBenchmarking(true)
      await runSuperAgentBenchmark()
      await refresh()
    } catch (err) {
      setError(err instanceof Error ? err.message : '基准测试执行失败')
    } finally {
      setBenchmarking(false)
    }
  }, [refresh])

  return (
    <div className="h-full overflow-y-auto">
      <div className="mx-auto max-w-7xl px-3 py-4 sm:px-6 sm:py-5">
        <div className="flex flex-col gap-3 border-b border-border/10 pb-4 lg:flex-row lg:items-center lg:justify-between">
          <div className="min-w-0">
            <div className="flex items-center gap-2">
              <Sparkles className="h-5 w-5 text-primaryAccent" aria-hidden />
              <h1 className="text-lg font-semibold text-primary">{SUPER_AGENT_TERMS.consoleTitle}</h1>
            </div>
            <div className="mt-2 flex flex-wrap gap-2">
              {(capabilities?.routes || ['review_plus', 'structure_only', 'hybrid']).map((route) => (
                <span key={route} className="rounded-full border border-border/15 bg-surface px-2 py-0.5 text-[10px] text-muted">
                  {ROUTE_LABELS[route] || route}
                </span>
              ))}
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Link
              href="/review-plus-v2"
              className="inline-flex min-h-9 items-center justify-center rounded-lg border border-border/20 bg-surface px-3 text-[11px] font-medium text-primary"
            >
              {REVIEW_PLUS_TERMS.nav}
            </Link>
            <button
              type="button"
              onClick={refresh}
              disabled={loading}
              className="inline-flex min-h-9 items-center justify-center gap-2 rounded-lg border border-border/20 bg-surface px-3 text-[11px] font-medium text-primary disabled:opacity-50"
            >
              <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} aria-hidden />
              刷新
            </button>
            <button
              type="button"
              onClick={handleBenchmark}
              disabled={benchmarking}
              className="inline-flex min-h-9 items-center justify-center gap-2 rounded-lg bg-brand px-3 text-[11px] font-medium text-white disabled:opacity-50"
            >
              {benchmarking ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : <CheckCircle2 className="h-4 w-4" aria-hidden />}
              {SUPER_AGENT_TERMS.benchmark}
            </button>
          </div>
        </div>

        {error ? (
          <div className="mt-4 rounded-lg border border-destructive/20 bg-destructive/10 px-4 py-3 text-[11px] text-destructive">
            {error}
          </div>
        ) : null}

        <div className="mt-5 grid gap-5 lg:grid-cols-[360px_minmax(0,1fr)]">
          <aside className="space-y-4">
            <section className="rounded-xl border border-border/15 bg-surface p-4 shadow-soft">
              <div className="mb-3 flex items-center gap-2 text-[12px] font-medium text-primary">
                <Bot className="h-4 w-4 text-primaryAccent" aria-hidden />
                {SUPER_AGENT_TERMS.createRun}
              </div>
              <div className="space-y-3">
                <label className="block">
                  <span className="text-[10px] font-medium text-muted">名称</span>
                  <input
                    value={form.name}
                    onChange={(event) => setForm((current) => ({ ...current, name: event.target.value }))}
                    className="mt-1 w-full rounded-lg border border-border/25 bg-background px-3 py-2 text-[12px] text-primary outline-none focus:border-primaryAccent/50"
                  />
                </label>
                <label className="block">
                  <span className="text-[10px] font-medium text-muted">{REVIEW_PLUS_TERMS.sourceIdLabel}</span>
                  <input
                    value={form.source_review_id}
                    onChange={(event) => setForm((current) => ({ ...current, source_review_id: event.target.value }))}
                    placeholder="rvp_..."
                    className="mt-1 w-full rounded-lg border border-border/25 bg-background px-3 py-2 text-[12px] text-primary outline-none focus:border-primaryAccent/50"
                  />
                </label>
                <div className="grid grid-cols-2 gap-2">
                  <label className="block">
                    <span className="text-[10px] font-medium text-muted">模式</span>
                    <select
                      value={form.processing_mode}
                      onChange={(event) => setForm((current) => ({ ...current, processing_mode: event.target.value }))}
                      className="mt-1 w-full rounded-lg border border-border/25 bg-background px-2 py-2 text-[12px] text-primary outline-none focus:border-primaryAccent/50"
                    >
                      <option value="OPTIMAL">{PROCESSING_MODE_LABELS.OPTIMAL}</option>
                      <option value="HIGH_ACCURACY">{PROCESSING_MODE_LABELS.HIGH_ACCURACY}</option>
                      <option value="HIGH_SPEED">{PROCESSING_MODE_LABELS.HIGH_SPEED}</option>
                    </select>
                  </label>
                  <label className="block">
                    <span className="text-[10px] font-medium text-muted">路由</span>
                    <select
                      value={form.requested_route}
                      onChange={(event) => setForm((current) => ({ ...current, requested_route: event.target.value as CreateSuperAgentRunInput['requested_route'] }))}
                      className="mt-1 w-full rounded-lg border border-border/25 bg-background px-2 py-2 text-[12px] text-primary outline-none focus:border-primaryAccent/50"
                    >
                      <option value="auto">{ROUTE_LABELS.auto}</option>
                      <option value="review_plus">{ROUTE_LABELS.review_plus}</option>
                      <option value="gnc_review_only">{ROUTE_LABELS.gnc_review_only}</option>
                      <option value="structure_only">{ROUTE_LABELS.structure_only}</option>
                      <option value="hybrid">{ROUTE_LABELS.hybrid}</option>
                    </select>
                  </label>
                </div>
                <label className="block">
                  <span className="text-[10px] font-medium text-muted">审查模式</span>
                  <select
                    value={form.review_mode}
                    onChange={(event) => setForm((current) => ({ ...current, review_mode: event.target.value as CreateSuperAgentRunInput['review_mode'] }))}
                    className="mt-1 w-full rounded-lg border border-border/25 bg-background px-2 py-2 text-[12px] text-primary outline-none focus:border-primaryAccent/50"
                  >
                    <option value="full">{REVIEW_MODE_LABELS.full}</option>
                    <option value="single_doc">{REVIEW_MODE_LABELS.single_doc}</option>
                    <option value="multi_doc">{REVIEW_MODE_LABELS.multi_doc}</option>
                  </select>
                </label>
                <label className="block">
                  <span className="text-[10px] font-medium text-muted">目标</span>
                  <textarea
                    value={form.objective}
                    onChange={(event) => setForm((current) => ({ ...current, objective: event.target.value }))}
                    rows={3}
                    className="mt-1 w-full resize-none rounded-lg border border-border/25 bg-background px-3 py-2 text-[12px] text-primary outline-none focus:border-primaryAccent/50"
                  />
                </label>
                <label className="flex items-center gap-2 text-[11px] text-muted">
                  <input
                    type="checkbox"
                    checked={form.execute}
                    onChange={(event) => setForm((current) => ({ ...current, execute: event.target.checked }))}
                    className="h-4 w-4 accent-[rgb(var(--color-brand))]"
                  />
                  立即执行
                </label>
                <button
                  type="button"
                  onClick={handleCreate}
                  disabled={submitting}
                  className="inline-flex min-h-9 w-full items-center justify-center gap-2 rounded-lg bg-brand px-3 text-[11px] font-medium text-white disabled:opacity-50"
                >
                  {submitting ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : <Play className="h-4 w-4" aria-hidden />}
                  创建
                </button>
              </div>
            </section>

            <section className="space-y-2">
              {loading ? (
                <div className="rounded-xl border border-border/15 bg-surface px-4 py-8 text-center text-[11px] text-muted">
                  加载中...
                </div>
              ) : runs.length ? runs.map((run) => (
                <RunRow
                  key={run.run_id}
                  run={run}
                  selected={selectedRun?.run_id === run.run_id}
                  onSelect={(item) => setSelectedId(item.run_id)}
                />
              )) : (
                <div className="rounded-xl border border-border/15 bg-surface px-4 py-8 text-center text-[11px] text-muted">
                  {SUPER_AGENT_TERMS.noRuns}
                </div>
              )}
            </section>
          </aside>

          <main>
            <RunDetail run={selectedRun} onExecute={handleExecute} executing={executing} />
          </main>
        </div>
      </div>
    </div>
  )
}
