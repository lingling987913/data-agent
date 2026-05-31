'use client'

import { useCallback, useEffect } from 'react'
import { X } from 'lucide-react'
import ReviewPlusDocumentPackagePanel from '@/features/review-plus-v2/components/ReviewPlusDocumentPackagePanel'
import type {
  ReviewPlusGatekeepingResult,
  ReviewPlusMaterialItem,
  ReviewPlusParserType,
} from '@/features/review-plus-shared/types'

type Props = {
  open: boolean
  onClose: () => void
  materials: ReviewPlusMaterialItem[]
  gatekeeping: ReviewPlusGatekeepingResult | null
  parserType: ReviewPlusParserType
  uploading: boolean
  parseComplete?: boolean
  parsing?: boolean
  taskStatus?: string
  onParserTypeChange: (value: ReviewPlusParserType) => void
  onFilesSelected: (files: FileList | null, preferredRole?: string) => void
  onRoleChange: (material: ReviewPlusMaterialItem, role: string) => void
  onConfirmRole: (material: ReviewPlusMaterialItem) => void
  onReclassify: () => void
  onReparseMaterial: (material: ReviewPlusMaterialItem, parserType: ReviewPlusParserType) => void
  onReparseAll: (parserType: ReviewPlusParserType) => void
  onPreview: (payload: { title: string; content: string }) => void
  onRecheckGate: () => void
}

export default function ReviewPlusMaterialPackageModal({
  open,
  onClose,
  ...panelProps
}: Props) {
  const handleKey = useCallback(
    (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    },
    [onClose],
  )

  useEffect(() => {
    if (!open) return undefined
    document.addEventListener('keydown', handleKey)
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', handleKey)
      document.body.style.overflow = ''
    }
  }, [handleKey, open])

  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-[100] flex items-center justify-center p-3 sm:p-6"
      onClick={onClose}
      data-testid="review-plus-package-modal"
    >
      <div className="absolute inset-0 bg-black/40 backdrop-blur-sm" aria-hidden />

      <div
        className="relative flex max-h-[92vh] w-full max-w-5xl flex-col overflow-hidden rounded-2xl border border-border/20 bg-background shadow-warm"
        onClick={(event) => event.stopPropagation()}
        role="dialog"
        aria-modal="true"
        aria-labelledby="review-plus-package-modal-title"
      >
        <div className="flex shrink-0 items-center justify-between gap-3 border-b border-border/15 px-4 py-3 sm:px-5">
          <div className="min-w-0">
            <h2 id="review-plus-package-modal-title" className="text-[14px] font-medium text-primary">
              送审包
            </h2>
            <p className="mt-0.5 text-[10px] text-muted">查看材料清单、解析状态、角色与门禁；审查进行中可随时打开核对。</p>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="inline-flex size-9 shrink-0 items-center justify-center rounded-xl border border-border/25 text-muted transition-colors hover:border-brand/40 hover:text-primary"
            aria-label="关闭送审包"
            data-testid="review-plus-package-modal-close"
          >
            <X size={16} aria-hidden />
          </button>
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto">
          <ReviewPlusDocumentPackagePanel {...panelProps} />
        </div>
      </div>
    </div>
  )
}
