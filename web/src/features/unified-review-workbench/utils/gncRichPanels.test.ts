import { describe, expect, it } from 'vitest'
import {
  extractGncArbitrationConflictIds,
  formatGncDisplayListItem,
  formatGncVerdictLabel,
  hasGncDecisionContent,
  hasGncMinutesVisibleSections,
  hasRichMinutesStruct,
  parseGncDecision,
  parseGncReportPayload,
  resolveGncArbitrationDisplayStatus,
  summarizeRecordMap,
} from '@/features/unified-review-workbench/utils/gncRichPanels'

describe('gncRichPanels', () => {
  it('parseGncDecision maps chief fields', () => {
    const parsed = parseGncDecision({
      verdict: 'conditionally_approved',
      rationale: '存在 open RID',
      requires_arbitration: true,
      arbitration_items: ['c-1'],
      key_risks: ['姿态精度'],
      conflict_resolutions: ['c-1: 采纳 AD 组'],
      conflict_analysis: [{ conflict_id: 'c-1', summary: '相左' }],
    })
    expect(parsed.verdict).toBe('conditionally_approved')
    expect(parsed.arbitrationItems).toEqual(['c-1'])
    expect(parsed.keyRisks).toEqual(['姿态精度'])
    expect(parsed.conflictAnalysis).toHaveLength(1)
  })

  it('resolveGncArbitrationDisplayStatus covers pending and resolved', () => {
    expect(
      resolveGncArbitrationDisplayStatus({
        arbitrationStatus: 'pending',
        requiresArbitration: true,
      }),
    ).toBe('pending')
    expect(
      resolveGncArbitrationDisplayStatus({
        arbitrationStatus: 'resolved',
        requiresArbitration: false,
      }),
    ).toBe('resolved')
    expect(
      resolveGncArbitrationDisplayStatus({
        requiresArbitration: false,
        workbenchPhase: 'completed',
      }),
    ).toBe('not_required')
    expect(
      resolveGncArbitrationDisplayStatus({
        requiresArbitration: false,
        workbenchPhase: 'arbitration',
      }),
    ).toBe('not_required')
  })

  it('hasGncDecisionContent detects partial decision payloads', () => {
    expect(hasGncDecisionContent(parseGncDecision({}))).toBe(false)
    expect(hasGncDecisionContent(parseGncDecision({ key_risks: ['姿态精度'] }))).toBe(true)
    expect(hasGncDecisionContent(parseGncDecision({ conflict_analysis: [{ conflict_id: 'c-1' }] }))).toBe(true)
    expect(hasGncDecisionContent(parseGncDecision({ requires_arbitration: true }))).toBe(true)
  })

  it('parseGncDecision preserves object arbitration items', () => {
    const parsed = parseGncDecision({
      arbitration_items: [
        { conflict_id: 'c-1', title: '姿态算法', summary: 'AD/AC 结论相左' },
      ],
      conflict_resolutions: [
        { conflict_id: 'c-1', resolution: '采纳 AD 组', reason: '证据更充分', source: 'chief' },
      ],
    })
    expect(parsed.arbitrationItems).toHaveLength(1)
    expect(formatGncDisplayListItem(parsed.arbitrationItems[0]).title).toBe('c-1')
    expect(formatGncDisplayListItem(parsed.arbitrationItems[0]).detail).toContain('姿态算法')
    expect(formatGncDisplayListItem(parsed.conflictResolutions[0]).detail).toContain('采纳 AD 组')
  })

  it('extractGncArbitrationConflictIds reads string and object items', () => {
    expect(extractGncArbitrationConflictIds(['c-1'])).toEqual(['c-1'])
    expect(
      extractGncArbitrationConflictIds([
        { conflict_id: 'c-1' },
        { conflict_key: 'k-2' },
        { summary: 'no id' },
      ]),
    ).toEqual(['c-1', 'k-2'])
  })

  it('formatGncVerdictLabel localizes known verdicts', () => {
    expect(formatGncVerdictLabel('conditionally_approved')).toBe('有条件通过')
    expect(formatGncVerdictLabel('custom')).toBe('custom')
  })

  it('hasRichMinutesStruct detects structured minutes', () => {
    expect(hasRichMinutesStruct({ text: 'plain' })).toBe(true)
    expect(hasRichMinutesStruct({ section_rid_map: { s1: { rid_count: 1 } } })).toBe(true)
    expect(hasRichMinutesStruct({ follow_up_items: ['整改项 A'] })).toBe(true)
    expect(hasRichMinutesStruct({})).toBe(false)
  })

  it('hasGncMinutesVisibleSections distinguishes empty structured payloads', () => {
    expect(hasGncMinutesVisibleSections({ section_rid_map: {} })).toBe(false)
    expect(hasGncMinutesVisibleSections({ follow_up_items: ['  '] })).toBe(false)
    expect(hasGncMinutesVisibleSections({ follow_up_items: ['整改项 A'] })).toBe(true)
  })

  it('parseGncReportPayload reads markdown object', () => {
    expect(parseGncReportPayload({ markdown: '# Report' })?.markdown).toBe('# Report')
    expect(parseGncReportPayload(null)).toBeNull()
  })

  it('summarizeRecordMap formats nested summaries', () => {
    const rows = summarizeRecordMap({
      '姿态确定算法设计': { passed: 2, failed: 1 },
      sec1: { rid_count: 3 },
    })
    expect(rows[0]?.detail).toContain('通过 2')
    expect(rows[1]?.detail).toBe('RID 3 条')
  })
})
