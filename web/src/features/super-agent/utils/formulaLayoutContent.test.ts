import { describe, expect, it } from 'vitest'
import {
  ensureMathDelimitersInMarkdown,
  formulaToDisplayMarkdown,
  isFormulaBlockType,
  isLayoutTableShapedContent,
  isStandaloneFormulaText,
  looksLikeLatexFormula,
  normalizeFormulaLatex,
  resolveLayoutBlockFormula,
  shouldRenderPreviewWithMarkdown,
  shouldUseDisplayMath,
  stripLatexPipeMarkers,
} from '@/features/super-agent/utils/formulaLayoutContent'
import { blockDisplayMarkdown } from '@/features/super-agent/utils/parsePreviewBlocks'
import { resolveLayoutBlockHtml, resolveLayoutBlockMarkdown } from '@/features/super-agent/utils/layoutBlockContent'
import type { ParsePreviewBlock } from '@/features/super-agent/types'

describe('formulaLayoutContent', () => {
  it('detects formula block types', () => {
    expect(isFormulaBlockType('formula')).toBe(true)
    expect(isFormulaBlockType('equation')).toBe(true)
    expect(isFormulaBlockType('paragraph')).toBe(false)
  })

  it('strips display math delimiters', () => {
    expect(normalizeFormulaLatex('$$R_{sys}=\\prod R_i$$')).toBe('R_{sys}=\\prod R_i')
    expect(normalizeFormulaLatex('\\[E=mc^2\\]')).toBe('E=mc^2')
  })

  it('recognizes latex-like text', () => {
    expect(looksLikeLatexFormula('R_{sys}=\\prod_{i=1}^{n} R_i')).toBe(true)
    expect(looksLikeLatexFormula('plain paragraph text')).toBe(false)
  })

  it('resolves formula from block type and formula_latex field', () => {
    const block: ParsePreviewBlock = {
      id: 'f1',
      block_type: 'formula',
      content: 'R_{sys}=\\prod R_i',
      formula_latex: 'R_{sys}=\\prod R_i',
    }
    expect(resolveLayoutBlockFormula(block)).toBe('R_{sys}=\\prod R_i')
    expect(resolveLayoutBlockMarkdown(block)).toContain('R_{sys}')
    expect(resolveLayoutBlockMarkdown(block)).toContain('$$')
  })

  it('wraps formula as display markdown', () => {
    expect(formulaToDisplayMarkdown('E=mc^2')).toBe('$$\nE=mc^2\n$$')
  })

  it('does not treat prose with inline bmatrix math as a standalone formula block', () => {
    const content =
      '其中， $\\boldsymbol{M}_{1}(k)=\\begin{bmatrix}m_{11}(k)&m_{12}(k)&m_{13}(k)\\\\ ' +
      'm_{21}(k)&m_{22}(k)&m_{23}(k)\\\\ m_{31}(k)&m_{32}(k)&m_{33}(k)\\end{bmatrix},' +
      '\\quad\\boldsymbol{M}_{2}(k)=\\begin{bmatrix}m_{14}(k)&m_{15}(k)&m_{16}(k)\\\\ ' +
      'm_{24}(k)&m_{25}(k)&m_{26}(k)\\\\ m_{34}(k)&m_{35}(k)&m_{36}(k)\\end{bmatrix},$'
    const block: ParsePreviewBlock = {
      id: 'inline-bmatrix',
      block_type: 'paragraph',
      content,
    }
    expect(looksLikeLatexFormula(content)).toBe(true)
    expect(isStandaloneFormulaText(content)).toBe(false)
    expect(resolveLayoutBlockFormula(block)).toBeNull()
    expect(resolveLayoutBlockMarkdown(block)).toBe(content)
  })

  it('wraps raw MinerU latex in mixed Chinese paragraphs', () => {
    const raw =
      '其中， \\boldsymbol{M}_{1}(k)=\\begin{bmatrix}m_{11}(k)&m_{12}(k)&m_{13}(k)\\\\ ' +
      'm_{21}(k)&m_{22}(k)&m_{23}(k)\\\\ m_{31}(k)&m_{32}(k)&m_{33}(k)\\end{bmatrix},'
    const block: ParsePreviewBlock = {
      id: 'raw-bmatrix',
      block_type: 'paragraph',
      content: raw,
    }
    const markdown = resolveLayoutBlockMarkdown(block)
    expect(markdown.startsWith('其中，')).toBe(true)
    expect(markdown).toContain('$$\n')
    expect(markdown).toContain('\\begin{bmatrix}')
  })

  it('wraps simple subscript variables for preview markdown', () => {
    expect(ensureMathDelimitersInMarkdown('V_{k} 为量测噪声')).toBe('$V_{k}$ 为量测噪声')
  })

  it('wraps widehat and overline commands without prior delimiters', () => {
    expect(looksLikeLatexFormula('\\widehat{x}')).toBe(true)
    expect(ensureMathDelimitersInMarkdown('\\widehat{x}')).toBe('$$\n\\widehat{x}\n$$')
    expect(ensureMathDelimitersInMarkdown('\\overline{y}')).toBe('$$\n\\overline{y}\n$$')
  })

  const jacobianRaw =
    '\\boldsymbol {H} = \\frac {\\partial \\boldsymbol {h} [' +
    '\\boldsymbol {X} _ {k } ] } { \\partial \\boldsymbol {X} _ { k } }' +
    '^ { T } } \\bigg | _ { \\boldsymbol {X} } _ { k } = \\hat { \\boldsymbol {X} } _ { k | k - 1 / k }' +
    ' \\approx \\left [ \\begin{array}{c c c} 1 & 0 & 0 \\\\ 0 & 1 & 0 \\\\ 0 & 0 & 1 \\end{array} \\right ]'

  const jacobianBiggRaw =
    '\\boldsymbol {H} = \\frac {\\partial \\boldsymbol {h} [ \\boldsymbol {X} _ {k} , k ]}{\\partial \\boldsymbol {X} _ {k} ^ {T}} \\Bigg | _ {\\boldsymbol {X} _ {k} = \\hat {\\boldsymbol {X}} _ {k + 1 / k}} \\approx \\left[ \\begin{array}{c c c} 1 & 0 & 0 \\\\ 0 & 1 & 0 \\\\ 0 & 0 & 1 \\\\ 0 & 0 & 0 \\\\ 0 & 0 & 0 \\\\ 0 & 0 & 0 \\end{array} \\right]'

  it('does not treat Jacobian Bigg| as a pipe table', () => {
    expect(stripLatexPipeMarkers(jacobianBiggRaw)).not.toContain('|')
    expect(isLayoutTableShapedContent(jacobianBiggRaw, 'formula')).toBe(false)
    expect(looksLikeLatexFormula(jacobianBiggRaw)).toBe(true)
  })

  it('resolves Jacobian formula block for layout KaTeX rendering', () => {
    const block: ParsePreviewBlock = {
      id: 'jacobian-layout',
      block_type: 'formula',
      content: jacobianBiggRaw,
      formula_latex: jacobianBiggRaw,
    }
    expect(resolveLayoutBlockFormula(block)).toBe(jacobianBiggRaw)
    expect(resolveLayoutBlockHtml(block)).toBeNull()
  })

  it('wraps inline noise variables in Chinese prose', () => {
    const wrapped = ensureMathDelimitersInMarkdown('式中， v_{k} ， w_{k} ， g_{k} 为三轴的量测噪声。')
    expect(wrapped).toBe('式中， $v_{k}$ ， $w_{k}$ ， $g_{k}$ 为三轴的量测噪声。')
  })

  it('wraps Jacobian raw latex as display math', () => {
    const wrapped = ensureMathDelimitersInMarkdown(jacobianRaw)
    expect(wrapped.startsWith('$$\n')).toBe(true)
    expect(wrapped.endsWith('\n$$')).toBe(true)
    expect(wrapped).toContain('\\begin{array}')
  })

  it('uses display math when Chinese prefix precedes multi-line Jacobian', () => {
    const wrapped = ensureMathDelimitersInMarkdown(`则量测方程的雅克比矩阵为 ${jacobianRaw}`)
    expect(wrapped).toContain('则量测方程的雅克比矩阵为')
    expect(wrapped).toContain('$$\n')
    expect(shouldUseDisplayMath(jacobianRaw)).toBe(true)
  })

  it('wraps formula blocks without delimiters in blockDisplayMarkdown', () => {
    const block: ParsePreviewBlock = {
      id: 'jacobian-formula',
      block_type: 'formula',
      content: jacobianRaw,
    }
    const markdown = blockDisplayMarkdown(block)
    expect(markdown.startsWith('$$\n')).toBe(true)
    expect(shouldRenderPreviewWithMarkdown(block, markdown)).toBe(true)
  })

  it('resolves fully delimited formula text as a standalone formula block', () => {
    const block: ParsePreviewBlock = {
      id: 'standalone-formula',
      block_type: 'paragraph',
      content: '$E=mc^2$',
    }
    expect(isStandaloneFormulaText(block.content)).toBe(true)
    expect(resolveLayoutBlockFormula(block)).toBe('E=mc^2')
  })

  it('does not treat html table with inline latex as a formula block', () => {
    const htmlTable =
      '<table><tr><td>日期</td><td colspan="2">2024.1.24</td><td>地点</td><td colspan="2">陆航检验室</td></tr>' +
      '<tr><td>检查项目</td><td>检查要求</td><td>检查结果</td><td>检查人</td><td>复核人</td><td>备注</td></tr>' +
      '<tr><td>环境温度</td><td> $20^{\\circ}C \\pm 5^{\\circ}C$ </td><td> $230^{\\circ}C$ </td>' +
      '<td rowspan="3">郭丹</td><td rowspan="3"></td><td></td></tr>' +
      '<tr><td>环境湿度</td><td>&lt;60%</td><td>41%</td><td></td></tr>' +
      '<tr><td>大气条件</td><td>大气</td><td></td><td></td></tr></table>'
    const block: ParsePreviewBlock = {
      id: 't-html-latex',
      block_type: 'table',
      content: htmlTable,
    }
    expect(isLayoutTableShapedContent(htmlTable, 'table')).toBe(true)
    expect(looksLikeLatexFormula(htmlTable)).toBe(true)
    expect(resolveLayoutBlockFormula(block)).toBeNull()
    const html = resolveLayoutBlockHtml(block)
    expect(html).toContain('<table>')
    expect(html).toContain('colspan="2"')
    expect(html).toContain('rowspan="3"')
    expect(html).toContain('class="katex"')
    expect(html).not.toContain('$230')
  })

  it('keeps HTML table blocks intact in blockDisplayMarkdown', () => {
    const htmlTable =
      '<table><tr><td>环境温度</td><td> $20^{\\circ}C \\pm 5^{\\circ}C$ </td></tr></table>'
    const block: ParsePreviewBlock = {
      id: 't-html-md',
      block_type: 'table',
      content: htmlTable,
      markdown: htmlTable,
    }
    expect(blockDisplayMarkdown(block)).toBe(htmlTable)
  })
})
