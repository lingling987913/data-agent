'use client'

import { StatusBadge } from '@aqua/ui-core'
import { GncReadonlyActionBar } from '@/features/unified-review-workbench/components/GncReadonlyActionBar'
import { useGncResource } from '@/features/unified-review-workbench/hooks/useGncResource'
import {
  groupGatekeepingIssues,
  resolveGncGateStatusLabel,
  resolveGncGateStatusTone,
  resolveGncMaterialRoleLabel,
  resolveGncParseStatusLabel,
  resolveGncParseStatusTone,
  resolveGncRoleConfirmLabel,
  resolveGncRoleConfirmTone,
} from '@/features/unified-review-workbench/utils/gncGatekeepingView'

interface GncMaterialItem {
  material_id?: string
  name?: string
  role?: string
  parse_status?: string
  role_confirmed?: boolean
  blocking?: boolean
  warnings?: string[]
  document_type?: string
}

interface GncGatekeepingProjection {
  gate_status?: string
  can_start_review?: boolean
  gate_summary?: string
  blocking_reasons?: string[]
  warnings?: string[]
  missing_materials?: string[]
  material_count?: number
  review_scope?: string
  review_phase?: string
}

function IssueBadge({ label, tone }: { label: string; tone: 'destructive' | 'warning' | 'neutral' }) {
  const styles = {
    destructive: 'border-destructive/25 bg-destructive/5 text-destructive',
    warning: 'border-amber-500/25 bg-amber-500/5 text-amber-700',
    neutral: 'border-border/20 bg-surface text-primary',
  }
  return (
    <span className={`inline-flex max-w-full rounded-full border px-2 py-0.5 text-[10px] leading-snug ${styles[tone]}`}>
      {label}
    </span>
  )
}

export function GncMaterialsTab({ reviewId, enabled }: { reviewId: string; enabled: boolean }) {
  const materialsQuery = useGncResource<GncMaterialItem[]>(reviewId, 'materials', enabled)
  const gatekeepingQuery = useGncResource<GncGatekeepingProjection>(reviewId, 'gatekeeping', enabled)

  if (materialsQuery.loading || gatekeepingQuery.loading) {
    return <p className="text-[11px] text-muted">加载送审材料…</p>
  }
  if (materialsQuery.error || gatekeepingQuery.error) {
    return (
      <p className="text-[11px] text-destructive">
        {materialsQuery.error || gatekeepingQuery.error}
      </p>
    )
  }

  const materials = Array.isArray(materialsQuery.data) ? materialsQuery.data : []
  const gate = gatekeepingQuery.data || {}
  const issueGroups = groupGatekeepingIssues(gate)

  return (
    <div className="space-y-4 text-[11px]">
      <GncReadonlyActionBar
        actions={[
          {
            id: 'upload',
            label: '上传材料',
            hint: '送审包在 Super Agent / GNC 任务创建阶段维护，工作台 BFF 暂无上传 API',
            available: false,
          },
          {
            id: 'role',
            label: '确认材料角色',
            hint: '角色确认需在源任务编排中完成，此处仅展示投影状态',
            available: false,
          },
          {
            id: 'gate',
            label: '重跑门禁',
            hint: 'quality_screening 由流水线自动执行，暂无单独重跑端点',
            available: false,
          },
        ]}
      />

      <section className="rounded-xl border border-border/15 bg-background px-4 py-3">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <div className="text-[10px] font-medium text-muted">送审包准入</div>
            <div className="mt-1 text-[13px] font-semibold text-primary">{gate.gate_summary || '待检查'}</div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <StatusBadge tone={resolveGncGateStatusTone(gate.gate_status)}>
              {resolveGncGateStatusLabel(gate.gate_status)}
            </StatusBadge>
            <StatusBadge tone={gate.can_start_review ? 'positive' : 'destructive'}>
              {gate.can_start_review ? '可启动审查' : '暂不可启动'}
            </StatusBadge>
          </div>
        </div>
        <div className="mt-2 flex flex-wrap gap-3 text-[10px] text-muted">
          {gate.review_phase ? <span>阶段：{gate.review_phase}</span> : null}
          {gate.review_scope ? <span>范围：{gate.review_scope}</span> : null}
          {gate.material_count != null ? <span>材料数：{gate.material_count}</span> : null}
        </div>
      </section>

      {issueGroups.length ? (
        <div className="grid gap-3 md:grid-cols-3">
          {issueGroups.map((group) => (
            <section
              key={group.key}
              className="rounded-xl border border-border/15 bg-surface p-3"
            >
              <div className="flex items-center gap-2">
                <span className="text-[10px] font-medium text-primary">{group.title}</span>
                <StatusBadge tone={group.tone}>{group.items.length}</StatusBadge>
              </div>
              <div className="mt-2 flex flex-wrap gap-1.5">
                {group.items.map((item) => (
                  <IssueBadge
                    key={`${group.key}-${item}`}
                    label={item}
                    tone={group.key === 'blocking' ? 'destructive' : group.key === 'warnings' ? 'warning' : 'neutral'}
                  />
                ))}
              </div>
            </section>
          ))}
        </div>
      ) : null}

      <section className="space-y-2">
        <div className="text-[10px] font-medium text-muted">送审材料清单</div>
        {!materials.length ? (
          <p className="text-[10px] text-muted">暂无材料</p>
        ) : (
          materials.map((item, index) => (
            <article key={String(item.material_id || item.name || index)} className="rounded-xl border border-border/15 bg-background p-3">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="font-medium text-primary">{item.name || '未命名材料'}</div>
                  <div className="mt-2 flex flex-wrap items-center gap-1.5">
                    <StatusBadge tone="neutral">
                      {resolveGncMaterialRoleLabel(item.role || item.document_type)}
                    </StatusBadge>
                    <StatusBadge tone={resolveGncParseStatusTone(item.parse_status)}>
                      {resolveGncParseStatusLabel(item.parse_status)}
                    </StatusBadge>
                    <StatusBadge tone={resolveGncRoleConfirmTone(item.role_confirmed)}>
                      {resolveGncRoleConfirmLabel(item.role_confirmed)}
                    </StatusBadge>
                  </div>
                </div>
                {item.blocking ? (
                  <StatusBadge tone="destructive">阻塞</StatusBadge>
                ) : null}
              </div>
              {(item.warnings || []).length ? (
                <div className="mt-2 flex flex-wrap gap-1.5">
                  {(item.warnings || []).map((warning) => (
                    <IssueBadge key={warning} label={warning} tone="warning" />
                  ))}
                </div>
              ) : null}
            </article>
          ))
        )}
      </section>
    </div>
  )
}

export default GncMaterialsTab
