import type { ParsePreviewBlock } from '@/features/super-agent/types'
import { blockLayoutDisplayText } from '@/features/super-agent/utils/parsePreviewBlocks'

export function isFormulaBlockType(blockType: string): boolean {
  const value = blockType.trim().toLowerCase()
  return value === 'formula' || value.includes('equation') || value.includes('math')
}

/** Strip common LaTeX delimiters from MinerU / markdown formula text. */
export function normalizeFormulaLatex(raw: string): string {
  let text = raw.trim()
  if (!text) return ''

  if (text.startsWith('$$') && text.endsWith('$$') && text.length > 4) {
    text = text.slice(2, -2).trim()
  } else if (text.startsWith('\\[') && text.endsWith('\\]')) {
    text = text.slice(2, -2).trim()
  } else if (text.startsWith('\\(') && text.endsWith('\\)')) {
    text = text.slice(2, -2).trim()
  } else if (text.startsWith('$') && text.endsWith('$') && text.length > 2 && !text.startsWith('$$')) {
    text = text.slice(1, -1).trim()
  }

  return text
}

const LATEX_COMMAND_PATTERN =
  /\\(?:boldsymbol|mathbf|begin|frac|left|right|Bigg|bigg|Big|big|Phi|dot|sin|cos|tan|quad|cdots|eta|rho|sigma|alpha|beta|gamma|delta|theta|lambda|mu|pi|partial|nabla|sum|prod|int|sqrt|mathrm|operatorname|hat|widehat|widetilde|overline|underline|bar|vec|ddot|approx|cdot|times|leq|geq|neq|infty)\b/

const DISPLAY_MATH_TRIGGER = /\\(?:begin\{|frac|Bigg|bigg|left|array)|\\\\|\n/

/** Strip LaTeX evaluation-bar / norm markers so pipe-table heuristics ignore them. */
export function stripLatexPipeMarkers(text: string): string {
  return text
    .replace(/\\(?:Bigg|bigg|Big|big|middle|mid|vert|Vert)\s*\|/gi, '')
    .replace(/\\left\s*\|/g, '')
    .replace(/\\right\s*\|/g, '')
    .replace(/\\\|/g, '')
}

export function looksLikeLatexFormula(text: string): boolean {
  const normalized = normalizeFormulaLatex(text)
  if (!normalized) return false
  if (LATEX_COMMAND_PATTERN.test(normalized)) return true
  if (/[\^_]/.test(normalized) && /[A-Za-z0-9{}]/.test(normalized)) return true
  if (/^\d+\s*=\s*.+/.test(normalized) && /[\^_\\]/.test(normalized)) return true
  return false
}

export function isFullyMathDelimited(text: string): boolean {
  const trimmed = text.trim()
  if (trimmed.startsWith('$$') && trimmed.endsWith('$$') && trimmed.length > 4) return true
  if (trimmed.startsWith('\\[') && trimmed.endsWith('\\]')) return true
  return false
}

function hasRawUndelimitedLatex(text: string): boolean {
  let scratch = text
  scratch = scratch.replace(/\$\$[\s\S]*?\$\$/g, '')
  scratch = scratch.replace(/\$[^$\n]+\$/g, '')
  return looksLikeLatexFormula(scratch)
}

export function shouldUseDisplayMath(latex: string): boolean {
  return DISPLAY_MATH_TRIGGER.test(latex) || latex.trim().includes('\n')
}

export function isStandaloneFormulaText(text: string): boolean {
  const trimmed = text.trim()
  if (!trimmed) return false
  if (trimmed.startsWith('$$') && trimmed.endsWith('$$') && trimmed.length > 4) return true
  if (trimmed.startsWith('\\[') && trimmed.endsWith('\\]')) return true
  if (trimmed.startsWith('\\(') && trimmed.endsWith('\\)')) return true
  if (trimmed.startsWith('$') && trimmed.endsWith('$') && trimmed.length > 2 && !trimmed.startsWith('$$')) {
    return true
  }
  return false
}

function isGfmSeparatorRow(line: string): boolean {
  return /^\|?\s*:?-{3,}/.test(line.trim())
}

/** True when block text should render as a table, not as a standalone formula. */
export function isLayoutTableShapedContent(raw: string, blockType: string): boolean {
  if (/<table[\s>]/i.test(raw)) return true
  const value = blockType.trim().toLowerCase()
  if (value === 'table' || value.includes('table')) return true
  if (isFormulaBlockType(blockType) && looksLikeLatexFormula(raw)) return false
  if (!raw.includes('|')) return false
  const pipeProbe = stripLatexPipeMarkers(raw)
  if (!pipeProbe.includes('|')) return false
  const lines = pipeProbe
    .trim()
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
  if (!lines.length) return false
  if (lines.some((line) => isGfmSeparatorRow(line))) return true
  if (lines.filter((line) => line.includes('|')).length >= 2) return true
  if (lines.length === 1) {
    let stripped = lines[0]
    if (stripped.startsWith('|') && stripped.endsWith('|')) {
      stripped = stripped.slice(1, -1)
    }
    const cells = stripped.split('|').map((cell) => cell.trim())
    if (cells.length < 2) return false
    if (cells.some((cell) => looksLikeLatexFormula(cell))) return false
    return true
  }
  return false
}

/** Resolve formula LaTeX for layout view when block is formula-shaped. */
export function resolveLayoutBlockFormula(block: ParsePreviewBlock): string | null {
  const formulaLatex = typeof block.formula_latex === 'string' ? block.formula_latex.trim() : ''
  if (formulaLatex) return formulaLatex

  const raw = blockLayoutDisplayText(block)
  if (!raw) return null

  if (isLayoutTableShapedContent(raw, block.block_type)) return null

  if (isFormulaBlockType(block.block_type)) {
    return normalizeFormulaLatex(raw) || raw
  }

  if (isStandaloneFormulaText(raw)) {
    return normalizeFormulaLatex(raw)
  }

  return null
}

/** Wrap plain LaTeX as display math markdown for reading-mode renderers. */
export function formulaToDisplayMarkdown(latex: string): string {
  const normalized = normalizeFormulaLatex(latex)
  if (!normalized) return ''
  if (normalized.startsWith('$$') || normalized.startsWith('\\[')) return normalized
  return `$$\n${normalized}\n$$`
}

const INLINE_SUBSCRIPT_PATTERN = /\b([A-Za-z]+(?:_\{[^}]+\}|_[A-Za-z0-9]))(?=\s|[，,。；;:]|$)/g
const CJK_PATTERN = /[\u4e00-\u9fff]/

/** Wrap MinerU raw LaTeX fragments with $ / $$ delimiters for remark-math preview. */
export function ensureMathDelimitersInMarkdown(text: string): string {
  const trimmed = text.trim()
  if (!trimmed) return text
  if (isFullyMathDelimited(trimmed)) return text
  if (trimmed.includes('$') && !hasRawUndelimitedLatex(trimmed)) return text
  if (!looksLikeLatexFormula(trimmed)) return text

  const commandMatch = trimmed.match(
    /\\(?:boldsymbol|mathbf|begin|frac|left|right|Bigg|bigg|Phi|dot|sin|cos|tan|quad|cdots|eta|rho|sigma|alpha|beta|gamma|delta|theta|lambda|mu|pi|partial|nabla|sum|prod|int|sqrt|mathrm|operatorname|hat|widehat|widetilde|overline|underline|bar|vec|ddot|approx)/,
  )
  const commandIndex = commandMatch?.index ?? (trimmed.startsWith('\\') ? 0 : -1)

  if (commandIndex >= 0) {
    const prefix = trimmed.slice(0, commandIndex)
    const latex = trimmed.slice(commandIndex).trim().replace(/[，,。；;]+$/, '')
    if (!latex) return text
    if (!prefix.trim()) return formulaToDisplayMarkdown(latex)
    if (CJK_PATTERN.test(prefix)) {
      if (shouldUseDisplayMath(latex)) return `${prefix.trimEnd()}\n\n${formulaToDisplayMarkdown(latex)}`
      return `${prefix.trimEnd()} $${latex}$`
    }
    return formulaToDisplayMarkdown(latex)
  }

  return trimmed.replace(INLINE_SUBSCRIPT_PATTERN, (_match, token: string) => `$${token}$`)
}

/** Prefer KaTeX markdown rendering over escaped HTML for math-heavy preview blocks. */
export function shouldRenderPreviewWithMarkdown(block: ParsePreviewBlock, markdown: string): boolean {
  if (isFormulaBlockType(block.block_type)) return true
  if (isFullyMathDelimited(markdown)) return true
  return looksLikeLatexFormula(markdown)
}
