'use client'

/**
 * 文件组审查 — 送审包面板
 *
 * 齐套性槽位 + 批量拖拽上传 + 材料清单；上传后由后端自动解析并判定材料角色。
 */

import { useEffect, useMemo, useRef, useState } from 'react'
import { GATEKEEPING_TERMS, PARSER_TYPE_LABELS, resolveUiLabel } from '@/lib/aeroTerminology'
import { StatusBadge } from '@aqua/ui-core'
import type {
  ReviewPlusGatekeepingResult,
  ReviewPlusMaterialItem,
  ReviewPlusParserType,
} from '@/features/review-plus-shared/types'
import { MATERIAL_ROLE_LABELS } from '@/features/review-plus-shared/types'
import {
  reviewPlusParseStatusTone,
  reviewPlusSlotStatusTone,
} from '@/features/review-plus-shared/utils/reviewPlusStatusTone'
import { resolvePrepWizardStep } from '@/features/review-plus-shared/utils/reviewPlusPrepWizard'

const PARSER_OPTIONS: Array<{ value: ReviewPlusParserType; label: string; description: string }> = [
  { value: 'auto', label: '自动选择', description: '按文件类型自动选择解析器' },
  { value: 'local', label: '本地解析', description: '适合 xlsx 与常规 docx' },
  { value: 'mineru', label: 'MinerU 本地', description: '局域网 MinerU 服务，适合 PDF 与图片' },
  { value: 'mineru_agent', label: 'MinerU 联网', description: 'MinerU 在线 Agent API，支持 PDF、Office、图片' },
]

type PackageSlot = {
  key: string
  label: string
  roles: string[]
  required: boolean
  description: string
}

const PACKAGE_SLOTS: PackageSlot[] = [
  {
    key: 'review_rule',
    label: '检查需求',
    roles: ['review_rule'],
    required: true,
    description: 'xlsx 检查项、审查准则、文档检查需求等材料',
  },
  {
    key: 'checklist',
    label: '检查单',
    roles: ['checklist'],
    required: true,
    description: '产品保证工作检查单、检查清单',
  },
  {
    key: 'task_book',
    label: '任务书',
    roles: ['task_book'],
    required: true,
    description: '研制任务书、任务要求、合同要求',
  },
  {
    key: 'subject_report',
    label: '被审报告',
    roles: ['subject_report', 'subject_document'],
    required: true,
    description: '可靠性安全性设计分析报告、被审方案/报告',
  },
  {
    key: 'supporting',
    label: '支撑附件',
    roles: ['supporting_attachment'],
    required: false,
    description: '会议纪要、历史材料、补充说明等',
  },
]

const MATERIAL_ROLES = Object.entries(MATERIAL_ROLE_LABELS).map(([value, label]) => ({ value, label }))

function roleLabel(role?: string): string {
  return MATERIAL_ROLE_LABELS[String(role || 'unknown')] || '未识别'
}

function parseStatusLabel(status?: string): string {
  if (status === 'ok' || status === 'parsed') return '解析正常'
  if (status === 'degraded' || status === 'partial') return '解析受限'
  if (status === 'failed') return '解析失败'
  if (status === 'parsing') return '解析中'
  return '待解析'
}

function slotStatusLabel(materials: ReviewPlusMaterialItem[], required: boolean): string {
  if (materials.length === 0) return required ? '缺失' : '未提供'
  if (materials.some((item) => item.parse_status === 'failed' || !(item.content || '').trim())) return '解析异常'
  if (materials.some((item) => !item.role_confirmed && String(item.role || '') !== 'unknown')) return '角色待确认'
  if (materials.some((item) => String(item.role || '') === 'unknown')) return '待判定'
  return '已满足'
}

function gateStatusLabel(status: string): string {
  if (status === 'passed') return GATEKEEPING_TERMS.passed
  if (status === 'limited') return GATEKEEPING_TERMS.limitedPass
  if (status === 'blocked') return GATEKEEPING_TERMS.blocked
  return '待检查'
}

export interface ReviewPlusDocumentPackagePanelProps {
  materials: ReviewPlusMaterialItem[]
  gatekeeping: ReviewPlusGatekeepingResult | null
  parserType: ReviewPlusParserType
  uploading: boolean
  /** 任务级解析是否完成（含 parse_artifact / status），由工作台传入 */
  parseComplete?: boolean
  /** 是否正在执行 Step 3 材料解析 */
  parsing?: boolean
  /** 任务 status，用于识别 parsing 等阶段 */
  taskStatus?: string
  onParserTypeChange: (value: ReviewPlusParserType) => void
  onFilesSelected: (files: FileList | null, preferredRole?: string) => void
  onRoleChange: (material: ReviewPlusMaterialItem, role: string) => void
  onConfirmRole: (material: ReviewPlusMaterialItem) => void
  onReclassify: () => void
  onReparseMaterial: (material: ReviewPlusMaterialItem, parserType: ReviewPlusParserType) => void
  onReparseAll: (parserType: ReviewPlusParserType) => void
  onPreview: (payload: { title: string; content: string }) => void
  onRecheckGate: () => void
  /** 只读模式：隐藏上传、角色确认、重解析等写操作，仅展示材料与门禁状态 */
  readOnly?: boolean
}

const PREP_WIZARD_STEPS = [
  { n: 1, label: '上传材料' },
  { n: 2, label: '确认角色' },
  { n: 3, label: '文档解析' },
  { n: 4, label: '准入通过' },
  { n: 5, label: '开始处理' },
] as const

export default function ReviewPlusDocumentPackagePanel({
  materials,
  gatekeeping,
  parserType,
  uploading,
  parseComplete: parseCompleteProp,
  parsing = false,
  taskStatus = '',
  onParserTypeChange,
  onFilesSelected,
  onRoleChange,
  onConfirmRole,
  onReclassify,
  onReparseMaterial,
  onReparseAll,
  onPreview,
  onRecheckGate,
  readOnly = false,
}: ReviewPlusDocumentPackagePanelProps) {
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [dragOver, setDragOver] = useState(false)
  const [pendingUploadRole, setPendingUploadRole] = useState('')

  const packageSlots = useMemo(() => {
    return PACKAGE_SLOTS.map((slot) => ({
      ...slot,
      materials: materials.filter((item) => slot.roles.includes(String(item.role || 'unknown'))),
    }))
  }, [materials])

  const requiredSlots = packageSlots.filter((slot) => slot.required)
  const satisfiedRequiredCount = requiredSlots.filter((slot) => slot.materials.length > 0).length
  const parseReadyCount = materials.filter((m) => (m.content || '').trim() && m.parse_status !== 'failed').length
  const unconfirmedCount = materials.filter((m) => !m.role_confirmed && String(m.role || '') !== 'unknown').length
  const unknownCount = materials.filter((m) => String(m.role || '') === 'unknown').length
  const missingRequiredSlots = requiredSlots.filter((slot) => slot.materials.length === 0)
  const gateStatus = String(gatekeeping?.gate_status || 'unknown')
  const materialParseComplete = materials.length > 0 && materials.every((item) => {
    const parseStatus = String(item.parse_status || '')
    if (parseStatus === 'failed') return false
    return Boolean((item.content || '').trim()) || parseStatus === 'ok' || parseStatus === 'degraded' || parseStatus === 'partial'
  })
  const parseComplete = parseCompleteProp ?? materialParseComplete
  const prepWizard = resolvePrepWizardStep(materials, gateStatus, missingRequiredSlots.length, {
    parseComplete,
    parsing,
    taskStatus,
  })

  const readinessText =
    uploading
      ? '正在批量上传、解析并自动判定材料角色...'
      : missingRequiredSlots.length > 0
        ? `缺少 ${missingRequiredSlots.map((slot) => slot.label).join('、')}`
        : unknownCount > 0
          ? `还有 ${unknownCount} 份材料角色未识别，请修正或重新判定`
          : unconfirmedCount > 0
            ? `还有 ${unconfirmedCount} 份材料角色待确认`
            : parseReadyCount < materials.length
              ? '存在解析异常材料'
              : '必需材料已齐套，可启动文件组审查'

  const readinessTone =
    missingRequiredSlots.length > 0 || gateStatus === 'blocked'
      ? 'border-destructive/20 bg-destructive/5 text-destructive'
      : unknownCount > 0 || unconfirmedCount > 0 || gateStatus === 'limited'
        ? 'border-warning/20 bg-warning/8 text-warning'
        : 'border-positive/20 bg-positive/8 text-positive'

  const requestUploadForRole = (role: string) => {
    setPendingUploadRole(role)
    fileInputRef.current?.click()
  }

  return (
    <div className="border border-border rounded-xl bg-surface overflow-hidden">
      <div className="px-4 py-4 sm:px-5">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <h3 className="text-sm font-medium text-primary">送审文档包</h3>
            <p className="text-[11px] text-muted mt-1 leading-relaxed">
              {readOnly
                ? '只读查看解析状态、材料角色与送审包门禁结果。'
                : '支持一次选择多份文件批量上传；系统会自动解析文本、判定材料角色并执行送审包准入检查。'}
            </p>
          </div>
        </div>

        <nav className="mt-4 rounded-xl border border-border/25 bg-background px-3 py-3" aria-label="送审准备步骤">
          <p className="text-[10px] font-medium text-muted">送审准备</p>
          <ol className="mt-2 flex flex-col gap-2 sm:flex-row sm:items-center sm:gap-0">
            {PREP_WIZARD_STEPS.map((item, index) => {
              const active = prepWizard.step === item.n
              const done = prepWizard.step > item.n
              const pending = prepWizard.step < item.n
              const parsingStep = item.n === 3 && active && (parsing || String(taskStatus) === 'parsing')
              return (
                <li key={item.n} className={`flex min-w-0 flex-1 items-center gap-2 ${index > 0 ? 'sm:pl-2' : ''}`}>
                  {index > 0 ? <span className="hidden h-px flex-1 bg-border/30 sm:block" aria-hidden /> : null}
                  <span className={`flex size-6 shrink-0 items-center justify-center rounded-full text-[10px] font-medium ${
                    done
                      ? 'bg-positive text-white'
                      : active
                        ? parsingStep
                          ? 'bg-primaryAccent text-white motion-safe:animate-pulse'
                          : 'bg-primaryAccent text-white'
                        : 'bg-muted/15 text-muted'
                  }`}>
                    {done ? '完' : item.n}
                  </span>
                  <span className={`min-w-0 truncate text-[11px] ${
                    active ? 'font-medium text-primary' : pending ? 'text-muted/60' : 'text-muted'
                  }`}>
                    {item.label}
                    {item.n === 3 && active && !parseComplete && !parsingStep ? (
                      <span className="ml-1 hidden text-[10px] font-normal text-warning sm:inline">待解析</span>
                    ) : null}
                  </span>
                </li>
              )
            })}
          </ol>
          <p className="mt-2 text-[11px] text-primaryAccent">{prepWizard.label}</p>
        </nav>

        {!readOnly ? (
        <>
        <details className="mt-3 rounded-lg border border-border/25 bg-muted/5 px-3 py-2">
          <summary className="cursor-pointer text-[11px] font-medium text-muted select-none">
            高级：文档解析设置
          </summary>
          <div className="mt-2 flex flex-col gap-2 sm:flex-row sm:items-center">
            <select
              className="w-full rounded-lg border border-border bg-background px-3 py-1.5 text-[11px] text-primary outline-none focus:border-brand/40 sm:max-w-xs"
              value={parserType}
              onChange={(e) => onParserTypeChange(e.target.value as ReviewPlusParserType)}
              aria-label="解析方式"
            >
              {PARSER_OPTIONS.map((opt) => (
                <option key={opt.value} value={opt.value} title={opt.description}>{opt.label}</option>
              ))}
            </select>
            <button
              type="button"
              disabled={uploading || materials.length === 0}
              onClick={() => onReparseAll(parserType)}
              className="rounded-lg border border-primaryAccent/30 px-3 py-1.5 text-[11px] font-medium text-primaryAccent hover:bg-primaryAccent/5 disabled:cursor-not-allowed disabled:opacity-50"
              data-testid="review-plus-v2-batch-reparse"
            >
              {uploading ? '处理中...' : '按当前设置重新解析全部'}
            </button>
          </div>
          <p className="mt-1.5 text-[10px] leading-relaxed text-muted">
            默认自动选择即可；仅当解析质量不理想时再调整并重新解析。
          </p>
        </details>

        <div
          role="button"
          tabIndex={0}
          onKeyDown={(e) => {
            if ((e.key === 'Enter' || e.key === ' ') && !uploading) {
              e.preventDefault()
              fileInputRef.current?.click()
            }
          }}
          onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(e) => {
            e.preventDefault()
            setDragOver(false)
            if (e.dataTransfer.files.length > 0) onFilesSelected(e.dataTransfer.files)
          }}
          onClick={() => { if (!uploading) fileInputRef.current?.click() }}
          className={`mt-4 rounded-xl border border-dashed p-6 text-center cursor-pointer motion-safe:transition-colors ${
            dragOver
              ? 'border-primaryAccent bg-primaryAccent/5'
              : 'border-border/40 hover:border-primaryAccent/40 hover:bg-muted/5'
          }`}
          data-testid="review-plus-v2-upload-dropzone"
        >
          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept=".xlsx,.xls,.docx,.doc,.pdf,.txt,.md"
            className="hidden"
            onChange={(e) => {
              if (e.target.files?.length) {
                onFilesSelected(e.target.files, pendingUploadRole || undefined)
              }
              setPendingUploadRole('')
              e.currentTarget.value = ''
            }}
            data-testid="review-plus-v2-upload-input"
          />
          <p className="text-sm font-medium text-primary">
            {uploading ? '正在上传、解析并自动判定角色...' : '拖拽多个文件到此处，或点击批量选择'}
          </p>
          <p className="text-[11px] text-muted mt-1.5">
            无需按类型逐个上传；解析完成后可在顶部切换解析方式并批量重新解析全部材料。
          </p>
          <button
            type="button"
            disabled={uploading}
            onClick={(e) => {
              e.stopPropagation()
              fileInputRef.current?.click()
            }}
            className="mt-3 rounded-2xl bg-brand px-4 py-2 text-sm text-white disabled:opacity-50 motion-safe:active:scale-[0.98]"
            data-testid="review-plus-v2-upload-button"
          >
            {uploading ? '处理中...' : '批量选择文件'}
          </button>
        </div>
        </>
        ) : null}
      </div>

      <div className="border-t border-border/40 px-4 py-4 space-y-3 sm:px-5">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
          <div>
            <h4 className="text-[12px] font-medium text-primary">送审包齐套性检查</h4>
            <p className="mt-0.5 text-[11px] text-muted">按检查需求、检查单、任务书与被审报告四类必需角色校验。</p>
          </div>
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-1.5 text-center text-[10px]">
            <StatChip value={`${satisfiedRequiredCount}/${requiredSlots.length}`} label="必需角色" />
            <StatChip value={`${parseReadyCount}/${materials.length || 0}`} label="可审文本" />
            <StatChip value={String(unconfirmedCount)} label="待确认" />
            <StatChip value={gateStatusLabel(gateStatus)} label={GATEKEEPING_TERMS.label} highlight={gateStatus === 'blocked'} />
          </div>
        </div>

        <div className={`rounded-lg border px-3 py-2 text-[11px] ${readinessTone}`}>
          {readinessText}
        </div>

        {!readOnly ? (
        <div className="flex flex-wrap gap-2">
          <button
            type="button"
            onClick={onReclassify}
            disabled={uploading || materials.length === 0}
            className="rounded-lg border border-border/30 px-3 py-1 text-[10px] text-primary hover:border-brand/40 disabled:opacity-50"
          >
            重新自动判定角色
          </button>
          <button
            type="button"
            onClick={onRecheckGate}
            disabled={uploading}
            className="rounded-lg border border-border/30 px-3 py-1 text-[10px] text-primaryAccent hover:border-brand/40 disabled:opacity-50"
          >
            {GATEKEEPING_TERMS.recheck}
          </button>
        </div>
        ) : null}

        <div className="space-y-2">
          {packageSlots.map((slot) => {
            const statusLabel = slotStatusLabel(slot.materials, slot.required)
            const primaryRole = slot.roles[0]
            return (
              <div key={slot.key} className="rounded-lg border border-border/35 bg-background px-3 py-3">
                <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2">
                      <span className="text-[12px] font-medium text-primary">{slot.label}</span>
                      <StatusBadge tone={reviewPlusSlotStatusTone(slot.materials, slot.required)}>
                        {statusLabel}
                      </StatusBadge>
                      <StatusBadge tone={slot.required ? 'destructive' : 'neutral'}>
                        {slot.required ? '必需' : '可选'}
                      </StatusBadge>
                    </div>
                    <p className="mt-1 text-[10px] leading-relaxed text-muted">{slot.description}</p>
                  </div>
                  {!readOnly ? (
                  <button
                    type="button"
                    onClick={() => requestUploadForRole(primaryRole)}
                    disabled={uploading}
                    className={`shrink-0 rounded-lg border px-2.5 py-1 text-[10px] motion-safe:transition-colors ${
                      slot.required && slot.materials.length === 0
                        ? 'border-destructive/30 text-destructive hover:bg-destructive/5'
                        : 'border-primaryAccent/30 text-primaryAccent hover:bg-primaryAccent/5'
                    }`}
                  >
                    {slot.materials.length > 0 ? '补充此类' : '上传此类'}
                  </button>
                  ) : null}
                </div>

                {slot.materials.length > 0 ? (
                  <ul className="mt-3 space-y-2 border-t border-border/20 pt-2">
                    {slot.materials.map((material) => (
                      <MaterialRow
                        key={material.name}
                        material={material}
                        uploading={uploading}
                        parserType={parserType}
                        readOnly={readOnly}
                        onRoleChange={onRoleChange}
                        onConfirmRole={onConfirmRole}
                        onReparseMaterial={onReparseMaterial}
                        onPreview={onPreview}
                      />
                    ))}
                  </ul>
                ) : null}
              </div>
            )
          })}
        </div>
      </div>

      {gatekeeping ? (
        <div className="border-t border-border/40 px-4 py-4 sm:px-5">
          <p className="text-[11px] text-muted leading-relaxed">{gatekeeping.gate_summary || '—'}</p>
          <div className="mt-3 grid gap-3 sm:grid-cols-3 text-[11px]">
            <GateList title="缺失材料" items={gatekeeping.missing_materials} />
            <GateList title="阻断原因" items={gatekeeping.blocking_reasons} />
            <GateList title="受限说明" items={gatekeeping.limited_scope} />
          </div>
        </div>
      ) : null}
    </div>
  )
}

function MaterialRow({
  material,
  uploading,
  parserType,
  readOnly = false,
  onRoleChange,
  onConfirmRole,
  onReparseMaterial,
  onPreview,
}: {
  material: ReviewPlusMaterialItem
  uploading: boolean
  parserType: ReviewPlusParserType
  readOnly?: boolean
  onRoleChange: (material: ReviewPlusMaterialItem, role: string) => void
  onConfirmRole: (material: ReviewPlusMaterialItem) => void
  onReparseMaterial: (material: ReviewPlusMaterialItem, parserType: ReviewPlusParserType) => void
  onPreview: (payload: { title: string; content: string }) => void
}) {
  const currentParser = PARSER_OPTIONS.some((option) => option.value === material.parser_type)
    ? material.parser_type as ReviewPlusParserType
    : material.parser_type === 'mineru_via_pdf'
      ? 'mineru_agent'
      : parserType
  const [reparseParser, setReparseParser] = useState<ReviewPlusParserType>(currentParser)
  useEffect(() => {
    setReparseParser(currentParser)
  }, [currentParser, material.name])

  const parseStatus = parseStatusLabel(material.parse_status)
  const confidence = material.role_confidence != null ? Math.round(material.role_confidence * 100) : null
  const autoClassified = material.role_confirmed && confidence != null && confidence >= 75

  return (
    <li className="rounded-lg border border-border/25 bg-surface px-3 py-2.5">
      <div className="flex flex-col gap-2 lg:flex-row lg:items-start lg:justify-between">
        <div className="min-w-0 flex-1">
          <p className="text-[12px] font-medium text-primary truncate">{material.name}</p>
          <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
            <StatusBadge tone={reviewPlusParseStatusTone(material.parse_status)}>
              {parseStatus}
            </StatusBadge>
            <StatusBadge tone="neutral">{roleLabel(String(material.role))}</StatusBadge>
            {confidence != null ? (
              <span className="text-[9px] text-muted tabular-nums">置信度 {confidence}%</span>
            ) : null}
            {material.parser_name || material.parser_type ? (
              <span className="text-[9px] text-muted">
                {material.parser_name || resolveUiLabel(PARSER_TYPE_LABELS, material.parser_type, '')}
              </span>
            ) : null}
            {autoClassified ? (
              <span className="text-[9px] text-positive">已自动判定</span>
            ) : material.role_confirmed ? (
              <span className="text-[9px] text-positive">已确认</span>
            ) : (
              <span className="text-[9px] text-warning">待确认</span>
            )}
          </div>
          {material.role_reason ? (
            <p className="mt-1 text-[10px] text-muted/80 leading-relaxed">{material.role_reason}</p>
          ) : null}
        </div>
        {readOnly ? (
          <div className="flex shrink-0">
            <button
              type="button"
              onClick={() => onPreview({ title: material.name, content: material.content || '暂无解析内容' })}
              className="rounded-lg border border-border/30 px-2 py-1 text-[10px] text-primary hover:border-brand/40"
            >
              查看
            </button>
          </div>
        ) : (
        <div className="flex flex-wrap items-center gap-1.5 shrink-0">
          <select
            value={String(material.role || 'unknown')}
            onChange={(e) => onRoleChange(material, e.target.value)}
            disabled={uploading}
            className="rounded-lg border border-border/30 bg-background px-2 py-1 text-[10px] text-primary focus:border-brand/40 outline-none"
            aria-label={`${material.name} 材料角色`}
          >
            {MATERIAL_ROLES.map((role) => (
              <option key={role.value} value={role.value}>{role.label}</option>
            ))}
          </select>
          {!material.role_confirmed ? (
            <button
              type="button"
              disabled={uploading}
              onClick={() => onConfirmRole(material)}
              className="rounded-lg border border-positive/30 bg-positive/10 px-2 py-1 text-[10px] text-positive"
            >
              确认角色
            </button>
          ) : null}
          <button
            type="button"
            disabled={uploading}
            onClick={() => onReparseMaterial(material, reparseParser)}
            className="rounded-lg border border-primaryAccent/30 px-2 py-1 text-[10px] text-primaryAccent hover:bg-primaryAccent/5 disabled:opacity-50"
            title="使用「高级：文档解析设置」中的解析方式"
          >
            重新解析
          </button>
          <button
            type="button"
            onClick={() => onPreview({ title: material.name, content: material.content || '暂无解析内容' })}
            className="rounded-lg border border-border/30 px-2 py-1 text-[10px] text-primary hover:border-brand/40"
          >
            预览
          </button>
        </div>
        )}
      </div>
    </li>
  )
}

function StatChip({ value, label, highlight }: { value: string; label: string; highlight?: boolean }) {
  return (
    <div className={`rounded-lg border px-2 py-1.5 ${highlight ? 'border-destructive/30 bg-destructive/5' : 'border-border/40 bg-background'}`}>
      <div className={`font-semibold text-[11px] ${highlight ? 'text-destructive' : 'text-primary'}`}>{value}</div>
      <div className="text-muted">{label}</div>
    </div>
  )
}

function GateList({ title, items }: { title: string; items?: string[] }) {
  return (
    <div>
      <p className="font-medium text-primary">{title}</p>
      {(items || []).length ? (
        <ul className="mt-1 space-y-1 text-destructive">
          {items!.map((item) => <li key={item}>{item}</li>)}
        </ul>
      ) : (
        <p className="mt-1 text-muted">无</p>
      )}
    </div>
  )
}
