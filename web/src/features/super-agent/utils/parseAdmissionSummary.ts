import type { ParsePreviewResponse } from '@/features/super-agent/types'
import { needsCalibrationReview, resolvePreviewBlocks } from '@/features/super-agent/utils/parsePreviewBlocks'
import {
  isStaleParsePreview,
  shouldShowCapabilityFailure,
  shouldShowDegradedNotice,
} from '@/features/super-agent/utils/parsePreviewFormat'

export type ParseAdmissionStatus = 'incomplete' | 'review_required' | 'ready'

export interface ParseAdmissionSummaryModel {
  status: ParseAdmissionStatus
  headline: string
  nextAction: string
  materialCount: number
  parsedOk: number
  degradedCount: number
  sectionCount: number | null
  evidenceCount: number | null
  structureReady: boolean | null
  risks: string[]
}

export function buildParseAdmissionSummary(
  preview: ParsePreviewResponse | null,
  options?: { loading?: boolean; parseBusy?: boolean },
): ParseAdmissionSummaryModel {
  const emptyStats = {
    materialCount: preview?.summary.material_count ?? 0,
    parsedOk: preview?.summary.parsed_ok ?? 0,
    degradedCount: preview?.summary.degraded_count ?? 0,
    sectionCount: preview?.structure_summary?.section_count ?? null,
    evidenceCount: preview?.structure_summary?.evidence_count ?? null,
    structureReady: preview?.structure_summary?.structure_ready ?? null,
  }

  if (options?.loading || options?.parseBusy || !preview) {
    const inProgress = Boolean(options?.loading || options?.parseBusy)
    return {
      status: 'incomplete',
      headline: inProgress ? '解析进行中' : '待启动解析',
      nextAction: inProgress
        ? '请等待解析完成后再核对对照预览。'
        : '请在工作台启动材料解析。',
      risks: [],
      ...emptyStats,
    }
  }

  const risks: string[] = []
  const structureSummary = preview.structure_summary
  const structureReady = structureSummary?.structure_ready ?? null

  if (isStaleParsePreview(preview)) {
    risks.push('当前预览为旧版数据，需重新解析以加载原文对照与分块 Markdown。')
  }

  for (const item of preview.materials) {
    if (shouldShowCapabilityFailure(item)) {
      risks.push(`${item.file_name}：解析能力未通过，需人工复核或补充解析后端。`)
      continue
    }
    if (shouldShowDegradedNotice(item)) {
      risks.push(`${item.file_name}：降级解析，建议核对关键表格与图表。`)
    }
    const calibrationCount = resolvePreviewBlocks(item).filter(needsCalibrationReview).length
    if (calibrationCount > 0) {
      risks.push(`${item.file_name}：${calibrationCount} 处内容块建议人工复核。`)
    }
  }

  if (structureSummary && !structureSummary.structure_ready) {
    risks.push('结构化产物尚未就绪，暂不可继续。')
  }

  const uniqueRisks = [...new Set(risks)].slice(0, 2)

  let status: ParseAdmissionStatus = 'ready'
  if (structureSummary && !structureSummary.structure_ready) {
    status = 'incomplete'
  } else if (uniqueRisks.length > 0) {
    status = 'review_required'
  }

  const headline =
    status === 'incomplete'
      ? '结构化未完成'
      : status === 'review_required'
        ? '需核对解析结果'
        : '解析已完成'

  const nextAction =
    status === 'incomplete'
      ? '请等待结构化产物生成，或重新解析后再核对。'
      : status === 'review_required'
        ? '请在对照工作台核对标出的风险项。'
        : '请确认对照预览无误后继续。'

  return {
    status,
    headline,
    nextAction,
    materialCount: preview.summary.material_count,
    parsedOk: preview.summary.parsed_ok,
    degradedCount: preview.summary.degraded_count,
    sectionCount: structureSummary?.section_count ?? null,
    evidenceCount: structureSummary?.evidence_count ?? null,
    structureReady,
    risks: uniqueRisks,
  }
}
