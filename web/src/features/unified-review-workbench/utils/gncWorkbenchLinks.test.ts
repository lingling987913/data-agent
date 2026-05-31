import { describe, expect, it } from 'vitest'
import {
  collectRelatedEvidenceIds,
  collectRelatedRidIds,
  extractEvidenceRidId,
  extractRidContext,
  extractRuleLinkTargets,
} from '@/features/unified-review-workbench/utils/gncWorkbenchLinks'

describe('gncWorkbenchLinks', () => {
  it('collectRelatedEvidenceIds merges alternate field names', () => {
    expect(collectRelatedEvidenceIds({
      evidence_ids: ['e-1'],
      source_evidence_ids: ['e-2', 'e-1'],
    })).toEqual(['e-1', 'e-2'])
  })

  it('collectRelatedRidIds reads related rid fields only', () => {
    expect(collectRelatedRidIds({
      rid_id: 'self-rid',
      related_rid_id: 'rid-1',
      related_rid_ids: ['rid-2'],
    })).toEqual(expect.arrayContaining(['rid-1', 'rid-2']))
    expect(collectRelatedRidIds({
      rid_id: 'self-rid',
      related_rid_id: 'rid-1',
      related_rid_ids: ['rid-2'],
    })).toHaveLength(2)
  })

  it('extractEvidenceRidId prefers review_item and rid aliases on evidence', () => {
    expect(extractEvidenceRidId({ review_item_id: 'rid-9' })).toBe('rid-9')
    expect(extractEvidenceRidId({ related_rid_id: 'rid-8' })).toBe('rid-8')
  })

  it('extractRidContext normalizes source fields', () => {
    expect(extractRidContext({
      source_rule_id: 'rule-1',
      unit_key: 'unit-a',
      section_id: 'sec-1',
      review_item: 'item-1',
    })).toEqual({
      ruleId: 'rule-1',
      unitKey: 'unit-a',
      sectionId: 'sec-1',
      reviewItemId: 'item-1',
    })
  })

  it('extractRuleLinkTargets collects evidence and rid links on rules', () => {
    expect(extractRuleLinkTargets({
      related_evidence_ids: ['e-1'],
      rid_id: 'rid-1',
    })).toEqual({
      evidenceIds: ['e-1'],
      ridIds: ['rid-1'],
    })
  })
})
