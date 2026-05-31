'use client'

import katex from 'katex'
import { useMemo } from 'react'
import type { CSSProperties } from 'react'
import { cn } from '@/vendor/ui-core/utils'
import { normalizeFormulaLatex } from '@/features/super-agent/utils/formulaLayoutContent'
import 'katex/dist/katex.min.css'

type FormulaRendererProps = {
  latex: string
  displayMode?: boolean
  className?: string
  style?: CSSProperties
}

export default function FormulaRenderer({
  latex,
  displayMode = true,
  className,
  style,
}: FormulaRendererProps) {
  const { html, error } = useMemo(() => {
    const normalized = normalizeFormulaLatex(latex)
    if (!normalized) {
      return { html: '', error: 'empty' }
    }
    try {
      return {
        html: katex.renderToString(normalized, {
          displayMode,
          throwOnError: false,
          strict: 'ignore',
          trust: false,
        }),
        error: '',
      }
    } catch (err) {
      return {
        html: '',
        error: err instanceof Error ? err.message : 'render failed',
      }
    }
  }, [latex, displayMode])

  if (!html) {
    return (
      <span className={cn('font-mono text-[0.95em] text-primary/85', className)} style={style}>
        {latex}
      </span>
    )
  }

  return (
    <span
      className={cn(
        'formula-renderer inline-block max-w-full leading-normal [&_.katex]:text-[length:inherit] [&_.katex-display]:my-0 [&_.katex-display]:max-w-full [&_.katex-display]:overflow-x-auto',
        className,
      )}
      style={style}
      title={error || undefined}
      dangerouslySetInnerHTML={{ __html: html }}
    />
  )
}
