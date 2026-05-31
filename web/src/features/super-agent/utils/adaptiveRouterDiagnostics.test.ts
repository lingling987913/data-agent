import { describe, expect, it } from 'vitest'
import {
  adaptiveRouteToRequestedRoute,
  labelAdaptiveDomain,
  labelAdaptiveRoute,
  resolveAdaptiveRouterDiagnostics,
} from '@/features/super-agent/utils/adaptiveRouterDiagnostics'
import type { MaterialClassification } from '@/features/super-agent/types'

describe('adaptiveRouterDiagnostics', () => {
  it('returns visible=false when adaptive_router is absent', () => {
    const diagnostics = resolveAdaptiveRouterDiagnostics({ doc_type: 'x', domain: 'y', recommended_route: 'smart', reason: 'z' })
    expect(diagnostics.visible).toBe(false)
  })

  it('labels domain/route and counts specialists', () => {
    const classification: MaterialClassification = {
      doc_type: '电机规格',
      domain: '机械/电气',
      recommended_route: 'smart',
      reason: 'test',
      adaptive_router: {
        source: 'llm',
        domain_id: 'generic_document_review',
        route: 'smart',
        primary_path: 'smart_committee',
        confidence: 0.82,
        reasoning_summary: '机械文档走通用智能审查',
        selected_capabilities: { specialist_ids: ['document_consistency_reviewer'] },
        task_specs: [{ task_id: 't1' }],
        guardrail_corrections: ['机械/电气文档且无强航天信号，aerospace → generic_document_review'],
      },
    }
    const diagnostics = resolveAdaptiveRouterDiagnostics(classification)
    expect(diagnostics.visible).toBe(true)
    expect(diagnostics.domainLabel).toBe(labelAdaptiveDomain('generic_document_review'))
    expect(diagnostics.routeLabel).toBe(labelAdaptiveRoute('smart'))
    expect(diagnostics.specialistCount).toBe(1)
    expect(diagnostics.taskSpecCount).toBe(1)
    expect(diagnostics.hasGuardrailCorrections).toBe(true)
    expect(diagnostics.confidencePercent).toBe(82)
  })

  it('maps adaptive routes to requested_route', () => {
    expect(adaptiveRouteToRequestedRoute('review_plus')).toBe('review_plus')
    expect(adaptiveRouteToRequestedRoute('gnc_review')).toBe('gnc_review_only')
    expect(adaptiveRouteToRequestedRoute('smart')).toBe('smart')
  })
})
