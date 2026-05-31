'use client'

import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode, type RefObject } from 'react'
import {
  AlertTriangle,
  ChevronLeft,
  ChevronRight,
  Download,
  FileText,
  Loader2,
  Pencil,
  RefreshCw,
  Upload,
} from 'lucide-react'
import MarkdownRenderer from '@aqua/ui-core/typography/MarkdownRenderer'
import { MATERIAL_ROLE_LABELS } from '@/features/review-plus-shared/types'
import { PROCESSING_MODE_LABELS } from '@/lib/aeroTerminology'
import { fetchSourceFileBlob } from '@/features/super-agent/api'
import type { MaterialParsePreviewItem, ParsePreviewBlock, ParsePreviewResponse } from '@/features/super-agent/types'
import PdfBlockOverlayViewer from '@/features/super-agent/components/PdfBlockOverlayViewer'
import BlockEditModal from '@/features/super-agent/components/BlockEditModal'
import LayoutBlockPane from '@/features/super-agent/components/LayoutBlockPane'
import {
  blockContentEdited,
  blockDisplayMarkdown,
  blockDoubleClickNavigation,
  buildMaterialJsonPreview,
  buildPdfViewerSrc,
  firstBlockPage,
  jsonBlockClickNavigation,
  applyCalibrationHighlightsToHtml,
  needsCalibrationReview,
  renderCalibrationHighlightedHtml,
  shouldRenderPreviewWithMarkdown,
  resolvePageCount,
  resolvePreviewBlocks,
  scrollJsonToBlock,
  scrollMarkdownToBlock,
  scrollMarkdownToPage,
  updateBlockContent,
} from '@/features/super-agent/utils/parsePreviewBlocks'
import { buildOfficePreview, type OfficePreviewResult } from '@/features/super-agent/utils/officePreview'
import {
  formatParseStatus,
  isImageFileName,
  isLegacyOfficeFileName,
  isOfficeFileName,
  isPdfFileName,
  isTextLikeFileName,
  PARSING_TIER_LABELS,
  resolveMineruBatchId,
  resolveOfficePreviewKind,
  shouldShowCapabilityFailure,
  shouldShowDegradedNotice,
  shouldShowPreviewWarnings,
  filterPreviewWarnings,
  isStaleParsePreview,
  isStaleParsePreviewItem,
} from '@/features/super-agent/utils/parsePreviewFormat'

interface UploadedFileRef {
  id: string
  file: File
}

interface ParsePreviewPanelProps {
  preview: ParsePreviewResponse | null
  files?: UploadedFileRef[]
  parseBusy?: boolean
  loading?: boolean
  parseProgress?: number
  parseLines?: string[]
  showManualStart?: boolean
  onStartParse?: () => void
  onReparse?: () => void
}

type ResultTab = 'markdown' | 'json'
type MarkdownViewMode = 'layout' | 'reading'

const MARKDOWN_PROSE =
  'prose-sm max-w-none [&_h1]:mb-2 [&_h1]:mt-3 [&_h1]:text-base [&_h1]:font-semibold [&_h1]:text-primary [&_h2]:mb-2 [&_h2]:mt-2 [&_h2]:text-sm [&_h2]:font-semibold [&_h2]:text-primary [&_h3]:mb-1 [&_h3]:mt-2 [&_h3]:text-sm [&_h3]:font-medium [&_h3]:text-primary [&_p]:my-2 [&_p]:text-[13px] [&_p]:leading-relaxed [&_p]:text-primary/90 [&_li]:text-[13px] [&_li]:text-primary/90 [&_ul]:my-2 [&_ol]:my-2 [&_table]:my-3 [&_table]:w-full [&_table]:border-collapse [&_table]:border [&_table]:border-border/25 [&_th]:border [&_th]:border-border/25 [&_th]:bg-surface/80 [&_th]:px-2.5 [&_th]:py-1.5 [&_th]:text-left [&_th]:text-[12px] [&_th]:font-medium [&_td]:border [&_td]:border-border/20 [&_td]:px-2.5 [&_td]:py-1.5 [&_td]:text-[12px] [&_code]:rounded [&_code]:bg-primaryAccent/5 [&_code]:px-1 [&_code]:text-primaryAccent'

/** 左右对照滚动视口统一高度（含各自顶栏：页码 / Tab） */
const COMPARE_VIEWPORT_CLASS = 'flex h-[min(72vh,720px)] min-h-[420px] flex-col overflow-hidden'

function parseStatusBadgeClass(tone: 'ok' | 'warn' | 'fail'): string {
  if (tone === 'ok') return 'border-emerald-200/80 bg-emerald-50 text-emerald-700'
  if (tone === 'warn') return 'border-amber-200/80 bg-amber-50 text-amber-700'
  return 'border-destructive/25 bg-destructive/10 text-destructive'
}

function useSourceObjectUrl(sourceFile?: File, sourceDownloadUrl?: string) {
  const [objectUrl, setObjectUrl] = useState<string | null>(null)
  const [arrayBuffer, setArrayBuffer] = useState<ArrayBuffer | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    let cancelled = false
    let createdUrl: string | null = null

    const applyUrl = (url: string | null) => {
      if (cancelled) {
        if (url) URL.revokeObjectURL(url)
        return
      }
      setObjectUrl(url)
    }

    const applyBuffer = (buffer: ArrayBuffer | null) => {
      if (!cancelled) setArrayBuffer(buffer)
    }

    // Prefer server source (may include orientation-normalized PDF) over local upload blob.
    if (sourceDownloadUrl) {
      setLoading(true)
      setError('')
      void fetchSourceFileBlob(sourceDownloadUrl)
        .then(async (blob) => {
          if (cancelled) return
          createdUrl = URL.createObjectURL(blob)
          applyUrl(createdUrl)
          applyBuffer(await blob.arrayBuffer())
        })
        .catch((err) => {
          if (cancelled) return
          applyUrl(null)
          applyBuffer(null)
          setError(err instanceof Error ? err.message : '原文加载失败')
        })
        .finally(() => {
          if (!cancelled) setLoading(false)
        })

      return () => {
        cancelled = true
        if (createdUrl) URL.revokeObjectURL(createdUrl)
      }
    }

    if (sourceFile) {
      createdUrl = URL.createObjectURL(sourceFile)
      applyUrl(createdUrl)
      setLoading(true)
      setError('')
      void sourceFile
        .arrayBuffer()
        .then((buffer) => {
          applyBuffer(buffer)
        })
        .catch((err) => {
          if (cancelled) return
          applyBuffer(null)
          setError(err instanceof Error ? err.message : '原文加载失败')
        })
        .finally(() => {
          if (!cancelled) setLoading(false)
        })
      return () => {
        cancelled = true
        if (createdUrl) URL.revokeObjectURL(createdUrl)
      }
    }

    applyUrl(null)
    applyBuffer(null)
    setLoading(false)
    setError('')
    return () => {
      cancelled = true
    }
  }, [sourceDownloadUrl, sourceFile])

  return { objectUrl, arrayBuffer, loading, error }
}

const OFFICE_WORD_PROSE =
  'text-[11px] leading-relaxed text-primary/90 [&_.docx-preview-page]:mb-4 [&_.docx-preview-page]:min-h-[360px] [&_.docx-preview-page]:rounded-md [&_.docx-preview-page]:border [&_.docx-preview-page]:border-border/15 [&_.docx-preview-page]:bg-white [&_.docx-preview-page]:px-6 [&_.docx-preview-page]:py-5 [&_.docx-preview-page]:shadow-sm [&_.docx-preview-page:last-child]:mb-0 [&_p]:my-2 [&_table]:my-3 [&_table]:w-full [&_table]:border-collapse [&_table]:border [&_table]:border-border/25 [&_th]:border [&_th]:border-border/25 [&_th]:bg-surface/80 [&_th]:px-2.5 [&_th]:py-1.5 [&_th]:text-left [&_th]:text-[12px] [&_td]:border [&_td]:border-border/20 [&_td]:px-2.5 [&_td]:py-1.5 [&_td]:text-[12px]'

const OFFICE_SHEET_PROSE =
  '[&_table]:w-full [&_table]:border-collapse [&_table]:border [&_table]:border-border/25 [&_th]:border [&_th]:border-border/25 [&_th]:bg-surface/80 [&_th]:px-2.5 [&_th]:py-1.5 [&_th]:text-left [&_th]:text-[12px] [&_td]:border [&_td]:border-border/20 [&_td]:px-2.5 [&_td]:py-1.5 [&_td]:text-[12px]'

function resolveOfficePageLabel(
  preview: OfficePreviewResult,
  currentPage: number,
  pageCount: number,
): string {
  if (preview.kind === 'word') return '原文件 · 全文'
  if (preview.kind === 'excel') {
    const sheet = preview.sheets?.[currentPage - 1]
    const sheetName = sheet?.name ? ` · ${sheet.name}` : ''
    return `原文件 · 工作表 ${currentPage} / ${pageCount}${sheetName}`
  }
  return `原文件 · 第 ${currentPage} / ${pageCount} 页`
}

function UnsupportedDocumentPreview({
  message,
  downloadUrl,
  fileName,
}: {
  message: string
  downloadUrl?: string | null
  fileName: string
}) {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-3 px-4 text-center">
      <p className="text-[11px] text-muted">{message}</p>
      {downloadUrl ? (
        <a
          href={downloadUrl}
          download={fileName}
          className="inline-flex items-center gap-1.5 rounded-md border border-border/20 bg-background px-3 py-1.5 text-[11px] font-medium text-primary hover:bg-surface/80"
        >
          <Download className="h-3.5 w-3.5" aria-hidden />
          下载原文件
        </a>
      ) : null}
    </div>
  )
}

function OfficeDocumentPreview({
  preview,
  currentPage,
}: {
  preview: OfficePreviewResult
  currentPage: number
}) {
  if (preview.kind === 'word' && preview.html) {
    return (
      <div className={`min-h-0 flex-1 overflow-y-auto px-3 py-2 ${OFFICE_WORD_PROSE}`}>
        <div dangerouslySetInnerHTML={{ __html: preview.html }} />
      </div>
    )
  }

  if (preview.kind === 'excel') {
    const sheet = preview.sheets?.[Math.max(currentPage - 1, 0)]
    if (!sheet?.html) {
      return (
        <div className="flex min-h-0 flex-1 items-center justify-center px-4 text-center text-[11px] text-muted">
          未读取到可预览的工作表内容。
        </div>
      )
    }
    return (
      <div className={`min-h-0 flex-1 overflow-y-auto px-2 py-2 text-[11px] text-primary/90 ${OFFICE_SHEET_PROSE}`}>
        <div dangerouslySetInnerHTML={{ __html: sheet.html }} />
      </div>
    )
  }

  const slide = preview.slides?.[Math.max(currentPage - 1, 0)]
  if (!slide) {
    return (
      <div className="flex min-h-0 flex-1 items-center justify-center px-4 text-center text-[11px] text-muted">
        未读取到可预览的幻灯片内容。
      </div>
    )
  }

  return (
    <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4">
      <div className="mx-auto max-w-xl rounded-lg border border-border/15 bg-surface/40 p-4 shadow-sm">
        <div className="mb-3 text-[10px] font-medium uppercase tracking-wide text-muted">Slide {slide.index}</div>
        {slide.lines.length ? (
          <div className="space-y-2">
            {slide.lines.map((line, index) => (
              <p key={`${slide.index}-${index}`} className="text-[12px] leading-relaxed text-primary/90">
                {line}
              </p>
            ))}
          </div>
        ) : (
          <p className="text-[11px] text-muted">该页未提取到文本内容（可能仅含图片或图表）。</p>
        )}
      </div>
    </div>
  )
}

function hasBboxOverlayData(blocks: ParsePreviewBlock[]): boolean {
  return blocks.some((block) => Array.isArray(block.bbox) && block.bbox.length >= 4)
}

function DocumentPageViewer({
  fileName,
  sourceFile,
  sourceDownloadUrl,
  sharedSource,
  pageCount,
  currentPage,
  blocks = [],
  activeBlockId,
  onPageChange,
  onBlockSelect,
}: {
  fileName: string
  sourceFile?: File
  sourceDownloadUrl?: string
  sharedSource?: ReturnType<typeof useSourceObjectUrl>
  pageCount: number
  currentPage: number
  blocks?: ParsePreviewBlock[]
  activeBlockId?: string | null
  onPageChange: (page: number) => void
  onBlockSelect?: (blockId: string) => void
}) {
  const internalSource = useSourceObjectUrl(
    sharedSource ? undefined : sourceFile,
    sharedSource ? undefined : sourceDownloadUrl,
  )
  const { objectUrl, arrayBuffer, loading, error } = sharedSource ?? internalSource
  const [textContent, setTextContent] = useState('')
  const [officePreview, setOfficePreview] = useState<OfficePreviewResult | null>(null)
  const [officePreviewError, setOfficePreviewError] = useState('')
  const [officePreviewLoading, setOfficePreviewLoading] = useState(false)

  const officeKind = resolveOfficePreviewKind(fileName)
  const legacyOffice = isOfficeFileName(fileName) && isLegacyOfficeFileName(fileName)

  useEffect(() => {
    if (!sourceFile || !isTextLikeFileName(sourceFile.name)) {
      setTextContent('')
      return
    }
    let cancelled = false
    void sourceFile.text().then((text) => {
      if (!cancelled) setTextContent(text)
    })
    return () => {
      cancelled = true
    }
  }, [sourceFile])

  useEffect(() => {
    if (!officeKind || !arrayBuffer) {
      setOfficePreview(null)
      setOfficePreviewError('')
      setOfficePreviewLoading(false)
      return
    }

    let cancelled = false
    setOfficePreviewLoading(true)
    setOfficePreviewError('')
    void buildOfficePreview(fileName, arrayBuffer)
      .then((preview) => {
        if (cancelled) return
        setOfficePreview(preview)
      })
      .catch((err) => {
        if (cancelled) return
        setOfficePreview(null)
        setOfficePreviewError(err instanceof Error ? err.message : 'Office 预览加载失败')
      })
      .finally(() => {
        if (!cancelled) setOfficePreviewLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [arrayBuffer, fileName, officeKind])

  const effectivePageCount = officePreview?.pageCount ?? pageCount
  const safePage = Math.min(Math.max(currentPage, 1), Math.max(effectivePageCount, 1))
  const viewerSrc = objectUrl && isPdfFileName(fileName) ? buildPdfViewerSrc(objectUrl, safePage) : objectUrl
  const useBboxOverlay =
    Boolean(objectUrl && isPdfFileName(fileName) && hasBboxOverlayData(blocks) && onBlockSelect)
  const showOfficePagination = Boolean(officePreview && officePreview.pageCount > 1)
  const pageLabel = officePreview
    ? resolveOfficePageLabel(officePreview, safePage, Math.max(effectivePageCount, 1))
    : `原文件 · 第 ${safePage} / ${Math.max(effectivePageCount, 1)} 页`

  return (
    <div className={`${COMPARE_VIEWPORT_CLASS} rounded-lg border border-border/10 bg-background`}>
      <div className="flex items-center justify-between gap-2 border-b border-border/10 px-3 py-2">
        <div className="min-w-0 truncate text-[10px] font-medium text-muted">{pageLabel}</div>
        {showOfficePagination || (!officePreview && effectivePageCount > 1) ? (
          <div className="flex items-center gap-1">
            <button
              type="button"
              disabled={safePage <= 1}
              onClick={() => onPageChange(safePage - 1)}
              className="rounded border border-border/15 p-1 text-muted disabled:opacity-40"
              aria-label="上一页"
            >
              <ChevronLeft className="h-3.5 w-3.5" />
            </button>
            <input
              type="number"
              min={1}
              max={Math.max(effectivePageCount, 1)}
              value={safePage}
              onChange={(event) => {
                const next = Number(event.target.value)
                if (Number.isFinite(next)) onPageChange(next)
              }}
              className="w-12 rounded border border-border/15 bg-surface px-1 py-0.5 text-center text-[10px] text-primary"
            />
            <button
              type="button"
              disabled={safePage >= Math.max(effectivePageCount, 1)}
              onClick={() => onPageChange(safePage + 1)}
              className="rounded border border-border/15 p-1 text-muted disabled:opacity-40"
              aria-label="下一页"
            >
              <ChevronRight className="h-3.5 w-3.5" />
            </button>
          </div>
        ) : null}
      </div>

      <div className="relative flex min-h-0 flex-1 flex-col overflow-auto">
        {loading || officePreviewLoading ? (
          <div className="flex min-h-0 flex-1 items-center justify-center text-[11px] text-muted">正在加载原文…</div>
        ) : error ? (
          <div className="flex min-h-0 flex-1 items-center justify-center px-4 text-center text-[11px] text-destructive">{error}</div>
        ) : officePreviewError ? (
          <UnsupportedDocumentPreview
            message={`Office 预览失败：${officePreviewError}`}
            downloadUrl={objectUrl}
            fileName={fileName}
          />
        ) : officePreview ? (
          <OfficeDocumentPreview preview={officePreview} currentPage={safePage} />
        ) : legacyOffice ? (
          <UnsupportedDocumentPreview
            message="暂不支持旧版 Office 格式（.doc / .ppt）在线预览，请下载原文件查看。"
            downloadUrl={objectUrl}
            fileName={fileName}
          />
        ) : useBboxOverlay && objectUrl ? (
          <PdfBlockOverlayViewer
            pdfUrl={objectUrl}
            fileName={fileName}
            pageCount={pageCount}
            currentPage={safePage}
            blocks={blocks}
            activeBlockId={activeBlockId ?? null}
            onPageChange={onPageChange}
            onBlockSelect={onBlockSelect!}
          />
        ) : viewerSrc && isPdfFileName(fileName) ? (
          <iframe title={`${fileName} 第 ${safePage} 页`} src={viewerSrc} className="h-full w-full bg-background" />
        ) : objectUrl && isImageFileName(fileName) ? (
          <div className="flex h-full items-center justify-center p-4">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src={objectUrl} alt={fileName} className="max-h-full max-w-full object-contain" />
          </div>
        ) : sourceFile && isTextLikeFileName(sourceFile.name) && textContent ? (
          <pre className="h-full overflow-auto whitespace-pre-wrap px-3 py-2 text-[11px] leading-relaxed text-primary/80">
            {textContent}
          </pre>
        ) : (
          <UnsupportedDocumentPreview
            message={
              sourceFile || sourceDownloadUrl
                ? '暂不支持该格式的分页预览，请下载原文件或查看右侧解析结果。'
                : '材料已上传至服务端，刷新后可通过下载链接预览原文。'
            }
            downloadUrl={objectUrl}
            fileName={fileName}
          />
        )}
      </div>
    </div>
  )
}

function BlockMarkdownPane({
  blocks,
  originalBlocks,
  activePage,
  activeBlockId,
  onBlockEdit,
  onBlockActivatePage,
  onBlockDoubleClick,
}: {
  blocks: ParsePreviewBlock[]
  originalBlocks: ParsePreviewBlock[]
  activePage: number
  activeBlockId: string | null
  onBlockEdit: (blockId: string, text: string) => void
  onBlockActivatePage: (blockId: string, page: number) => void
  onBlockDoubleClick: (blockId: string) => void
}) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [editingBlock, setEditingBlock] = useState<ParsePreviewBlock | null>(null)

  const originalById = useMemo(() => {
    const map = new Map<string, ParsePreviewBlock>()
    for (const block of originalBlocks) {
      map.set(block.id, block)
    }
    return map
  }, [originalBlocks])

  useEffect(() => {
    scrollMarkdownToPage(containerRef.current, activePage)
  }, [activePage])

  useEffect(() => {
    if (activeBlockId) {
      scrollMarkdownToBlock(containerRef.current, activeBlockId)
    }
  }, [activeBlockId, blocks])

  if (!blocks.length) {
    return (
      <div className="flex h-full min-h-0 items-center justify-center px-4 text-center text-[12px] text-muted">
        未提取到可预览正文。
      </div>
    )
  }

  return (
    <>
      <div ref={containerRef} className="h-full min-h-0 overflow-auto px-1 py-1">
        <div className="space-y-3">
          {blocks.map((block) => {
            const blockId = block.id
            const pageHint = block.page_hint ?? 1
            const markdown = blockDisplayMarkdown(block)
            const isHtmlBlock = /^\s*<table[\s>]/i.test(markdown)
            const useMarkdownForCalibration = shouldRenderPreviewWithMarkdown(block, markdown)
            const original = originalById.get(blockId)
            const isEdited = original ? blockContentEdited(original, block) : false
            const isActive = activeBlockId === blockId
            return (
              <div
                key={blockId}
                data-block-id={blockId}
                data-page-hint={pageHint}
                title="双击跳转 JSON · 点击铅笔编辑"
                onDoubleClick={(event) => {
                  event.preventDefault()
                  onBlockDoubleClick(blockId)
                }}
                onClick={() => onBlockActivatePage(blockId, pageHint)}
                className={`group cursor-pointer rounded-md px-2 py-1.5 transition hover:bg-primaryAccent/5 ${
                  isActive
                    ? 'bg-amber-50 ring-1 ring-amber-300'
                    : pageHint === activePage
                      ? 'bg-primaryAccent/5 ring-1 ring-primaryAccent/20'
                      : ''
                }`}
              >
                <div className="mb-1 flex items-center gap-2">
                  {isEdited ? (
                    <span className="text-[10px] font-medium text-primaryAccent">已编辑</span>
                  ) : null}
                  {block.calibrated ? (
                    <span className="rounded border border-amber-200 bg-amber-50 px-1.5 py-0.5 text-[10px] font-medium text-amber-700">
                      已应用校准建议
                    </span>
                  ) : block.needs_calibration_review || needsCalibrationReview(block) ? (
                    <span className="rounded border border-red-200 bg-red-50 px-1.5 py-0.5 text-[10px] font-medium text-red-700">
                      需人工复核
                    </span>
                  ) : null}
                  <button
                    type="button"
                    title="编辑此块"
                    onClick={(event) => {
                      event.stopPropagation()
                      setEditingBlock(block)
                    }}
                    className="ml-auto rounded p-0.5 text-muted opacity-0 transition hover:bg-border/10 group-hover:opacity-100"
                    aria-label="编辑此块"
                  >
                    <Pencil className="h-3 w-3" aria-hidden />
                  </button>
                </div>
                {markdown ? (
                  <>
                    {block.calibrated || block.needs_calibration_review || needsCalibrationReview(block) ? (
                      useMarkdownForCalibration && !isHtmlBlock ? (
                        <MarkdownRenderer className={MARKDOWN_PROSE}>{markdown}</MarkdownRenderer>
                      ) : (
                        <div
                          className={MARKDOWN_PROSE}
                          dangerouslySetInnerHTML={{
                            __html: isHtmlBlock
                              ? applyCalibrationHighlightsToHtml(block, markdown)
                              : renderCalibrationHighlightedHtml(block, markdown),
                          }}
                        />
                      )
                    ) : (
                      <MarkdownRenderer className={MARKDOWN_PROSE}>{markdown}</MarkdownRenderer>
                    )}
                    {block.calibrated && block.original_markdown ? (
                      <details className="mt-2 rounded-md border border-border/20 bg-surface/60 px-2 py-1 text-[10px] text-muted">
                        <summary className="cursor-pointer font-medium text-amber-700">查看校准前原文</summary>
                        <pre className="mt-1 whitespace-pre-wrap text-[10px] leading-relaxed">
                          {block.original_markdown}
                        </pre>
                      </details>
                    ) : null}
                  </>
                ) : (
                  <p className="text-[12px] text-muted">（空块）</p>
                )}
              </div>
            )
          })}
        </div>
      </div>
      {editingBlock ? (
        <BlockEditModal
          block={editingBlock}
          draftText={blockDisplayMarkdown(editingBlock)}
          onSave={(text) => onBlockEdit(editingBlock.id, text)}
          onClose={() => setEditingBlock(null)}
        />
      ) : null}
    </>
  )
}

function JsonResultPane({
  payload,
  activeBlockId,
  onBlockClick,
  containerRef,
}: {
  payload: Record<string, unknown>
  activeBlockId: string | null
  onBlockClick: (blockId: string) => void
  containerRef: RefObject<HTMLDivElement | null>
}) {
  const blocks = Array.isArray(payload.blocks) ? (payload.blocks as ParsePreviewBlock[]) : []
  const { blocks: _blocks, ...rest } = payload
  const prefix = JSON.stringify({ ...rest, blocks: null }, null, 2).replace('"blocks": null', '"blocks": [')

  return (
    <div ref={containerRef} className="h-full min-h-0 overflow-auto px-3 py-2 text-[11px] leading-relaxed text-primary/85">
      <pre className="whitespace-pre-wrap">{prefix}</pre>
      {blocks.map((block, index) => {
        const blockId = block.id || `block-${index}`
        const isActive = activeBlockId === blockId
        return (
          <pre
            key={blockId}
            data-json-block-id={blockId}
            role="button"
            tabIndex={0}
            onClick={() => onBlockClick(blockId)}
            onKeyDown={(event) => {
              if (event.key === 'Enter' || event.key === ' ') {
                event.preventDefault()
                onBlockClick(blockId)
              }
            }}
            className={`my-0.5 cursor-pointer whitespace-pre-wrap rounded-md px-1 py-0.5 transition ${
              isActive ? 'bg-amber-100 ring-1 ring-amber-300' : 'hover:bg-surface/80'
            }`}
          >
            {JSON.stringify(block, null, 2)}
            {index < blocks.length - 1 ? ',' : ''}
          </pre>
        )
      })}
      <pre className="whitespace-pre-wrap">{']'}</pre>
      <pre className="whitespace-pre-wrap">{'}'}</pre>
    </div>
  )
}

function StatDivider() {
  return <span className="mx-2 text-border/40">|</span>
}

function ParseResultCard({
  item,
  preview,
  blocks,
  originalBlocks,
  pageCount,
  resultTab,
  onResultTabChange,
  markdownViewMode,
  onMarkdownViewModeChange,
  hasLayoutData,
  activeBlockId,
  currentPage,
  onBlockEdit,
  onBlockActivatePage,
  onBlockDoubleClick,
  onJsonBlockClick,
  jsonPayload,
  jsonContainerRef,
  pdfPageUrl,
  compareLeftPane,
}: {
  item: MaterialParsePreviewItem
  preview: ParsePreviewResponse
  blocks: ParsePreviewBlock[]
  originalBlocks: ParsePreviewBlock[]
  pageCount: number
  resultTab: ResultTab
  onResultTabChange: (tab: ResultTab) => void
  markdownViewMode: MarkdownViewMode
  onMarkdownViewModeChange: (mode: MarkdownViewMode) => void
  hasLayoutData: boolean
  activeBlockId: string | null
  currentPage: number
  onBlockEdit: (blockId: string, text: string) => void
  onBlockActivatePage: (blockId: string, page: number) => void
  onBlockDoubleClick: (blockId: string) => void
  onJsonBlockClick: (blockId: string) => void
  jsonPayload: Record<string, unknown>
  jsonContainerRef: RefObject<HTMLDivElement | null>
  pdfPageUrl?: string | null
  compareLeftPane?: ReactNode
}) {
  const status = formatParseStatus(item.parse_status)
  const irStats = item.document_ir_stats || {}
  const batchId = resolveMineruBatchId(item, preview)
  const showCapabilityFailure = shouldShowCapabilityFailure(item)
  const showDegraded = shouldShowDegradedNotice(item)
  const meaningfulWarnings = filterPreviewWarnings(item.warnings)
  const showWarnings = shouldShowPreviewWarnings(item)

  return (
    <article
      className="overflow-hidden rounded-xl border border-[#d5e0ea]/90 bg-[#eef3f8] shadow-sm"
      data-testid="parse-result-card"
    >
      <header className="px-5 pt-5 pb-3">
        <div className="flex items-start justify-between gap-3">
          <div className="flex min-w-0 items-center gap-2.5">
            <FileText className="h-5 w-5 shrink-0 text-primaryAccent" aria-hidden />
            <h3 className="truncate text-[14px] font-semibold text-primary">{item.file_name}</h3>
          </div>
          <span
            className={`shrink-0 rounded-full border px-2.5 py-0.5 text-[11px] font-medium ${parseStatusBadgeClass(status.tone)}`}
          >
            {status.label}
          </span>
        </div>

        <div className="mt-3 flex flex-wrap gap-2">
          <span className="rounded-md border border-border/10 bg-surface/80 px-2 py-0.5 text-[11px] text-muted">
            角色：{MATERIAL_ROLE_LABELS[item.role] || item.role}
          </span>
          <span className="rounded-md border border-border/10 bg-surface/80 px-2 py-0.5 text-[11px] text-muted">
            解析层级：{PARSING_TIER_LABELS[item.parsing_tier] || item.parsing_tier}
          </span>
          <span className="rounded-md border border-border/10 bg-surface/80 px-2 py-0.5 text-[11px] text-muted">
            解析器：{item.parser_name || item.parser_type}
          </span>
        </div>
      </header>

      <div className="space-y-1.5 px-5 pb-3 text-[11px] text-muted">
        <div className="flex flex-wrap items-center gap-y-1">
          <span>正文长度: {item.content_length.toLocaleString()} 字</span>
          <StatDivider />
          <span>有效行数: {item.line_count.toLocaleString()}</span>
          <StatDivider />
          <span>处理模式: {PROCESSING_MODE_LABELS[item.processing_mode] || item.processing_mode}</span>
        </div>
        <div className="flex flex-wrap items-center gap-y-1">
          <span>Layout: {irStats.layout_block_count ?? 0}</span>
          <StatDivider />
          <span>表格: {irStats.table_element_count ?? 0}</span>
          <StatDivider />
          <span>图片: {irStats.visual_element_count ?? 0}</span>
          <StatDivider />
          <span>流程: {irStats.graph_element_count ?? 0}</span>
          <StatDivider />
          <span>图表: {irStats.chart_element_count ?? 0}</span>
          {pageCount > 1 ? (
            <>
              <StatDivider />
              <span>页数: {pageCount}</span>
            </>
          ) : null}
        </div>
      </div>

      {showCapabilityFailure ? (
        <div className="mx-5 mb-3 flex items-start gap-2 rounded-lg border border-amber-200/80 bg-amber-50 px-3 py-2.5 text-[11px] text-amber-800">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
          <span>能力未通过：该文件需要人工复核或补充解析后端。</span>
        </div>
      ) : null}
      {showDegraded ? (
        <div className="mx-5 mb-3 flex items-start gap-2 rounded-lg border border-amber-200/80 bg-amber-50 px-3 py-2.5 text-[11px] text-amber-800">
          <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
          <span>降级解析：结果可用性有限，建议核对关键表格与图表。</span>
        </div>
      ) : null}
      {showWarnings ? (
        <div className="mx-5 mb-3 space-y-1 rounded-lg border border-amber-200/60 bg-amber-50/60 px-3 py-2 text-[11px] text-amber-800">
          {meaningfulWarnings.slice(0, 3).map((warning) => (
            <p key={warning}>{warning}</p>
          ))}
        </div>
      ) : null}

      <div
        className={`mx-3 mb-4 grid items-stretch gap-3 ${compareLeftPane ? 'md:grid-cols-2' : ''}`}
        data-testid={compareLeftPane ? 'parse-preview-compare-row' : undefined}
      >
        {compareLeftPane ? (
          <div className="min-h-0" data-testid="parse-preview-pdf-pane">
            {compareLeftPane}
          </div>
        ) : null}

        <div
          className={`min-h-0 rounded-lg border border-border/20 bg-white shadow-[inset_0_1px_0_rgba(255,255,255,0.6)] ${COMPARE_VIEWPORT_CLASS}`}
          data-testid="parse-preview-result-viewport"
        >
          <div className="flex shrink-0 items-center justify-between gap-2 border-b border-border/10 px-3 py-2">
            <div className="flex flex-wrap items-center gap-2">
              <div className="inline-flex rounded-md border border-border/10 bg-surface/50 p-0.5">
                {(['markdown', 'json'] as const).map((tab) => {
                  const active = resultTab === tab
                  return (
                    <button
                      key={tab}
                      type="button"
                      onClick={() => onResultTabChange(tab)}
                      className={`rounded px-2.5 py-1 text-[10px] font-medium transition ${
                        active ? 'bg-white text-primary shadow-sm' : 'text-muted hover:text-primary'
                      }`}
                    >
                      {tab === 'markdown' ? 'Markdown' : 'JSON'}
                    </button>
                  )
                })}
              </div>
              {resultTab === 'markdown' && hasLayoutData ? (
                <div className="inline-flex rounded-md border border-border/10 bg-surface/50 p-0.5">
                  {([
                    { mode: 'layout' as const, label: '版面视图' },
                    { mode: 'reading' as const, label: '阅读序' },
                  ]).map(({ mode, label }) => {
                    const active = markdownViewMode === mode
                    return (
                      <button
                        key={mode}
                        type="button"
                        onClick={() => onMarkdownViewModeChange(mode)}
                        className={`rounded px-2.5 py-1 text-[10px] font-medium transition ${
                          active ? 'bg-white text-primary shadow-sm' : 'text-muted hover:text-primary'
                        }`}
                      >
                        {label}
                      </button>
                    )
                  })}
                </div>
              ) : null}
            </div>
            {resultTab === 'markdown' ? (
              <span className="text-[10px] text-muted">
                {markdownViewMode === 'layout' && hasLayoutData
                  ? '按 bbox 复原版面 · 点击原文或文字块后高亮联动'
                  : '双击块跳转 JSON · 铅笔编辑 · 左页联动滚动'}
              </span>
            ) : (
              <span className="text-[10px] text-muted">点击 block 行跳转 Markdown</span>
            )}
          </div>

          <div className="min-h-0 flex-1 overflow-auto bg-white">
            {resultTab === 'markdown' ? (
              markdownViewMode === 'layout' && hasLayoutData ? (
                <LayoutBlockPane
                  blocks={blocks}
                  originalBlocks={originalBlocks}
                  activePage={currentPage}
                  activeBlockId={activeBlockId}
                  pdfPageUrl={pdfPageUrl}
                  onBlockEdit={onBlockEdit}
                  onBlockActivatePage={onBlockActivatePage}
                  onBlockDoubleClick={onBlockDoubleClick}
                />
              ) : (
                <BlockMarkdownPane
                  blocks={blocks}
                  originalBlocks={originalBlocks}
                  activePage={currentPage}
                  activeBlockId={activeBlockId}
                  onBlockEdit={onBlockEdit}
                  onBlockActivatePage={onBlockActivatePage}
                  onBlockDoubleClick={onBlockDoubleClick}
                />
              )
            ) : (
              <JsonResultPane
                payload={jsonPayload}
                activeBlockId={activeBlockId}
                onBlockClick={onJsonBlockClick}
                containerRef={jsonContainerRef}
              />
            )}
          </div>
        </div>
      </div>

      {item.content_markdown_truncated ? (
        <p className="mx-5 -mt-2 mb-3 text-[10px] text-muted">
          Markdown 预览已截断，完整内容请以后端解析 artifact 为准。
        </p>
      ) : null}

      {batchId ? (
        <footer className="border-t border-[#d5e0ea]/80 bg-[#eef3f8] px-5 py-2.5 text-[10px] text-orange-500">
          MinerU extract batch_id={batchId}
        </footer>
      ) : item.parser_name ? (
        <footer className="border-t border-[#d5e0ea]/80 bg-[#eef3f8] px-5 py-2.5 text-[10px] text-muted">
          解析器：{item.parser_name}
        </footer>
      ) : null}
    </article>
  )
}

function ParseMaterialCompareView({
  item,
  preview,
  sourceFile,
}: {
  item: MaterialParsePreviewItem
  preview: ParsePreviewResponse
  sourceFile?: File
}) {
  const [resultTab, setResultTab] = useState<ResultTab>('markdown')
  const [markdownViewMode, setMarkdownViewMode] = useState<MarkdownViewMode>('layout')
  const [currentPage, setCurrentPage] = useState(1)
  const [activeBlockId, setActiveBlockId] = useState<string | null>(null)
  const jsonContainerRef = useRef<HTMLDivElement>(null)

  const originalBlocks = useMemo(() => resolvePreviewBlocks(item), [item])
  const [blocks, setBlocks] = useState<ParsePreviewBlock[]>(originalBlocks)
  const hasLayoutData = useMemo(() => hasBboxOverlayData(blocks), [blocks])

  const pageCount = useMemo(() => resolvePageCount(item, blocks), [item, blocks])
  const jsonPayload = useMemo(() => buildMaterialJsonPreview(item, preview, blocks), [item, preview, blocks])
  const sharedSource = useSourceObjectUrl(sourceFile, item.source_download_url)
  const pdfPageUrl = isPdfFileName(item.file_name) ? sharedSource.objectUrl : null

  useEffect(() => {
    const nextBlocks = resolvePreviewBlocks(item)
    setBlocks(nextBlocks)
    setCurrentPage(firstBlockPage(nextBlocks))
    setActiveBlockId(null)
    setResultTab('markdown')
    setMarkdownViewMode(hasBboxOverlayData(nextBlocks) ? 'layout' : 'reading')
  }, [item.file_name, item])

  useEffect(() => {
    if (resultTab === 'json' && activeBlockId) {
      scrollJsonToBlock(jsonContainerRef.current, activeBlockId)
    }
  }, [resultTab, activeBlockId, blocks])

  const handlePageChange = useCallback((page: number) => {
    const next = Math.min(Math.max(page, 1), Math.max(pageCount, 1))
    setCurrentPage(next)
  }, [pageCount])

  const handleBlockEdit = useCallback((blockId: string, text: string) => {
    setBlocks((current) => updateBlockContent(current, blockId, text))
    setActiveBlockId(blockId)
  }, [])

  const handleBlockSelect = useCallback(
    (blockId: string) => {
      setActiveBlockId(blockId)
      const block = blocks.find((item) => item.id === blockId)
      if (block?.page_hint) {
        setCurrentPage(block.page_hint)
      }
    },
    [blocks],
  )

  const handleMarkdownBlockClick = useCallback(
    (blockId: string, page: number) => {
      setActiveBlockId(blockId)
      handlePageChange(page)
    },
    [handlePageChange],
  )

  const handleBlockDoubleClick = useCallback((blockId: string) => {
    const { nextTab, activeBlockId: nextActiveBlockId } = blockDoubleClickNavigation(blockId)
    setActiveBlockId(nextActiveBlockId)
    setResultTab(nextTab)
  }, [])

  const handleJsonBlockClick = useCallback((blockId: string) => {
    const { nextTab, activeBlockId: nextActiveBlockId } = jsonBlockClickNavigation(blockId)
    setActiveBlockId(nextActiveBlockId)
    setResultTab(nextTab)
  }, [])

  return (
    <div className="rounded-xl bg-surface/40 p-2 sm:p-3" data-testid="parse-preview-material-compare">
      <ParseResultCard
        item={item}
        preview={preview}
        blocks={blocks}
        originalBlocks={originalBlocks}
        pageCount={pageCount}
        resultTab={resultTab}
        onResultTabChange={setResultTab}
        markdownViewMode={markdownViewMode}
        onMarkdownViewModeChange={setMarkdownViewMode}
        hasLayoutData={hasLayoutData}
        activeBlockId={activeBlockId}
        currentPage={currentPage}
        onBlockEdit={handleBlockEdit}
        onBlockActivatePage={handleMarkdownBlockClick}
        onBlockDoubleClick={handleBlockDoubleClick}
        onJsonBlockClick={handleJsonBlockClick}
        jsonPayload={jsonPayload}
        jsonContainerRef={jsonContainerRef}
        pdfPageUrl={pdfPageUrl}
        compareLeftPane={
          <DocumentPageViewer
            fileName={item.file_name}
            sourceFile={sourceFile}
            sourceDownloadUrl={item.source_download_url}
            sharedSource={sharedSource}
            pageCount={pageCount}
            currentPage={currentPage}
            blocks={blocks}
            activeBlockId={activeBlockId}
            onPageChange={handlePageChange}
            onBlockSelect={handleBlockSelect}
          />
        }
      />
    </div>
  )
}

function ParsePreviewLoadingState({
  parseProgress,
  parseLines,
  parseBusy,
  showManualStart,
  onStartParse,
  variant,
}: {
  parseProgress: number
  parseLines: string[]
  parseBusy: boolean
  showManualStart: boolean
  onStartParse?: () => void
  variant: 'loading' | 'idle'
}) {
  const Icon = variant === 'loading' ? Upload : FileText
  const title = variant === 'loading' ? '正在解析材料…' : '准备解析材料'
  const subtitle =
    variant === 'loading'
      ? null
      : '解析尚未开始或上次失败，可手动触发分级解析预览。'

  return (
    <div
      className="flex flex-1 flex-col items-center justify-center py-8"
      data-testid="parse-preview-panel-loading"
    >
      <Icon className={`h-10 w-10 text-primaryAccent ${variant === 'loading' ? 'animate-pulse' : ''}`} aria-hidden />
      <h3 className="mt-4 text-sm font-semibold text-primary">{title}</h3>
      {subtitle ? (
        <p className="mt-2 max-w-md text-center text-[12px] text-muted">{subtitle}</p>
      ) : null}
      {variant === 'loading' ? (
        <div className="mt-6 w-full max-w-md">
          <div className="mb-2 flex justify-between text-[11px] text-muted">
            <span>解析进度</span>
            <span className="tabular-nums">{Math.round(parseProgress)}%</span>
          </div>
          <div className="h-2 overflow-hidden rounded-full bg-border/15">
            <div
              className="h-full rounded-full bg-primaryAccent transition-all duration-300"
              style={{ width: `${Math.min(100, parseProgress)}%` }}
            />
          </div>
        </div>
      ) : null}
      {parseLines.length ? (
        <ul className="mt-6 w-full max-w-md space-y-2 text-[12px] text-muted">
          {parseLines.map((line) => (
            <li key={line} className="flex items-start gap-2">
              <Loader2 className="mt-0.5 h-3.5 w-3.5 shrink-0 animate-spin text-primaryAccent" aria-hidden />
              <span>{line}</span>
            </li>
          ))}
        </ul>
      ) : null}
      {showManualStart && onStartParse ? (
        <button
          type="button"
          disabled={parseBusy}
          data-testid="super-agent-start-parse-cta"
          onClick={onStartParse}
          className="mt-6 inline-flex min-h-10 items-center justify-center gap-2 rounded-lg border border-border/20 bg-background px-5 text-[12px] font-medium text-primary disabled:opacity-50"
        >
          <Upload className="h-4 w-4" aria-hidden />
          手动开始解析
        </button>
      ) : null}
    </div>
  )
}

export default function ParsePreviewPanel({
  preview,
  files = [],
  parseBusy = false,
  loading = false,
  parseProgress = 0,
  parseLines = [],
  showManualStart = false,
  onStartParse,
  onReparse,
}: ParsePreviewPanelProps) {
  const [activeIndex, setActiveIndex] = useState(0)
  const materials = preview?.materials ?? []

  useEffect(() => {
    if (activeIndex >= materials.length) {
      setActiveIndex(0)
    }
  }, [activeIndex, materials.length])

  const fileByName = useMemo(() => {
    const map = new Map<string, File>()
    for (const item of files) {
      map.set(item.file.name, item.file)
    }
    return map
  }, [files])

  const activeMaterial = materials[activeIndex]
  const activeMaterialStale = activeMaterial ? isStaleParsePreviewItem(activeMaterial) : false
  const previewStale = preview ? isStaleParsePreview(preview) : false

  return (
    <div className="space-y-3" data-testid="parse-preview-panel-v2">
      {!preview ? (
        <ParsePreviewLoadingState
          parseProgress={parseProgress}
          parseLines={parseLines}
          parseBusy={parseBusy}
          showManualStart={showManualStart}
          onStartParse={onStartParse}
          variant={loading || parseBusy ? 'loading' : 'idle'}
        />
      ) : (
        <>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="text-[11px] text-muted">
              共 {preview.summary.material_count} 份 · 成功 {preview.summary.parsed_ok} 份
              {preview.summary.degraded_count ? (
                <span className="text-[rgb(var(--color-sa-gold))]">
                  {' '}
                  · 降级/异常 {preview.summary.degraded_count} 份
                </span>
              ) : null}
            </div>
            {onReparse ? (
              <button
                type="button"
                disabled={parseBusy}
                onClick={onReparse}
                className="inline-flex items-center gap-1 rounded-md border border-border/20 bg-background px-2.5 py-1 text-[10px] font-medium text-primary disabled:opacity-50"
              >
                <RefreshCw className="h-3 w-3" aria-hidden />
                重新解析
              </button>
            ) : null}
          </div>

          {previewStale || activeMaterialStale ? (
            <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg border border-amber-200/80 bg-amber-50 px-3 py-2.5 text-[11px] text-amber-800">
              <span>当前预览为旧版数据（仅 content_preview），需重新解析以加载 PDF 对照与分块 Markdown。</span>
              {onReparse ? (
                <button
                  type="button"
                  disabled={parseBusy}
                  onClick={onReparse}
                  className="shrink-0 rounded-md border border-amber-300/80 bg-white px-2.5 py-1 text-[10px] font-medium text-amber-900 disabled:opacity-50"
                >
                  重新解析
                </button>
              ) : null}
            </div>
          ) : null}

          {materials.length > 1 ? (
            <div className="flex flex-wrap gap-1.5 border-b border-border/10 pb-2">
              {materials.map((item, index) => {
                const active = index === activeIndex
                const tone = formatParseStatus(item.parse_status).tone
                return (
                  <button
                    key={item.file_name}
                    type="button"
                    onClick={() => setActiveIndex(index)}
                    className={`inline-flex max-w-full items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-[10px] transition ${
                      active
                        ? 'border-primaryAccent/40 bg-primaryAccent/10 text-primary'
                        : 'border-border/15 bg-background text-muted hover:border-primaryAccent/25 hover:text-primary'
                    }`}
                  >
                    <span className="truncate">{item.file_name}</span>
                    <span
                      className={`h-1.5 w-1.5 shrink-0 rounded-full ${
                        tone === 'ok' ? 'bg-positive' : tone === 'warn' ? 'bg-[rgb(var(--color-sa-gold))]' : 'bg-destructive'
                      }`}
                      aria-hidden
                    />
                  </button>
                )
              })}
            </div>
          ) : null}

          {activeMaterial ? (
            <ParseMaterialCompareView
              key={activeMaterial.file_name}
              item={activeMaterial}
              preview={preview}
              sourceFile={fileByName.get(activeMaterial.file_name)}
            />
          ) : null}
        </>
      )}
    </div>
  )
}
