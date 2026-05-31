'use client'

import { useGncResource } from '@/features/unified-review-workbench/hooks/useGncResource'
import { useOptionalGncWorkbenchLink } from '@/features/unified-review-workbench/components/GncWorkbenchLinkContext'
import { GncCommitteeSubflowLanes } from '@/features/unified-review-workbench/components/GncCommitteeSubflowLanes'
import { extractRuleLinkTargets } from '@/features/unified-review-workbench/utils/gncWorkbenchLinks'
import type { GncCommitteeSubflowInput } from '@/features/unified-review-workbench/utils/gncCommitteeSubFlows'

interface RuleResult {
  rule_id?: string
  judgment?: string
  execution_status?: string
  hard_fail?: boolean
  placeholder?: boolean
  not_checked?: boolean
  blocking?: boolean
  passed?: boolean
  evidence_ids?: string[]
  related_evidence_ids?: string[]
  rid_id?: string
  related_rid_ids?: string[]
}

interface UnitResult {
  unit_key?: string
  stage?: string
  stage_key?: string
  agent_id?: string
  rule_results?: RuleResult[]
  blocking_flags?: string[]
  not_checked_rule_ids?: string[]
  hard_fail_rule_ids?: string[]
  placeholder_rule_ids?: string[]
}

interface CommitteeProjection extends GncCommitteeSubflowInput {
  ad_group?: Record<string, unknown>
  ac_group?: Record<string, unknown>
  discipline_reviews?: Record<string, unknown>
  unit_results?: UnitResult[]
  findings?: Array<Record<string, unknown>>
  blocking_flags?: string[]
  not_checked_rule_ids?: string[]
  hard_fail_rule_ids?: string[]
  placeholder_rule_ids?: string[]
  conflicts?: Array<Record<string, unknown>>
}

function GroupPanel({
  title,
  group,
  highlighted,
}: {
  title: string
  group?: Record<string, unknown>
  highlighted?: boolean
}) {
  if (!group || !Object.keys(group).length) {
    return (
      <div className={`rounded-xl border p-3 text-[10px] text-muted ${
        highlighted ? 'border-primaryAccent/40 bg-primaryAccent/5' : 'border-border/15 bg-background'
      }`}>
        {title}：暂无数据
      </div>
    )
  }
  return (
    <div className={`rounded-xl border p-3 ${
      highlighted ? 'border-primaryAccent/40 bg-primaryAccent/5 ring-1 ring-primaryAccent/20' : 'border-border/15 bg-background'
    }`}>
      <div className="text-[10px] font-medium text-muted">{title}</div>
      <div className="mt-1 text-[12px] font-medium text-primary">{String(group.summary || group.status || '已执行')}</div>
      {group.error ? <p className="mt-1 text-[10px] text-destructive">{String(group.error)}</p> : null}
      {Array.isArray(group.findings) && group.findings.length ? (
        <p className="mt-1 text-[10px] text-muted">{group.findings.length} 条专项发现</p>
      ) : null}
    </div>
  )
}

function RuleBadge({ label, tone }: { label: string; tone: 'danger' | 'warning' | 'muted' }) {
  const styles = {
    danger: 'border-destructive/25 text-destructive',
    warning: 'border-amber-500/25 text-amber-700',
    muted: 'border-border/20 text-muted',
  }
  return <span className={`rounded border px-1.5 py-0.5 text-[10px] ${styles[tone]}`}>{label}</span>
}

export function GncCommitteeTab({ reviewId, enabled }: { reviewId: string; enabled: boolean }) {
  const link = useOptionalGncWorkbenchLink()
  const { data, loading, error } = useGncResource<CommitteeProjection>(reviewId, 'committee', enabled)

  if (loading) return <p className="text-[11px] text-muted">加载专家意见…</p>
  if (error) return <p className="text-[11px] text-destructive">{error}</p>

  const unitResults = data?.unit_results ?? []
  const adGroup = data?.ad_group || (data?.discipline_reviews as Record<string, unknown> | undefined)?.ad_group as Record<string, unknown> | undefined
  const acGroup = data?.ac_group || (data?.discipline_reviews as Record<string, unknown> | undefined)?.ac_group as Record<string, unknown> | undefined
  const selectedGroupKey = link?.selectedCommitteeGroupKey || ''
  const selectedStageKey = link?.selectedCommitteeStageKey || ''
  const selectedUnitKey = link?.selectedCommitteeUnitKey || ''

  const isUnitHighlighted = (unit: UnitResult) => {
    if (selectedUnitKey && (unit.unit_key === selectedUnitKey || unit.agent_id === selectedUnitKey)) {
      return true
    }
    if (selectedStageKey && (unit.stage === selectedStageKey || unit.stage_key === selectedStageKey)) {
      return true
    }
    return false
  }

  const groupHighlight = (groupKey: 'ad_group' | 'ac_group') => (
    selectedGroupKey === groupKey && !selectedStageKey && !selectedUnitKey
  )

  return (
    <div className="space-y-4 text-[11px]">
      <GncCommitteeSubflowLanes
        committee={data}
        stayOnCurrentTab
      />

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {[
          ['单元结果', unitResults.length],
          ['阻塞标记', (data?.blocking_flags ?? []).length],
          ['未检规则', (data?.not_checked_rule_ids ?? []).length],
          ['冲突项', (data?.conflicts ?? []).length],
        ].map(([label, value]) => (
          <div key={String(label)} className="rounded-xl border border-border/15 bg-surface px-3 py-2">
            <div className="text-[10px] text-muted">{label}</div>
            <div className="mt-1 text-base font-semibold text-primary">{value}</div>
          </div>
        ))}
      </div>

      <div className="grid gap-3 md:grid-cols-2">
        <GroupPanel title="AD 专项组" group={adGroup} highlighted={groupHighlight('ad_group')} />
        <GroupPanel title="AC 专项组" group={acGroup} highlighted={groupHighlight('ac_group')} />
      </div>

      {(selectedGroupKey || selectedStageKey || selectedUnitKey) ? (
        <p className="rounded-lg border border-primaryAccent/20 bg-primaryAccent/5 px-3 py-2 text-[10px] text-primaryAccent">
          已从流程 Tab 定位：
          {selectedGroupKey ? ` ${selectedGroupKey}` : ''}
          {selectedStageKey ? ` · 阶段 ${selectedStageKey}` : ''}
          {selectedUnitKey ? ` · 单元 ${selectedUnitKey}` : ''}
        </p>
      ) : null}

      {(data?.hard_fail_rule_ids ?? []).length ? (
        <section className="rounded-xl border border-destructive/20 bg-destructive/5 p-3">
          <div className="text-[10px] font-medium text-destructive">Hard Fail 规则</div>
          <div className="mt-2 flex flex-wrap gap-1">
            {(data?.hard_fail_rule_ids ?? []).map((ruleId) => (
              <RuleBadge key={ruleId} label={ruleId} tone="danger" />
            ))}
          </div>
        </section>
      ) : null}

      {(data?.placeholder_rule_ids ?? []).length ? (
        <section className="rounded-xl border border-amber-500/20 bg-amber-500/5 p-3">
          <div className="text-[10px] font-medium text-amber-700">Placeholder / 未执行规则</div>
          <div className="mt-2 flex flex-wrap gap-1">
            {(data?.placeholder_rule_ids ?? []).map((ruleId) => (
              <RuleBadge key={ruleId} label={ruleId} tone="warning" />
            ))}
          </div>
        </section>
      ) : null}

      <section className="space-y-2">
        <div className="text-[10px] font-medium text-muted">单元 / 规则判定</div>
        {!unitResults.length ? (
          <p className="text-[10px] text-muted">暂无单元级结果</p>
        ) : (
          unitResults.map((unit) => (
            <article
              key={`${unit.unit_key}-${unit.agent_id || 'default'}`}
              className={`rounded-xl border p-3 ${
                isUnitHighlighted(unit)
                  ? 'border-primaryAccent/40 bg-primaryAccent/5 ring-1 ring-primaryAccent/20'
                  : 'border-border/15 bg-background'
              }`}
            >
              <div className="flex flex-wrap items-center justify-between gap-2">
                <div>
                  <div className="font-medium text-primary">{unit.unit_key || '未命名单元'}</div>
                  <div className="mt-0.5 text-[10px] text-muted">
                    {unit.stage ? `阶段：${unit.stage}` : null}
                    {unit.agent_id ? ` · Agent：${unit.agent_id}` : null}
                  </div>
                </div>
                {(unit.blocking_flags || []).length ? (
                  <span className="rounded-full border border-destructive/25 px-2 py-0.5 text-[10px] text-destructive">
                    {(unit.blocking_flags || []).length} 阻塞
                  </span>
                ) : null}
              </div>
              <div className="mt-2 space-y-1.5">
                {(unit.rule_results || []).map((rule) => {
                  const linkTargets = extractRuleLinkTargets(rule as Record<string, unknown>)
                  return (
                  <div key={rule.rule_id} className="flex flex-wrap items-center gap-2 rounded border border-border/10 px-2 py-1 text-[10px]">
                    <span className="font-medium text-primary">{rule.rule_id}</span>
                    <span className="text-muted">{rule.judgment || (rule.passed ? 'satisfied' : 'not_satisfied')}</span>
                    {rule.hard_fail ? <RuleBadge label="hard_fail" tone="danger" /> : null}
                    {rule.placeholder || rule.not_checked ? <RuleBadge label="not_checked" tone="warning" /> : null}
                    {rule.blocking ? <RuleBadge label="blocking" tone="danger" /> : null}
                    {linkTargets.evidenceIds.length ? (
                      <button
                        type="button"
                        className="text-primaryAccent hover:underline"
                        onClick={() => {
                          link?.setSelectedEvidenceId(linkTargets.evidenceIds[0])
                          link?.openLinkedTab('evidences')
                        }}
                      >
                        证据 {linkTargets.evidenceIds.length}
                      </button>
                    ) : null}
                    {linkTargets.ridIds.length ? (
                      <button
                        type="button"
                        className="text-primaryAccent hover:underline"
                        onClick={() => {
                          link?.setSelectedRidId(linkTargets.ridIds[0])
                          link?.openLinkedTab('rid')
                        }}
                      >
                        RID {linkTargets.ridIds.length}
                      </button>
                    ) : null}
                  </div>
                  )
                })}
              </div>
            </article>
          ))
        )}
      </section>

      {(data?.findings ?? []).length ? (
        <section className="space-y-2">
          <div className="text-[10px] font-medium text-muted">关联发现（点击查看证据）</div>
          {(data?.findings ?? []).map((finding) => {
            const findingId = String(finding.finding_id || '')
            return (
              <button
                key={findingId}
                type="button"
                onClick={() => {
                  link?.setSelectedFindingId(findingId)
                  link?.openLinkedTab('evidences')
                }}
                className="block w-full rounded-lg border border-border/15 px-3 py-2 text-left hover:border-primaryAccent/30 hover:bg-primaryAccent/5"
              >
                <div className="font-medium text-primary">{String(finding.title || findingId)}</div>
                {finding.severity ? <div className="mt-0.5 text-[10px] text-muted">严重度：{String(finding.severity)}</div> : null}
              </button>
            )
          })}
        </section>
      ) : null}
    </div>
  )
}

export default GncCommitteeTab
