import { describe, expect, it } from 'vitest'
import {
  deriveRationaleSummary,
  isLikelyEnglishBusinessText,
  isPredominantlyEnglishText,
  isRawEnumToken,
  resolveCheckItemTitle,
  resolveDisplayName,
  resolveEvidenceStatusLabel,
  resolveJudgmentLabel,
  resolveLocalizedRationale,
  resolveLocalizedVerdict,
  resolveVerdictLabel,
  resolveWorkbenchStatusText,
  sanitizeBusinessText,
} from '@/features/unified-review-workbench/utils/zhWorkbenchText'

describe('zhWorkbenchText', () => {
  it('maps conditional_rejection to Chinese without exposing raw code', () => {
    expect(resolveVerdictLabel('conditional_rejection')).toBe('材料不足，暂无法完成完整审查')
    expect(resolveVerdictLabel('conditional_rejection')).not.toContain('conditional_rejection')
  })

  it('maps reject and review-plus release tokens to Chinese', () => {
    expect(resolveVerdictLabel('reject')).toBe('不通过')
    expect(resolveVerdictLabel('conditional')).toBe('有条件通过')
    expect(resolveVerdictLabel('needs_human_review')).toBe('待人工确认')
  })

  it('replaces English rationale with derived Chinese summary', () => {
    const english =
      'The uploaded package lacks primary design documents and fault analysis matrices required for a complete GNC CDR review.'
    expect(isLikelyEnglishBusinessText(english)).toBe(true)
    const summary = resolveLocalizedRationale({
      rationale: english,
      verdict: 'conditional_rejection',
      materialInsufficiency: true,
    })
    expect(summary).toContain('资料包')
    expect(summary).not.toContain('uploaded package')
    expect(summary).not.toContain('conditional_rejection')
  })

  it('replaces mixed English rationale even when rationale_zh is populated', () => {
    const mixed =
      'Primary design document missing; cannot complete full GNC Key Design Review at this time. GNC 关键设计审查材料不足。'
    expect(isPredominantlyEnglishText(mixed)).toBe(true)
    const summary = resolveLocalizedRationale({
      rationale: mixed,
      rationaleZh: mixed,
      verdict: 'conditional_rejection',
      materialInsufficiency: true,
    })
    expect(summary).toContain('资料包')
    expect(summary).not.toMatch(/primary design document/i)
  })

  it('maps bucket/status/expert/check item badges to Chinese', () => {
    expect(resolveWorkbenchStatusText('insufficient_evidence')).toBe('证据不足')
    expect(resolveJudgmentLabel('not_satisfied')).toBe('未满足')
    expect(resolveEvidenceStatusLabel('missing')).toBe('待补证')
    expect(resolveDisplayName('ac_thruster_layout_unit', 'expert')).toBe('专业审查项')
    expect(isRawEnumToken('ac_thruster_layout_unit')).toBe(true)
  })

  it('sanitizes check item English titles to Chinese fallback', () => {
    const title = 'Thruster layout unit alignment must be verified against ICD baseline revision C.'
    expect(resolveCheckItemTitle(title, 'insufficient_evidence')).toBe('该检查项需补充材料后确认')
    expect(sanitizeBusinessText(title, '该检查项待进一步确认', { hideEnglish: true }))
      .toBe('该检查项待进一步确认')
  })

  it('prefers backend zh verdict label when present', () => {
    expect(resolveLocalizedVerdict({
      verdict: 'conditional_rejection',
      verdictLabelZh: '材料不足，暂无法完成完整审查',
    })).toBe('材料不足，暂无法完成完整审查')
  })

  it('derives bucket-based rationale when English only', () => {
    expect(deriveRationaleSummary({
      buckets: { insufficient_evidence: 3 },
      verdict: 'conditional_pass',
    })).toContain('证据不足')
  })
})
