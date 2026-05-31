'use client'

import { useState } from 'react'
import { X } from 'lucide-react'
import type { ParsePreviewBlock } from '@/features/super-agent/types'

export default function BlockEditModal({
  block,
  draftText,
  onSave,
  onClose,
}: {
  block: ParsePreviewBlock
  draftText: string
  onSave: (text: string) => void
  onClose: () => void
}) {
  const [value, setValue] = useState(draftText)

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40 p-4">
      <div className="w-full max-w-xl rounded-xl border border-border/20 bg-background shadow-soft">
        <div className="flex items-center justify-between border-b border-border/10 px-4 py-3">
          <div>
            <div className="text-[12px] font-medium text-primary">编辑解析块</div>
            <div className="text-[10px] text-muted">
              {block.block_type}
              {block.page_hint ? ` · 第 ${block.page_hint} 页` : ''}
            </div>
          </div>
          <button type="button" onClick={onClose} className="rounded p-1 text-muted hover:bg-border/10">
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="p-4">
          <textarea
            value={value}
            onChange={(event) => setValue(event.target.value)}
            rows={10}
            className="w-full rounded-lg border border-border/20 bg-surface px-3 py-2 text-[12px] leading-relaxed text-primary outline-none focus:border-primaryAccent/40"
          />
          <p className="mt-2 text-[10px] text-muted">修改会同步更新 Markdown 与 JSON 中的 block content（仅本地 draft）。</p>
        </div>
        <div className="flex justify-end gap-2 border-t border-border/10 px-4 py-3">
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-border/20 px-3 py-1.5 text-[11px] text-primary"
          >
            取消
          </button>
          <button
            type="button"
            onClick={() => {
              onSave(value)
              onClose()
            }}
            className="rounded-md bg-brand px-3 py-1.5 text-[11px] font-medium text-white"
          >
            保存 draft
          </button>
        </div>
      </div>
    </div>
  )
}
