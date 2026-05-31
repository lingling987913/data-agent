'use client'

import { useEffect, useMemo, useState } from 'react'
import { usePdfPageDimensions } from '@/features/super-agent/utils/usePdfPageDimensions'
import { Pencil } from 'lucide-react'
import BlockEditModal from '@/features/super-agent/components/BlockEditModal'
import type { ParsePreviewBlock } from '@/features/super-agent/types'
import { fetchFigureImageBlob } from '@/features/super-agent/api'
import type { BboxPercentRect } from '@/features/super-agent/utils/bboxGeometry'
import {
  isFigureBlockType,
  isTableBlockType,
  resolveLayoutBlockHtml,
  resolveLayoutBlockMarkdown,
} from '@/features/super-agent/utils/layoutBlockContent'
import { resolveLayoutBlockFormula } from '@/features/super-agent/utils/formulaLayoutContent'
import FormulaRenderer from '@/features/super-agent/components/FormulaRenderer'
import { mergeLayoutTableFragments } from '@/features/super-agent/utils/layoutTableMerge'
import {
  layoutBlockRectOnPage,
  layoutBlockRotationOnPage,
  resolveLayoutPageRotation,
  type LayoutPageRotation,
} from '@/features/super-agent/utils/layoutPageRotation'
import { layoutBlockRotationStyle } from '@/features/super-agent/utils/layoutBlockRotation'
import {
  LAYOUT_BLOCK_MIN_HEIGHT_PX,
  LAYOUT_BLOCK_PROSE_INHERIT,
  LAYOUT_HTML_TABLE_INHERIT,
  layoutBlockTextLength,
  resolveLayoutBlockTypography,
} from '@/features/super-agent/utils/layoutBlockTypography'
import {
  blockContentEdited,
  blockDisplayMarkdown,
  blockLayoutDisplayText,
  blocksForPage,
  applyCalibrationHighlightsToHtml,
  needsCalibrationReview,
  renderCalibrationHighlightedHtml,
  shouldRenderPreviewWithMarkdown,
} from '@/features/super-agent/utils/parsePreviewBlocks'
import {
  resolveFigureDescription,
  isVisualImageBlock,
} from '@/features/super-agent/utils/figureBlockContent'
import MarkdownRenderer from '@/vendor/ui-core/MarkdownRenderer'

interface LayoutBlockPaneProps {
  blocks: ParsePreviewBlock[]
  originalBlocks: ParsePreviewBlock[]
  activePage: number
  activeBlockId: string | null
  pdfPageUrl?: string | null
  onBlockEdit: (blockId: string, text: string) => void
  onBlockActivatePage: (blockId: string, page: number) => void
  onBlockDoubleClick: (blockId: string) => void
}

interface PositionedBlock {
  block: ParsePreviewBlock
  index: number
  rect: BboxPercentRect
}

function FigureBlockImage({
  imageUrl,
  description,
}: {
  imageUrl: string
  description: string | null
}) {
  const [objectUrl, setObjectUrl] = useState<string | null>(null)
  const [failed, setFailed] = useState(false)

  useEffect(() => {
    let revokedUrl: string | null = null
    let cancelled = false
    setObjectUrl(null)
    setFailed(false)

    void fetchFigureImageBlob(imageUrl)
      .then((blob) => {
        if (cancelled) return
        revokedUrl = URL.createObjectURL(blob)
        setObjectUrl(revokedUrl)
      })
      .catch(() => {
        if (!cancelled) setFailed(true)
      })

    return () => {
      cancelled = true
      if (revokedUrl) URL.revokeObjectURL(revokedUrl)
    }
  }, [imageUrl])

  if (failed || !objectUrl) {
    return (
      <div className="flex min-h-0 w-full flex-1 items-center justify-center">
        <span className="leading-normal text-muted">图</span>
      </div>
    )
  }

  return (
    <div className="flex min-h-0 w-full flex-1 items-center justify-center">
      <img
        src={objectUrl}
        alt={description || 'figure'}
        className="h-full max-h-full w-full object-contain"
        loading="lazy"
      />
    </div>
  )
}

function LayoutBlockContent({
  block,
  rect,
  rotation,
}: {
  block: ParsePreviewBlock
  rect: BboxPercentRect
  rotation: number
}) {
  const rotationStyle = layoutBlockRotationStyle(rotation)
  const formulaLatex = resolveLayoutBlockFormula(block)
  const tableHtml = formulaLatex ? null : resolveLayoutBlockHtml(block)
  const highlightedTableHtml = tableHtml ? applyCalibrationHighlightsToHtml(block, tableHtml) : null
  const isTableBlock = isTableBlockType(block.block_type) || tableHtml !== null
  const displayText = blockLayoutDisplayText(block)
  const typography = resolveLayoutBlockTypography(
    rect,
    layoutBlockTextLength(displayText, isTableBlock),
    { rotation, isTable: isTableBlock, isFormula: Boolean(formulaLatex) },
  )

  const inner = (() => {
    if (highlightedTableHtml) {
      return (
        <div
          className={`min-h-0 w-full leading-normal text-primary/90 ${LAYOUT_HTML_TABLE_INHERIT}`}
          style={typography.wrapperStyle}
          dangerouslySetInnerHTML={{ __html: highlightedTableHtml }}
        />
      )
    }

    if (formulaLatex) {
      return (
        <div
          className="flex w-full items-center justify-start overflow-x-auto"
          style={typography.wrapperStyle}
        >
          <FormulaRenderer latex={formulaLatex} displayMode />
        </div>
      )
    }

    if (!displayText || (isVisualImageBlock(block) && !tableHtml)) {
      const figureDescription = resolveFigureDescription(block)
      const figureImageUrl = block.image_url?.trim() || null
      if (isVisualImageBlock(block) && (figureImageUrl || figureDescription)) {
        return (
          <div
            className="flex h-full min-h-0 w-full flex-col gap-1 overflow-hidden"
            style={{ ...typography.wrapperStyle, height: '100%' }}
          >
            {figureImageUrl ? (
              <FigureBlockImage imageUrl={figureImageUrl} description={figureDescription} />
            ) : (
              <div className="flex min-h-0 w-full flex-1 items-center justify-center">
                <span className="leading-normal text-muted">图</span>
              </div>
            )}
            {figureDescription ? (
              <div
                className="shrink-0 overflow-hidden leading-normal text-primary/90"
                title={figureDescription}
                style={{
                  display: '-webkit-box',
                  WebkitLineClamp: 2,
                  WebkitBoxOrient: 'vertical',
                }}
              >
                {figureDescription}
              </div>
            ) : null}
          </div>
        )
      }
      const label = isVisualImageBlock(block) || isFigureBlockType(block.block_type)
        ? '图'
        : block.block_type || '（空块）'
      return (
        <span className="leading-normal text-muted" style={typography.wrapperStyle}>
          {label}
        </span>
      )
    }

    const markdown = resolveLayoutBlockMarkdown(block)
    const showCalibrationHighlight = block.calibrated || block.needs_calibration_review || needsCalibrationReview(block)
    if (showCalibrationHighlight && !shouldRenderPreviewWithMarkdown(block, markdown)) {
      return (
        <div
          style={typography.wrapperStyle}
          dangerouslySetInnerHTML={{ __html: renderCalibrationHighlightedHtml(block, markdown) }}
        />
      )
    }
    return (
      <div style={typography.wrapperStyle}>
        <MarkdownRenderer className={LAYOUT_BLOCK_PROSE_INHERIT}>{markdown}</MarkdownRenderer>
      </div>
    )
  })()

  if (!rotationStyle) return inner

  return (
    <div className="flex h-auto w-full items-start justify-start overflow-visible" style={rotationStyle}>
      {inner}
    </div>
  )
}

export default function LayoutBlockPane({
  blocks,
  originalBlocks,
  activePage,
  activeBlockId,
  pdfPageUrl,
  onBlockEdit,
  onBlockActivatePage,
  onBlockDoubleClick,
}: LayoutBlockPaneProps) {
  const [editingBlock, setEditingBlock] = useState<ParsePreviewBlock | null>(null)

  const originalById = useMemo(() => {
    const map = new Map<string, ParsePreviewBlock>()
    for (const block of originalBlocks) {
      map.set(block.id, block)
    }
    return map
  }, [originalBlocks])

  const pdfPageSize = usePdfPageDimensions(pdfPageUrl, activePage)

  const { positioned, unpositioned, pageLayout } = useMemo(() => {
    const pageBlocks = mergeLayoutTableFragments(blocksForPage(blocks, activePage))
    const layout = resolveLayoutPageRotation(pageBlocks, { pageSize: pdfPageSize })
    const positionedBlocks: PositionedBlock[] = []
    const unpositionedBlocks: ParsePreviewBlock[] = []

    pageBlocks.forEach((block, index) => {
      const rect = layoutBlockRectOnPage(block, layout.rotation)
      if (rect) {
        positionedBlocks.push({ block, index, rect })
        return
      }
      unpositionedBlocks.push(block)
    })

    return { positioned: positionedBlocks, unpositioned: unpositionedBlocks, pageLayout: layout }
  }, [blocks, activePage, pdfPageSize])

  if (!blocks.length) {
    return (
      <div className="flex h-full min-h-0 items-center justify-center px-4 text-center text-[12px] text-muted">
        未提取到可预览正文。
      </div>
    )
  }

  return (
    <>
      <div className="h-full min-h-0 overflow-auto px-2 py-2">
        <div className="mb-2 text-[10px] text-muted">第 {activePage} 页 · 版面复原</div>
        <div
          className="relative mx-auto w-full max-w-full rounded border border-border/20 bg-white shadow-inner"
          style={{ aspectRatio: pageLayout.aspectRatio }}
          data-testid="layout-block-canvas"
          data-page-rotation={pageLayout.rotation}
        >
          {positioned.map(({ block, index, rect }) => {
            const blockId = block.id
            const pageHint = block.page_hint ?? 1
            const original = originalById.get(blockId)
            const isEdited = original ? blockContentEdited(original, block) : false
            const isActive = activeBlockId === blockId
            const fullText = blockLayoutDisplayText(block)
            const hasContent = Boolean(fullText)
            const rotation = layoutBlockRotationOnPage(block, pageLayout.rotation as LayoutPageRotation)
            const formulaLatex = resolveLayoutBlockFormula(block)
            const isTableBlock =
              isTableBlockType(block.block_type) || (!formulaLatex && resolveLayoutBlockHtml(block) !== null)
            const isFigureBlock = isFigureBlockType(block.block_type) || isVisualImageBlock(block)
            const isFormulaBlock = Boolean(formulaLatex)
            const isCompactBlock = !isTableBlock && !isFigureBlock && !isFormulaBlock && rect.width * rect.height < 900

            return (
              <div
                key={blockId}
                data-block-id={blockId}
                data-page-hint={pageHint}
                title={fullText || block.block_type}
                onClick={() => onBlockActivatePage(blockId, pageHint)}
                onDoubleClick={(event) => {
                  event.preventDefault()
                  onBlockDoubleClick(blockId)
                }}
                className={`group absolute cursor-pointer rounded-sm border px-0.5 py-px transition hover:z-[500] ${
                  isActive
                    ? 'border-amber-500 bg-amber-100/70 ring-2 ring-amber-400'
                    : 'border-transparent bg-transparent'
                } ${isTableBlock ? 'overflow-auto' : isFigureBlock ? 'overflow-hidden' : 'overflow-visible'}`}
                style={{
                  left: `${rect.left}%`,
                  top: `${rect.top}%`,
                  width: `${rect.width}%`,
                  height: isFigureBlock ? `${rect.height}%` : 'auto',
                  minHeight: isTableBlock
                    ? `${rect.height}%`
                    : isFigureBlock
                      ? `${rect.height}%`
                    : `max(${LAYOUT_BLOCK_MIN_HEIGHT_PX}px, ${rect.height}%)`,
                  zIndex: isActive ? 1000 + index : index + 1,
                }}
              >
                <div
                  className={`flex ${isFigureBlock ? 'h-full min-h-0 justify-center' : 'h-auto'} flex-col items-start`}
                >
                  {!isCompactBlock && (!hasContent || isEdited) ? (
                    <div className="mb-px flex w-full shrink-0 items-center gap-1 leading-none">
                      {!hasContent ? (
                        <span className="truncate text-[8px] font-medium uppercase text-muted/80">
                          {block.block_type}
                        </span>
                      ) : null}
                      {isEdited ? (
                        <span className="text-[8px] font-medium text-primaryAccent">已编辑</span>
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
                        <Pencil className="h-2.5 w-2.5" aria-hidden />
                      </button>
                    </div>
                  ) : (
                    <button
                      type="button"
                      title="编辑此块"
                      onClick={(event) => {
                        event.stopPropagation()
                        setEditingBlock(block)
                      }}
                      className="absolute right-0.5 top-0.5 z-10 rounded p-0.5 text-muted opacity-0 transition hover:bg-border/10 group-hover:opacity-100"
                      aria-label="编辑此块"
                    >
                      <Pencil className="h-2.5 w-2.5" aria-hidden />
                    </button>
                  )}
                  <div
                    className={`w-full break-words leading-normal ${
                      isTableBlock
                        ? 'min-h-0 overflow-auto'
                        : isFigureBlock
                          ? 'h-full min-h-0 overflow-hidden'
                          : 'overflow-visible'
                    }`}
                  >
                    <LayoutBlockContent block={block} rect={rect} rotation={rotation} />
                  </div>
                </div>
              </div>
            )
          })}
          {positioned.length === 0 ? (
            <div className="absolute inset-0 flex items-center justify-center px-4 text-center text-[11px] text-muted">
              当前页无 bbox 定位数据
            </div>
          ) : null}
        </div>

        {unpositioned.length > 0 ? (
          <div className="mt-3 rounded-md border border-dashed border-border/25 bg-surface/40 px-2 py-2">
            <div className="mb-1.5 text-[10px] font-medium text-muted">未定位块（第 {activePage} 页）</div>
            <div className="space-y-1">
              {unpositioned.map((block) => {
                const blockId = block.id
                const pageHint = block.page_hint ?? 1
                const isActive = activeBlockId === blockId
                return (
                  <div
                    key={blockId}
                    data-block-id={blockId}
                    title={blockDisplayMarkdown(block)}
                    onClick={() => onBlockActivatePage(blockId, pageHint)}
                    onDoubleClick={(event) => {
                      event.preventDefault()
                      onBlockDoubleClick(blockId)
                    }}
                    className={`cursor-pointer rounded px-2 py-1 text-[11px] transition ${
                      isActive ? 'bg-amber-50 ring-1 ring-amber-300' : 'hover:bg-primaryAccent/5'
                    }`}
                  >
                    {!blockLayoutDisplayText(block) ? (
                      <span className="mr-1 text-[9px] uppercase text-muted">{block.block_type}</span>
                    ) : null}
                    <LayoutBlockContent
                      block={block}
                      rect={{ left: 0, top: 0, width: 100, height: 100 }}
                      rotation={layoutBlockRotationOnPage(block, pageLayout.rotation as LayoutPageRotation)}
                    />
                  </div>
                )
              })}
            </div>
          </div>
        ) : null}
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
