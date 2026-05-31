import { describe, expect, it } from 'vitest'
import {
  renderFormulasInLayoutTableHtml,
  renderFormulasInPlainText,
} from '@/features/super-agent/utils/layoutTableFormulaHtml'

describe('layoutTableFormulaHtml', () => {
  it('renders inline latex in plain text', () => {
    const html = renderFormulasInPlainText(' $230^{\\circ}C$ ')
    expect(html).toContain('class="katex"')
    expect(html).not.toContain('$230')
  })

  it('renders latex inside table cell text nodes only', () => {
    const table =
      '<table><tr><td>环境温度</td><td> $20^{\\circ}C \\pm 5^{\\circ}C$ </td>' +
      '<td> $230^{\\circ}C$ </td></tr></table>'
    const html = renderFormulasInLayoutTableHtml(table)
    expect(html).toContain('class="katex"')
    expect(html).not.toContain('$230')
    expect(html).not.toContain('$20')
    expect(html).toContain('环境温度')
  })

  it('leaves non-math cell text unchanged', () => {
    const table = '<table><tr><td>日期</td><td>2024.1.24</td></tr></table>'
    expect(renderFormulasInLayoutTableHtml(table)).toBe(table)
  })
})
