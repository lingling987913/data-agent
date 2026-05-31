'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { getUnifiedWorkbenchResource } from '@/features/unified-review-workbench/api'
import ConclusionOverviewPanel from '@/features/unified-review-workbench/components/ConclusionOverviewPanel'
import WorkbenchStatCard from '@/features/unified-review-workbench/components/WorkbenchStatCard'
import { LightMarkdownView } from '@/features/unified-review-workbench/components/LightMarkdownView'
import {
  bucketBadgeClass,
  bucketListItemClass,
  bucketToneClass,
  resolveBucketLabel,
  resolveConclusionBadge,
} from '@/features/unified-review-workbench/utils/bucketTone'
import { resolvePhaseLabel } from '@/features/unified-review-workbench/phaseResolver'
import {
  resolveWorkbenchPendingConfirm,
  resolveWorkbenchProblemCount,
} from '@/features/unified-review-workbench/utils/workbenchIssueStats'
import { buildConclusionOverviewFromDetail } from '@/features/unified-review-workbench/utils/conclusionOverviewModel'
import {
  BUCKET_MISSING_DETAIL_HINT,
  filterConclusionItemsByBucket,
  mergeFindingsConclusionItems,
  sortConclusionItemsByBucket,
} from '@/features/unified-review-workbench/utils/findingsBucketFilter'
import { normalizeSuperAgentTabKey } from '@/features/unified-review-workbench/utils/superAgentTabAlias'
import {
  resolveSuperAgentStatAction,
  statKeyForBucket,
  type WorkbenchNavigateOptions,
  type WorkbenchStatAction,
} from '@/features/unified-review-workbench/utils/workbenchStatAction'
import type { UnifiedReviewWorkbenchDetail, UnifiedWorkbenchTabKey } from '@/features/unified-review-workbench/types'
import {
  resolveCheckItemTitle,
  resolveDisplayName,
  resolveEvidenceStatusLabel,
  resolveJudgmentLabel,
  resolveLocalizedRationale,
  resolveLocalizedVerdict,
  resolveWorkbenchStatusText,
  sanitizeBusinessText,
} from '@/features/unified-review-workbench/utils/zhWorkbenchText'

interface Props {
  runId: string
  activeTab: UnifiedWorkbenchTabKey
  detail: UnifiedReviewWorkbenchDetail
  onOpenTab?: (tab: UnifiedWorkbenchTabKey, options?: WorkbenchNavigateOptions) => void
  urlBucket?: string | null
  landingHint?: string
}

function LandingHintBar({ hint, onDismiss }: { hint: string; onDismiss?: () => void }) {
  if (!hint.trim()) return null
  return (
    <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-primaryAccent/25 bg-primaryAccent/5 px-3 py-2 text-[11px] text-primary">
      <span>{hint}</span>
      {onDismiss ? (
        <button type="button" onClick={onDismiss} className="shrink-0 text-primaryAccent hover:underline">
          知道了
        </button>
      ) : null}
    </div>
  )
}

function useSuperAgentResource<T>(runId: string, resource: string, enabled: boolean) {
  const [data, setData] = useState<T | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const reload = useCallback(async () => {
    if (!enabled || !runId) return
    setLoading(true)
    setError('')
    try {
      setData(await getUnifiedWorkbenchResource<T>('super_agent', runId, resource))
    } catch (err) {
      setError(err instanceof Error ? err.message : '加载失败')
    } finally {
      setLoading(false)
    }
  }, [enabled, resource, runId])

  useEffect(() => {
    void reload()
  }, [reload])

  return { data, loading, error }
}

function ResourceState({ loading, error }: { loading: boolean; error: string }) {
  if (loading) return <p className="text-[11px] text-muted">加载中…</p>
  if (error) return <p className="text-[11px] text-destructive">{error}</p>
  return null
}

function asRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {}
}

function asList(value: unknown): Array<Record<string, unknown>> {
  return Array.isArray(value)
    ? value.filter((item): item is Record<string, unknown> => Boolean(item) && typeof item === 'object' && !Array.isArray(item))
    : []
}

function textValue(value: unknown): string {
  return typeof value === 'string' ? value.trim() : ''
}

function numberValue(value: unknown): number {
  const numeric = Number(value)
  return Number.isFinite(numeric) ? numeric : 0
}

function EmptyState({ label = '暂无数据', hint }: { label?: string; hint?: string }) {
  return (
    <div className="rounded-xl border border-border/15 bg-surface px-4 py-8 text-center text-[12px] text-muted">
      <p>{label}</p>
      {hint ? <p className="mt-2 text-[11px] text-muted/80">{hint}</p> : null}
    </div>
  )
}

function ListBlock({
  items,
  idKey,
  titleKey = 'title',
  conclusionMode = false,
}: {
  items: Array<Record<string, unknown>>
  idKey: string
  titleKey?: string
  conclusionMode?: boolean
}) {
  if (!items.length) return <EmptyState />
  return (
    <ul className="space-y-2">
        {items.map((item, index) => {
        const itemKey = String(
          item[idKey] || item.finding_id || item.check_item_id || item.evidence_id || item.id || index,
        )
        const { bucketKey, label: badgeLabel } = conclusionMode
          ? resolveConclusionBadge(item)
          : {
              bucketKey: '',
              label: resolveWorkbenchStatusText(item.status_label || item.conclusion_label || item.severity || item.status),
            }
        const bucket = String(item.business_bucket || bucketKey || '')
        const rawTitle = String(item[titleKey] || item.description || item[idKey] || '')
        const title = conclusionMode
          ? resolveCheckItemTitle(rawTitle, bucket)
          : rawTitle || '项'
        const agentDisplay = textValue(item.agent_display_name)
          || resolveDisplayName(item.agent_id, 'expert')
        const agentRaw = textValue(item.agent_id_raw)
        const judgmentLabel = resolveJudgmentLabel(item.judgment_label || item.judgment)
        const evidenceLabel = resolveEvidenceStatusLabel(item.evidence_status)
        const recommendation = sanitizeBusinessText(item.recommendation, '', { hideEnglish: true })
        const quote = textValue(item.quote || item.excerpt)
        const pageRef = textValue(item.page) || textValue(item.page_number)
        const sectionPath = textValue(item.section_path) || textValue(item.chapter_path)
        return (
          <li
            key={itemKey}
            className={`rounded-lg border px-3 py-2 text-[11px] ${
              conclusionMode && bucketKey
                ? bucketListItemClass(bucketKey)
                : 'border-border/15 bg-background'
            }`}
          >
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div className="min-w-0 flex-1 font-medium text-primary">
                {title}
              </div>
              {badgeLabel ? (
                <span className={`shrink-0 rounded-full border px-2 py-0.5 text-[10px] ${
                  conclusionMode && bucketKey ? bucketBadgeClass(bucketKey) : 'border-border/15 bg-surface text-muted'
                }`}>
                  {badgeLabel}
                </span>
              ) : null}
            </div>
            {agentDisplay ? (
              <div className="mt-1 text-muted">
                专家：{agentDisplay}
                {agentRaw ? <span className="ml-1 text-[10px] text-muted/80">（原始标识：{agentRaw}）</span> : null}
              </div>
            ) : null}
            {!conclusionMode && item.status ? (
              <div className="mt-1 text-muted">状态：{resolveWorkbenchStatusText(item.status)}</div>
            ) : null}
            {conclusionMode && judgmentLabel ? (
              <div className="mt-1 text-muted">判断：{judgmentLabel}</div>
            ) : null}
            {conclusionMode && evidenceLabel ? (
              <div className="mt-1 text-muted">证据：{evidenceLabel}</div>
            ) : null}
            {pageRef ? <div className="mt-1 text-muted">页码：{pageRef}</div> : null}
            {sectionPath ? <div className="mt-1 text-muted">章节路径：{sectionPath}</div> : null}
            {item.missing_reason || item.evidence_gap_reason ? (
              <p className="mt-1 text-sky-800">
                缺口：{String(item.missing_reason || item.evidence_gap_reason)}
              </p>
            ) : null}
            {recommendation ? <p className="mt-2 text-primary/80">建议：{recommendation}</p> : null}
            {quote ? (
              <p className="mt-2 text-muted">
                <span className="text-[10px] text-muted/80">原文摘录：</span>
                {quote}
              </p>
            ) : null}
          </li>
        )
      })}
    </ul>
  )
}

function OverviewSituationCards({
  detail,
  onStatAction,
}: {
  detail: UnifiedReviewWorkbenchDetail
  onStatAction?: (action: WorkbenchStatAction) => void
}) {
  const scope = asRecord(detail.conclusion_overview?.review_scope)
  const reviewRoute = textValue(scope.review_mode_label || detail.summary.review_mode_label)
  const pendingConfirm = resolveWorkbenchPendingConfirm(detail)
  const problemCount = resolveWorkbenchProblemCount(detail)
  const qualityHint = detail.workbench_phase === 'failed' ? '异常' : detail.error ? '需关注' : '正常'
  const materialValue = String(detail.metrics.material_count ?? scope.material_count ?? '—')
  const cards: Array<{ key: Parameters<typeof resolveSuperAgentStatAction>[0]; label: string; value: string }> = [
    { key: 'run_status', label: '运行状态', value: resolveWorkbenchStatusText(detail.status) },
    { key: 'workbench_phase', label: '当前阶段', value: resolvePhaseLabel(detail.workbench_phase) },
    { key: 'material_count', label: '材料数量', value: materialValue },
    { key: 'review_route_label', label: '审查路线', value: reviewRoute || '待识别' },
    { key: 'finding_count', label: '问题数量', value: String(problemCount) },
    { key: 'pending_confirm', label: '待确认事项', value: String(pendingConfirm) },
    { key: 'quality_status', label: '质量状态', value: qualityHint },
  ]
  return (
    <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-4">
      {cards.map((card) => (
        <WorkbenchStatCard
          key={card.label}
          label={card.label}
          value={card.value}
          action={resolveSuperAgentStatAction(card.key, detail)}
          onAction={onStatAction}
        />
      ))}
    </div>
  )
}

function FlowBlock({ data }: { data: unknown }) {
  const steps = asList(asRecord(data).steps)
  if (!steps.length) return <EmptyState label="暂无流程记录" hint="审查启动后将展示执行步骤。" />
  return (
    <div className="space-y-3">
      <div className="rounded-xl border border-border/15 bg-surface px-4 py-3">
        <div className="text-[10px] font-medium text-muted">执行流程</div>
        <div className="mt-1 text-[12px] text-primary">
          当前步骤：{textValue(asRecord(data).current_step) || '未开始'}
        </div>
      </div>
      <div className="grid gap-2">
        {steps.map((step, index) => {
          const status = textValue(step.status) || (step.completed ? 'completed' : 'pending')
          return (
            <div key={textValue(step.step_key) || index} className="rounded-xl border border-border/15 bg-background px-4 py-3">
              <div className="flex flex-wrap items-center gap-2">
                <span className="flex size-6 items-center justify-center rounded-full bg-primaryAccent/10 text-[10px] font-medium text-primaryAccent">
                  {index + 1}
                </span>
                <span className="font-medium text-primary">{textValue(step.label) || textValue(step.step_key) || '步骤'}</span>
                <span className="rounded-full border border-border/15 px-2 py-0.5 text-[10px] text-muted">{status}</span>
              </div>
              {asList(step.warnings).length ? (
                <p className="mt-2 text-[11px] text-warning">存在告警，详见运行质量 Tab。</p>
              ) : null}
            </div>
          )
        })}
      </div>
    </div>
  )
}

function CommitteeBlock({
  data,
  onStatAction,
}: {
  data: unknown
  onStatAction?: (action: WorkbenchStatAction) => void
}) {
  const payload = asRecord(data)
  const chiefPlan = asRecord(payload.chief_review_plan)
  const specialists = asList(payload.specialist_reviews)
  const taskBoard = asRecord(payload.smart_task_board)
  const selectedAgents = asList(chiefPlan.selected_agents)
  const members = specialists.length ? specialists : selectedAgents
  return (
    <div className="space-y-3">
      <div className="rounded-xl border border-border/15 bg-surface px-4 py-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="text-[10px] font-medium text-muted">总师调度</div>
            <div className="mt-1 text-[13px] font-medium text-primary">
              {textValue(chiefPlan.chief_agent_name) || '智能总师调度'}
            </div>
          </div>
          {textValue(taskBoard.status) ? (
            <span className="rounded-full border border-border/15 px-2 py-0.5 text-[10px] text-muted">{textValue(taskBoard.status)}</span>
          ) : null}
        </div>
        {textValue(chiefPlan.scenario) ? (
          <p className="mt-2 text-[11px] leading-relaxed text-muted">{textValue(chiefPlan.scenario)}</p>
        ) : null}
      </div>
      {members.length ? (
        <div className="grid gap-2 md:grid-cols-2">
          {members.map((member, index) => {
            const findings = asList(member.findings)
            const ruleResults = asList(member.rule_results)
            return (
              <div key={textValue(member.agent_id) || textValue(member.specialist_id) || index} className="rounded-xl border border-border/15 bg-background px-4 py-3">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <div className="font-medium text-primary">
                    {textValue(member.agent_name) || textValue(member.display_name) || textValue(member.agent_id) || '审查 Agent'}
                  </div>
                  <span className="rounded-full border border-border/15 px-2 py-0.5 text-[10px] text-muted">
                    {textValue(member.status) || (member.required ? '必选' : '参与')}
                  </span>
                </div>
                <p className="mt-2 text-[11px] leading-relaxed text-muted">
                  {textValue(member.summary) || textValue(member.reason) || textValue(member.assignment_reason) || textValue(member.role) || '等待输出审查意见。'}
                </p>
                {findings.length ? (
                  <button
                    type="button"
                    onClick={() => {
                      const action = resolveSuperAgentStatAction('finding_count')
                      if (action) onStatAction?.(action)
                    }}
                    className="mt-2 text-[10px] text-primaryAccent hover:underline"
                  >
                    {findings.length} 条发现 · 查看详情
                  </button>
                ) : null}
                {ruleResults.length ? (
                  <p className="mt-1 text-[10px] text-muted">{ruleResults.length} 条规则匹配（明细待后端投影）</p>
                ) : null}
              </div>
            )
          })}
        </div>
      ) : (
        <EmptyState label="暂无专家组输出" hint="路线执行后将展示 GNC 设计要素、文文一致性或智能通用化审查单元。" />
      )}
    </div>
  )
}

function RoutesBlock({
  data,
  onStatAction,
}: {
  data: unknown
  onStatAction?: (action: WorkbenchStatAction) => void
}) {
  const payload = asRecord(data)
  const reviewMode = textValue(payload.review_mode)
  const primaryPath = textValue(payload.primary_path)
  const routeDecision = asRecord(payload.route_decision)
  const flowSteps = asList(asRecord(payload.flow).steps)
  const committee = asRecord(payload.committee)
  const specialists = asList(committee.specialist_reviews)
  const selectedAgents = asList(asRecord(committee.chief_review_plan).selected_agents)
  const expertCount = specialists.length || selectedAgents.length
  const events = asList(payload.events)
  return (
    <div className="space-y-4 text-[12px]">
      <div className="grid gap-2 sm:grid-cols-3">
        <WorkbenchStatCard
          label="执行节点"
          value={flowSteps.length || '—'}
          action={resolveSuperAgentStatAction('routes_flow')}
          onAction={onStatAction}
        />
        <WorkbenchStatCard
          label="审查单元/专家"
          value={expertCount || '—'}
          action={resolveSuperAgentStatAction('routes_committee')}
          onAction={onStatAction}
        />
        <WorkbenchStatCard
          label="阶段事件"
          value={events.length || '—'}
          action={resolveSuperAgentStatAction('routes_events')}
          onAction={onStatAction}
        />
      </div>
      <section className="rounded-xl border border-border/15 bg-surface px-4 py-3">
        <div className="text-[10px] font-medium text-muted">审查路线概览</div>
        <p className="mt-1 text-[12px] text-primary">
          {reviewMode === 'gnc' ? 'GNC 设计要素审查' : primaryPath === 'gnc' ? 'GNC 设计要素审查' : '智能通用化审查'}
        </p>
        {routeDecision.route ? (
          <p className="mt-1 text-[11px] text-muted">路由决策：{textValue(routeDecision.route)}</p>
        ) : null}
        <p className="mt-2 text-[11px] text-muted/80">
          本页合并流程、专家委员会与关键事件，按执行节点、审查单元与工具调用展示。
        </p>
      </section>
      <section id="routes-flow">
        <h3 className="mb-2 text-[11px] font-medium text-muted">执行节点</h3>
        <FlowBlock data={payload.flow} />
      </section>
      <section id="routes-committee">
        <h3 className="mb-2 text-[11px] font-medium text-muted">审查单元与规则匹配</h3>
        <CommitteeBlock data={payload.committee} onStatAction={onStatAction} />
      </section>
      <section id="routes-events">
        <h3 className="mb-2 text-[11px] font-medium text-muted">阶段性输出与 Trace</h3>
        <ListBlock items={events} idKey="sequence" titleKey="type" />
      </section>
    </div>
  )
}

function DecisionBlock({
  data,
  detail,
  onStatAction,
}: {
  data: unknown
  detail: UnifiedReviewWorkbenchDetail
  onStatAction?: (action: WorkbenchStatAction) => void
}) {
  const payload = asRecord(data)
  const arbiter = asRecord(payload.arbiter_summary)
  const suggestions = asList(payload.replan_suggestions)
  const issueSummary = asRecord(payload.issue_summary)
  const buckets = asRecord(payload.issue_buckets) || asRecord(issueSummary.buckets)
  const bucketLabels = asRecord(payload.bucket_labels) || asRecord(issueSummary.bucket_labels)
  const conclusionItems = asList(payload.conclusion_items)
  const keyRisks = Array.isArray(payload.key_risks) ? payload.key_risks : []
  const degradation = Array.isArray(payload.trace_degradation_summary) ? payload.trace_degradation_summary : []
  const materialInsufficiency = Boolean(payload.material_insufficiency || detail.conclusion_overview?.material_insufficiency)
  const verdictLabel = resolveLocalizedVerdict({
    verdict: payload.verdict || detail.summary.verdict,
    verdictLabelZh: payload.verdict_label_zh || detail.summary.verdict_label_zh,
    headline: payload.headline_verdict || detail.summary.headline_verdict,
    oneLine: payload.one_line_conclusion || detail.summary.one_line_conclusion,
  })
  const rationaleDisplay = resolveLocalizedRationale({
    rationale: payload.rationale || detail.summary.rationale,
    rationaleZh: payload.rationale_zh || detail.summary.rationale_zh,
    verdict: payload.verdict || detail.summary.verdict,
    buckets: Object.fromEntries(Object.entries(buckets).map(([key, value]) => [key, numberValue(value)])),
    materialInsufficiency,
  })
  const arbiterText = sanitizeBusinessText(arbiter.summary || arbiter.rationale, '', { hideEnglish: true })
  return (
    <div className="space-y-3">
      <div className="rounded-xl border border-border/15 bg-surface px-4 py-3">
        <div className="text-[10px] font-medium text-muted">审查结论</div>
        <div className="mt-1 text-[15px] font-semibold text-primary">
          {verdictLabel || '待形成结论'}
        </div>
        {rationaleDisplay ? (
          <p className="mt-2 text-[11px] leading-relaxed text-muted">
            {rationaleDisplay}
          </p>
        ) : null}
      </div>
      {Object.keys(buckets).length ? (
        <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-5">
          {Object.entries(buckets).map(([key, value]) => {
            const label = String(bucketLabels[key] || resolveBucketLabel(key) || '其他')
            const action = resolveSuperAgentStatAction(statKeyForBucket(key))
            return (
              <WorkbenchStatCard
                key={key}
                label={label}
                value={numberValue(value)}
                action={action}
                onAction={onStatAction}
                className={bucketToneClass(key)}
              />
            )
          })}
        </div>
      ) : null}
      {conclusionItems.length ? (
        <div className="rounded-xl border border-border/15 bg-background px-4 py-3">
          <div className="text-[10px] font-medium text-muted">直接结论清单</div>
          <div className="mt-2">
            <ListBlock items={conclusionItems.slice(0, 8)} idKey="check_item_id" conclusionMode />
          </div>
        </div>
      ) : null}
      {keyRisks.length ? (
        <div className="rounded-xl border border-border/15 bg-background px-4 py-3">
          <div className="text-[10px] font-medium text-muted">关键风险</div>
          <ul className="mt-2 space-y-1 text-[11px] text-primary/80">
            {keyRisks.slice(0, 6).map((item, index) => {
              const text = sanitizeBusinessText(item, '存在待关注风险项', { hideEnglish: true })
              return <li key={index}>{index + 1}. {text}</li>
            })}
          </ul>
        </div>
      ) : null}
      {arbiterText ? (
        <div className="rounded-xl border border-border/15 bg-background px-4 py-3">
          <div className="text-[10px] font-medium text-muted">总师综合评判</div>
          <p className="mt-1 text-[11px] leading-relaxed text-primary/80">
            {arbiterText}
          </p>
        </div>
      ) : null}
      {suggestions.length ? (
        <div className="rounded-xl border border-border/15 bg-background px-4 py-3">
          <div className="text-[10px] font-medium text-muted">后续建议</div>
          <ul className="mt-2 space-y-1 text-[11px] text-primary/80">
            {suggestions.map((item, index) => (
              <li key={index}>{index + 1}. {textValue(item.title) || textValue(item.description) || JSON.stringify(item)}</li>
            ))}
          </ul>
        </div>
      ) : null}
      {degradation.length ? (
        <div className="rounded-xl border border-border/15 bg-background px-4 py-3">
          <div className="text-[10px] font-medium text-muted">链路说明</div>
          <ul className="mt-2 space-y-1 text-[11px] text-muted">
            {degradation.map((item, index) => <li key={index}>{String(item)}</li>)}
          </ul>
        </div>
      ) : null}
    </div>
  )
}

function ClosureBlock({
  data,
  detail,
  onStatAction,
}: {
  data: unknown
  detail: UnifiedReviewWorkbenchDetail
  onStatAction?: (action: WorkbenchStatAction) => void
}) {
  const payload = asRecord(data)
  const closureStatus = asRecord(payload.closure_status)
  const expertItems = asList(payload.expert_confirmation_items)
  const issueRecs = asList(payload.issue_recommendations)
  const report = asRecord(payload.report)
  const markdown = textValue(report.markdown)
  return (
    <div className="space-y-4 text-[12px]">
      <p className="text-[11px] text-muted">
        本页展示完整裁定与报告草稿；下方区分事实整理、问题建议与需专家确认项。
      </p>
      <DecisionBlock data={payload} detail={detail} onStatAction={onStatAction} />
      {markdown ? (
        <section className="rounded-xl border border-border/15 bg-background p-4">
          <h3 className="mb-2 text-[11px] font-medium text-muted">审查意见单 / 报告草稿</h3>
          <article className="prose prose-sm max-w-none text-[12px]">
            <LightMarkdownView markdown={markdown} />
          </article>
        </section>
      ) : (
        <EmptyState label="暂无报告草稿" hint="审查完成后将生成 Markdown 报告。" />
      )}
      <section className="rounded-xl border border-border/15 bg-surface px-4 py-3">
        <h3 className="text-[11px] font-medium text-muted">闭环状态</h3>
        <dl className="mt-2 grid gap-2 text-[11px] sm:grid-cols-2">
          <div><dt className="text-muted">裁定</dt><dd className="text-primary">{textValue(closureStatus.verdict_label_zh) || textValue(closureStatus.verdict) || '—'}</dd></div>
          <div><dt className="text-muted">报告</dt><dd className="text-primary">{closureStatus.report_available ? '已生成' : '未生成'}</dd></div>
          <div><dt className="text-muted">复查要求</dt><dd className="text-primary">{closureStatus.re_review_required ? '需要' : '暂无'}</dd></div>
          <div><dt className="text-muted">编辑草稿</dt><dd className="text-primary">{textValue(closureStatus.editorial_draft) || '—'}</dd></div>
        </dl>
      </section>
      {issueRecs.length ? (
        <section>
          <h3 className="mb-2 text-[11px] font-medium text-muted">问题建议（整改方向）</h3>
          <ListBlock items={issueRecs.slice(0, 12)} idKey="check_item_id" conclusionMode />
        </section>
      ) : null}
      {expertItems.length ? (
        <section>
          <h3 className="mb-2 text-[11px] font-medium text-muted">需专家确认</h3>
          <ListBlock items={expertItems} idKey="check_item_id" conclusionMode />
        </section>
      ) : null}
    </div>
  )
}

function QualityBlock({
  data,
  onStatAction,
}: {
  data: unknown
  onStatAction?: (action: WorkbenchStatAction) => void
}) {
  const payload = asRecord(data)
  const qualityReport = asRecord(payload.quality_report)
  const parseQuality = asRecord(payload.parse_quality)
  const outputIntegrity = asRecord(payload.output_integrity)
  const degradation = Array.isArray(payload.trace_degradation_summary) ? payload.trace_degradation_summary : []
  const disclaimer = textValue(payload.technical_review_disclaimer) || '技术复盘，不替代专家审查判断'
  const parseSummary = textValue(parseQuality.summary) || (Object.keys(parseQuality).length ? '已记录解析指标' : '暂无')
  const traceCount = asList(payload.execution_events).length
  return (
    <div className="space-y-4 text-[12px]">
      <p className="rounded-lg border border-amber-200/60 bg-amber-50/80 px-3 py-2 text-[11px] text-amber-900">
        {disclaimer}
      </p>
      <section className="grid gap-2 sm:grid-cols-2">
        <div id="quality-parse">
          <WorkbenchStatCard
            label="解析质量"
            value={parseSummary}
            action={resolveSuperAgentStatAction('quality_parse')}
            onAction={onStatAction}
          />
        </div>
        <div id="quality-execution">
          <WorkbenchStatCard
            label="执行质量"
            value={numberValue(qualityReport.overall_score) || '—'}
            detailHint="综合得分"
            action={resolveSuperAgentStatAction('quality_execution')}
            onAction={onStatAction}
          />
        </div>
        <div id="quality-evidence">
          <WorkbenchStatCard
            label="证据质量"
            value={numberValue(outputIntegrity.evidence_count)}
            detailHint="证据条数"
            action={resolveSuperAgentStatAction('quality_evidence')}
            onAction={onStatAction}
          />
        </div>
        <div id="quality-output">
          <WorkbenchStatCard
            label="输出完整性"
            value={`发现 ${numberValue(outputIntegrity.finding_count)} 条`}
            detailHint={`报告 ${outputIntegrity.report_available ? '已生成' : '未生成'}`}
            action={resolveSuperAgentStatAction('quality_output')}
            onAction={onStatAction}
          />
        </div>
        <WorkbenchStatCard
          label="Trace / 异常"
          value={traceCount || degradation.length || '—'}
          action={resolveSuperAgentStatAction('quality_trace')}
          onAction={onStatAction}
        />
        {degradation.length ? (
          <WorkbenchStatCard
            label="降级路径"
            value={degradation.length}
            action={resolveSuperAgentStatAction('quality_degradation')}
            onAction={onStatAction}
          />
        ) : null}
      </section>
      {degradation.length ? (
        <section id="quality-degradation" className="rounded-xl border border-border/15 bg-background px-4 py-3">
          <h3 className="text-[11px] font-medium text-muted">降级路径</h3>
          <ul className="mt-2 space-y-1 text-[11px] text-muted">
            {degradation.map((item, index) => <li key={index}>{String(item)}</li>)}
          </ul>
        </section>
      ) : null}
      <section id="quality-trace">
        <h3 className="mb-2 text-[11px] font-medium text-muted">运行 Trace / 异常记录</h3>
        <ListBlock items={asList(payload.execution_events)} idKey="sequence" titleKey="type" />
      </section>
    </div>
  )
}

function MaterialsBlock({
  items,
  detail,
}: {
  items: Array<Record<string, unknown>>
  detail: UnifiedReviewWorkbenchDetail
}) {
  const scope = asRecord(detail.conclusion_overview?.review_scope)
  const count = items.length || numberValue(detail.metrics.material_count ?? scope.material_count)
  if (!items.length) {
    return (
      <div className="space-y-3">
        <WorkbenchStatCard
          label="材料数量"
          value={count || '—'}
          action={null}
          detailHint="暂无材料清单，请确认解析已完成。"
        />
        <EmptyState
          label="暂无材料清单"
          hint="请确认 Super Agent 已完成解析与结构化；材料角色、章节与证据摘要将在此展示。"
        />
      </div>
    )
  }
  return (
    <div className="space-y-3 text-[12px]">
      <WorkbenchStatCard label="材料数量" value={count} action={null} detailHint="以下为材料明细列表。" />
      <p className="text-[11px] text-muted">
        原始材料、解析状态与结构化摘要（章节、表格、公式图片、证据集合等以运行数据为准）。
      </p>
      <ListBlock items={items} idKey="name" titleKey="name" />
    </div>
  )
}

function FindingsBlock({
  detail,
  findings,
  evidences,
  checkItems,
  urlBucket,
  onBucketChange,
  landingHint,
  onStatAction,
}: {
  detail: UnifiedReviewWorkbenchDetail
  findings: Array<Record<string, unknown>>
  evidences: Array<Record<string, unknown>>
  checkItems: Array<Record<string, unknown>>
  urlBucket?: string | null
  onBucketChange?: (bucket: string | null) => void
  landingHint?: string
  onStatAction?: (action: WorkbenchStatAction) => void
}) {
  const [selectedBucket, setSelectedBucket] = useState<string | null>(urlBucket ?? null)

  useEffect(() => {
    setSelectedBucket(urlBucket ?? null)
  }, [urlBucket])

  const setBucket = useCallback((bucket: string | null) => {
    setSelectedBucket(bucket)
    onBucketChange?.(bucket)
  }, [onBucketChange])
  const overviewModel = useMemo(
    () => buildConclusionOverviewFromDetail(detail, 'super_agent'),
    [detail],
  )

  const mergedItems = useMemo(
    () => sortConclusionItemsByBucket(mergeFindingsConclusionItems(findings, checkItems, evidences)),
    [findings, checkItems, evidences],
  )

  const filteredItems = useMemo(
    () => filterConclusionItemsByBucket(mergedItems, selectedBucket),
    [mergedItems, selectedBucket],
  )

  const activeBucketMeta = selectedBucket
    ? overviewModel.bucketCards.find((card) => card.key === selectedBucket)
    : null
  const statCount = activeBucketMeta?.count ?? 0
  const showMissingDetailHint = Boolean(selectedBucket && statCount > 0 && filteredItems.length === 0)
  const problemCount = resolveWorkbenchProblemCount(detail)
  const pendingConfirm = resolveWorkbenchPendingConfirm(detail)

  const hasAny = mergedItems.length || overviewModel.bucketCards.length
  if (!hasAny) {
    return (
      <EmptyState
        label="暂无发现与证据"
        hint="审查执行后将合并展示问题清单、检查项与证据摘录。"
      />
    )
  }

  const listTitle = selectedBucket && activeBucketMeta
    ? `直接结论清单 · ${activeBucketMeta.label}`
    : '直接结论清单'

  return (
    <div className="space-y-4 text-[12px]">
      <LandingHintBar hint={landingHint || ''} />
      <div className="grid gap-2 sm:grid-cols-3">
        <WorkbenchStatCard
          label="问题条数"
          value={problemCount}
          action={resolveSuperAgentStatAction('finding_count')}
          onAction={onStatAction}
        />
        <WorkbenchStatCard
          label="证据条数"
          value={detail.metrics.evidence_count}
          action={resolveSuperAgentStatAction('coverage_evidence')}
          onAction={onStatAction}
        />
        <WorkbenchStatCard
          label="待确认"
          value={pendingConfirm}
          action={resolveSuperAgentStatAction('pending_confirm', detail)}
          onAction={onStatAction}
        />
      </div>
      {overviewModel.bucketCards.length ? (
        <ConclusionOverviewPanel
          model={overviewModel}
          bucketsOnly
          activeBucket={selectedBucket}
          onBucketClick={setBucket}
          showFilterBar
          filterCount={selectedBucket ? statCount : undefined}
        />
      ) : null}

      <section className="rounded-xl border border-border/15 bg-background px-4 py-3">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-[11px] font-medium text-muted">{listTitle}</h3>
          {!overviewModel.bucketCards.length && selectedBucket ? (
            <button
              type="button"
              onClick={() => setBucket(null)}
              className="text-[10px] text-primaryAccent hover:underline"
            >
              查看全部 / 清除筛选
            </button>
          ) : null}
        </div>
        <div className="mt-2">
          {showMissingDetailHint ? (
            <EmptyState
              label={`${activeBucketMeta?.label || '该分桶'}暂无明细条目`}
              hint={BUCKET_MISSING_DETAIL_HINT}
            />
          ) : filteredItems.length ? (
            <ListBlock
              items={filteredItems}
              idKey="check_item_id"
              conclusionMode
            />
          ) : selectedBucket ? (
            <EmptyState label="该分桶暂无匹配条目" hint="可点击「全部」或清除筛选查看其他分桶。" />
          ) : (
            <EmptyState label="暂无结论条目" hint="审查执行后将在此按风险优先级展示全部结论。" />
          )}
        </div>
      </section>
    </div>
  )
}

const TAB_RESOURCE_MAP: Partial<Record<UnifiedWorkbenchTabKey, string>> = {
  materials: 'materials',
  routes: 'routes',
  closure: 'closure',
  quality: 'quality',
}

export default function UnifiedSuperAgentEmbed({
  runId,
  activeTab,
  detail,
  onOpenTab,
  urlBucket = null,
  landingHint = '',
}: Props) {
  const canonicalTab = normalizeSuperAgentTabKey(activeTab) || activeTab
  const pendingAnchorRef = useRef<string | null>(null)
  const [dismissedHint, setDismissedHint] = useState('')

  const scrollToAnchor = useCallback((anchor: string) => {
    window.setTimeout(() => {
      document.getElementById(anchor)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }, 80)
  }, [])

  const syncFindingsBucket = useCallback((bucket: string | null) => {
    if (!onOpenTab) return
    onOpenTab('findings', {
      bucket,
      hint: bucket
        ? resolveSuperAgentStatAction(statKeyForBucket(bucket))?.hint
        : undefined,
    })
  }, [onOpenTab])

  const applyStatAction = useCallback((action: WorkbenchStatAction) => {
    if (!onOpenTab || action.disabled) return
    const tab = normalizeSuperAgentTabKey(action.tab) || action.tab
    if (tab === canonicalTab) {
      if (tab === 'findings') {
        syncFindingsBucket(action.bucket ?? null)
        return
      }
      if (action.anchor) {
        scrollToAnchor(action.anchor)
        return
      }
      return
    }
    pendingAnchorRef.current = action.anchor || null
    onOpenTab(tab, {
      bucket: action.bucket,
      hint: action.hint,
      anchor: action.anchor,
    })
  }, [canonicalTab, onOpenTab, scrollToAnchor, syncFindingsBucket])

  const resource = TAB_RESOURCE_MAP[canonicalTab]
  const { data, loading, error } = useSuperAgentResource<unknown>(
    runId,
    resource || '',
    Boolean(resource) && canonicalTab !== 'findings',
  )

  const findingsRes = useSuperAgentResource<unknown[]>(
    runId,
    'findings',
    canonicalTab === 'findings',
  )
  const evidencesRes = useSuperAgentResource<unknown[]>(
    runId,
    'evidences',
    canonicalTab === 'findings',
  )
  const checkItemsRes = useSuperAgentResource<unknown[]>(
    runId,
    'check_items',
    canonicalTab === 'findings',
  )

  useEffect(() => {
    const anchor = pendingAnchorRef.current
    if (!anchor) return
    pendingAnchorRef.current = null
    const timer = window.setTimeout(() => {
      document.getElementById(anchor)?.scrollIntoView({ behavior: 'smooth', block: 'start' })
    }, 180)
    return () => window.clearTimeout(timer)
  }, [canonicalTab, loading, findingsRes.loading])

  const activeLandingHint = landingHint && landingHint !== dismissedHint ? landingHint : ''

  const handleOpenTab = useMemo(() => {
    if (!onOpenTab) return undefined
    return (tab: UnifiedWorkbenchTabKey) => {
      const mapped = normalizeSuperAgentTabKey(tab) || tab
      onOpenTab(mapped, { bucket: mapped === 'findings' ? urlBucket : null })
    }
  }, [onOpenTab, urlBucket])

  if (canonicalTab === 'overview') {
    const overviewModel = buildConclusionOverviewFromDetail(detail, 'super_agent')
    return (
      <div className="space-y-4 text-[12px]">
        <LandingHintBar
          hint={activeLandingHint}
          onDismiss={() => setDismissedHint(landingHint)}
        />
        <OverviewSituationCards detail={detail} onStatAction={applyStatAction} />
        <ConclusionOverviewPanel
          model={overviewModel}
          onOpenTab={handleOpenTab}
          onStatAction={applyStatAction}
          compact
        />
      </div>
    )
  }

  if (canonicalTab === 'findings') {
    const loadingAny = findingsRes.loading || evidencesRes.loading || checkItemsRes.loading
    const errorAny = findingsRes.error || evidencesRes.error || checkItemsRes.error
    const state = <ResourceState loading={loadingAny} error={errorAny} />
    if (state.props.loading || state.props.error) return state
    return (
      <FindingsBlock
        detail={detail}
        findings={Array.isArray(findingsRes.data) ? findingsRes.data as Array<Record<string, unknown>> : []}
        evidences={Array.isArray(evidencesRes.data) ? evidencesRes.data as Array<Record<string, unknown>> : []}
        checkItems={Array.isArray(checkItemsRes.data) ? checkItemsRes.data as Array<Record<string, unknown>> : []}
        urlBucket={urlBucket}
        onBucketChange={syncFindingsBucket}
        landingHint={activeLandingHint}
        onStatAction={applyStatAction}
      />
    )
  }

  const state = <ResourceState loading={loading} error={error} />
  if (state.props.loading || state.props.error) return state

  const tabHintBar = (
    <LandingHintBar
      hint={activeLandingHint}
      onDismiss={() => setDismissedHint(landingHint)}
    />
  )

  if (canonicalTab === 'materials') {
    return (
      <div className="space-y-3">
        {tabHintBar}
        <MaterialsBlock
          items={Array.isArray(data) ? data as Array<Record<string, unknown>> : []}
          detail={detail}
        />
      </div>
    )
  }
  if (canonicalTab === 'routes') {
    return (
      <div className="space-y-3">
        {tabHintBar}
        <RoutesBlock data={data} onStatAction={applyStatAction} />
      </div>
    )
  }
  if (canonicalTab === 'closure') {
    return (
      <div className="space-y-3">
        {tabHintBar}
        <ClosureBlock data={data} detail={detail} onStatAction={applyStatAction} />
      </div>
    )
  }
  if (canonicalTab === 'quality') {
    return (
      <div className="space-y-3">
        {tabHintBar}
        <QualityBlock data={data} onStatAction={applyStatAction} />
      </div>
    )
  }

  return (
    <EmptyState
      label="暂无内容"
      hint={`「${canonicalTab}」在当前运行阶段不可展示。`}
    />
  )
}
