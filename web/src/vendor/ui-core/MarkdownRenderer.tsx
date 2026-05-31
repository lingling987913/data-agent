'use client'

import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import remarkMath from 'remark-math'
import rehypeKatex from 'rehype-katex'
import { cn } from './utils'
import 'katex/dist/katex.min.css'

type MarkdownRendererProps = {
  children?: string
  classname?: string
  className?: string
}

export default function MarkdownRenderer({ children = '', classname, className }: MarkdownRendererProps) {
  return (
    <div className={cn('prose prose-sm max-w-none dark:prose-invert', classname, className)}>
      <ReactMarkdown remarkPlugins={[remarkGfm, remarkMath]} rehypePlugins={[rehypeKatex]}>
        {children}
      </ReactMarkdown>
    </div>
  )
}
