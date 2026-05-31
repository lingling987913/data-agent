'use client'

import { useCallback } from 'react'
import { toast } from 'sonner'
import type {
  ReviewPlusCoverageMatrixRow,
  ReviewPlusFinding,
  ReviewPlusTaskDetail,
} from '@/features/review-plus-v2/types'
import {
  buildHighlightsFromRefs,
  findMatchingTraceLink,
  resolveTraceMatrixRowId,
  type WorkbenchSelection,
} from '@/features/review-plus-v2/utils/aeroDesignerWorkbenchUtils'

export function useReviewPlusEvidenceSelection(
  task: Pick<ReviewPlusTaskDetail, 'materials'> & Partial<ReviewPlusTaskDetail>,
) {
  const buildFromCoverage = useCallback((row: ReviewPlusCoverageMatrixRow): WorkbenchSelection | null => {
    const refs = [
      ...(row.task_book_evidence_refs || []),
      ...(row.subject_evidence_refs || []),
    ]
    const highlights = buildHighlightsFromRefs(refs, task.materials)
    if (!highlights.length) {
      toast.info(`检查项 ${row.check_item_id || '—'} 暂无可定位的原文证据。`)
      return null
    }

    const matchedLink = findMatchingTraceLink(task, {
      source: 'coverage',
      checkItemId: row.check_item_id,
      quote: row.source_quote,
      requiresHumanConfirmation: row.requires_human_confirmation,
      highlights,
    })

    return {
      source: 'coverage',
      checkItemId: row.check_item_id,
      quote: row.source_quote,
      requiresHumanConfirmation: row.requires_human_confirmation,
      pendingTraceLinkId: matchedLink?.link_id,
      highlights,
    }
  }, [task])

  const buildFromFinding = useCallback((finding: ReviewPlusFinding): WorkbenchSelection | null => {
    const refs = [
      ...(finding.task_book_evidence_refs || []),
      ...(finding.subject_evidence_refs || []),
      ...(finding.evidence_refs || []),
    ]
    const uniqueRefs = refs.filter((ref, idx) => refs.indexOf(ref) === idx)
    const highlights = buildHighlightsFromRefs(uniqueRefs, task.materials)
    if (!highlights.length) {
      toast.info('该审查记录暂无可定位的原文证据。')
      return null
    }

    const matchedLink = findMatchingTraceLink(task, {
      source: 'finding',
      findingId: finding.finding_id,
      quote: finding.source_quote,
      requiresHumanConfirmation: finding.requires_human_confirmation,
      highlights,
    })

    return {
      source: 'finding',
      findingId: finding.finding_id,
      quote: finding.source_quote,
      requiresHumanConfirmation: finding.requires_human_confirmation,
      pendingTraceLinkId: matchedLink?.link_id,
      highlights,
    }
  }, [task])

  const buildFromTraceability = useCallback((rowData: Record<string, unknown>): WorkbenchSelection | null => {
    const requirement = rowData.requirement as Record<string, unknown> | undefined
    const evRef = String(requirement?.source_evidence_id || rowData.source_evidence_id || '')
    const highlights = buildHighlightsFromRefs(evRef ? [evRef] : [], task.materials)
    const rowId = resolveTraceMatrixRowId(rowData)

    if (!highlights.length) {
      toast.info(`追溯项 ${rowId || '—'} 暂无可定位的原文证据。`)
      return null
    }

    const matchedLink = findMatchingTraceLink(task, {
      source: 'traceability',
      traceRowId: rowId,
      quote: String(requirement?.source_quote || rowData.source_quote || ''),
      highlights,
    })

    return {
      source: 'traceability',
      traceRowId: rowId,
      quote: String(requirement?.source_quote || rowData.source_quote || ''),
      pendingTraceLinkId: matchedLink?.link_id,
      highlights,
    }
  }, [task.materials, task])

  const buildFromCrossDoc = useCallback((item: Record<string, unknown>): WorkbenchSelection | null => {
    const evidenceIds = Array.isArray(item.evidence_ids) ? item.evidence_ids as string[] : []
    const highlights = buildHighlightsFromRefs(evidenceIds, task.materials)
    const itemId = String(item.review_item_id || '')

    if (!highlights.length) {
      toast.info('该跨文档问题暂无可定位的行级证据，请查看源文摘录。')
      return null
    }

    return {
      source: 'cross_doc',
      crossDocItemId: itemId,
      quote: String(item.source_quote || ''),
      highlights,
    }
  }, [task.materials])

  return {
    buildFromCoverage,
    buildFromFinding,
    buildFromTraceability,
    buildFromCrossDoc,
  }
}
