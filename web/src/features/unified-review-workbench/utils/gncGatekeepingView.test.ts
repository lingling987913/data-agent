import { describe, expect, it } from 'vitest'
import {
  groupGatekeepingIssues,
  resolveGncGateStatusLabel,
  resolveGncMaterialRoleLabel,
  resolveGncParseStatusLabel,
} from '@/features/unified-review-workbench/utils/gncGatekeepingView'

describe('gncGatekeepingView', () => {
  it('groupGatekeepingIssues returns only non-empty groups', () => {
    expect(groupGatekeepingIssues({
      blocking_reasons: ['缺少主文档'],
      warnings: [],
      missing_materials: ['design_solution'],
    })).toEqual([
      { key: 'blocking', title: '阻塞原因', tone: 'destructive', items: ['缺少主文档'] },
      { key: 'missing', title: '缺失材料', tone: 'neutral', items: ['design_solution'] },
    ])
  })

  it('resolveGncMaterialRoleLabel maps known roles', () => {
    expect(resolveGncMaterialRoleLabel('design_solution')).toBe('设计方案文档')
    expect(resolveGncMaterialRoleLabel('custom_role')).toBe('custom_role')
  })

  it('resolveGncGateStatusLabel maps gate statuses', () => {
    expect(resolveGncGateStatusLabel('blocked')).toBe('准入阻断')
    expect(resolveGncGateStatusLabel('limited_pass')).toBe('有条件准入')
  })

  it('resolveGncParseStatusLabel maps parse statuses', () => {
    expect(resolveGncParseStatusLabel('parsed')).toBe('已解析')
    expect(resolveGncParseStatusLabel('failed')).toBe('解析失败')
  })
})
