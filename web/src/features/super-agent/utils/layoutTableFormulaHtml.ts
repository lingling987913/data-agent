import katex from 'katex'
import { normalizeFormulaLatex } from '@/features/super-agent/utils/formulaLayoutContent'

function renderKaTeX(latex: string, displayMode: boolean): string | null {
  const wrapped = displayMode ? `$$${latex}$$` : `$${latex}$`
  const normalized = normalizeFormulaLatex(wrapped)
  if (!normalized) return null
  try {
    return katex.renderToString(normalized, {
      displayMode,
      throwOnError: false,
      strict: 'ignore',
      trust: false,
    })
  } catch {
    return null
  }
}

/** Render $...$ / $$...$$ in plain text (table cell body). */
export function renderFormulasInPlainText(text: string): string {
  if (!text.includes('$')) return text

  let result = text.replace(/\$\$([\s\S]+?)\$\$/g, (match, body: string) => {
    return renderKaTeX(body.trim(), true) ?? match
  })
  result = result.replace(/\$([^$\n]+?)\$/g, (match, body: string) => {
    return renderKaTeX(body.trim(), false) ?? match
  })
  return result
}

/** KaTeX-render inline/display math inside table cell text nodes. */
export function renderFormulasInLayoutTableHtml(html: string): string {
  if (!html.includes('$')) return html
  return html.replace(/>([^<]+)</g, (full, text: string) => {
    if (!text.includes('$')) return full
    return `>${renderFormulasInPlainText(text)}<`
  })
}
