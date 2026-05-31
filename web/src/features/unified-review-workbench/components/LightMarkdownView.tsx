'use client'

import { parseLightMarkdownBlocks } from '@/features/unified-review-workbench/utils/lightMarkdown'

const HEADING_CLASS: Record<1 | 2 | 3, string> = {
  1: 'text-[15px] font-semibold text-primary',
  2: 'text-[13px] font-semibold text-primary',
  3: 'text-[12px] font-medium text-primary',
}

export function LightMarkdownView({ markdown, className = '' }: { markdown: string; className?: string }) {
  const blocks = parseLightMarkdownBlocks(markdown)
  if (!blocks.length) {
    return <p className="text-[11px] text-muted">暂无正文</p>
  }

  return (
    <div className={`space-y-3 text-[11px] leading-relaxed text-primary ${className}`.trim()}>
      {blocks.map((block, index) => {
        if (block.type === 'heading') {
          const Tag = block.level === 1 ? 'h2' : block.level === 2 ? 'h3' : 'h4'
          return (
            <Tag key={index} className={HEADING_CLASS[block.level]}>
              {block.text}
            </Tag>
          )
        }
        if (block.type === 'blockquote') {
          return (
            <blockquote
              key={index}
              className="border-l-2 border-primaryAccent/30 pl-3 text-muted italic"
            >
              {block.text}
            </blockquote>
          )
        }
        if (block.type === 'unordered_list' || block.type === 'ordered_list') {
          const ListTag = block.type === 'ordered_list' ? 'ol' : 'ul'
          return (
            <ListTag
              key={index}
              className={`space-y-1 pl-4 ${block.type === 'ordered_list' ? 'list-decimal' : 'list-disc'}`}
            >
              {block.items.map((item) => (
                <li key={item} className="text-primary">
                  {item}
                </li>
              ))}
            </ListTag>
          )
        }
        return (
          <p key={index} className="whitespace-pre-wrap text-primary">
            {block.text}
          </p>
        )
      })}
    </div>
  )
}

export default LightMarkdownView
