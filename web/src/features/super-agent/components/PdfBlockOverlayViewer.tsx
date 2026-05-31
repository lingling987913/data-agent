'use client'

import { useCallback, useEffect, useRef, useState } from 'react'
import * as pdfjsLib from 'pdfjs-dist'
import type { PDFDocumentProxy, RenderTask } from 'pdfjs-dist'
import type { ParsePreviewBlock } from '@/features/super-agent/types'
import { blocksForPage } from '@/features/super-agent/utils/parsePreviewBlocks'
import { mineruBboxToPixelRect, scalePixelRect } from '@/features/super-agent/utils/bboxGeometry'

pdfjsLib.GlobalWorkerOptions.workerSrc = new URL(
  'pdfjs-dist/build/pdf.worker.min.mjs',
  import.meta.url,
).toString()

interface PdfBlockOverlayViewerProps {
  pdfUrl: string
  fileName: string
  pageCount: number
  currentPage: number
  blocks: ParsePreviewBlock[]
  activeBlockId: string | null
  onPageChange: (page: number) => void
  onBlockSelect: (blockId: string) => void
}

interface OverlayItem {
  blockId: string
  rect: { left: number; top: number; width: number; height: number }
}

function isRenderCancelled(err: unknown): boolean {
  return (
    err instanceof pdfjsLib.RenderingCancelledException ||
    (err instanceof Error && err.name === 'RenderingCancelledException')
  )
}

export default function PdfBlockOverlayViewer({
  pdfUrl,
  fileName,
  pageCount,
  currentPage,
  blocks,
  activeBlockId,
  onPageChange,
  onBlockSelect,
}: PdfBlockOverlayViewerProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const renderTaskRef = useRef<RenderTask | null>(null)
  const renderGenerationRef = useRef(0)
  const [pdfDoc, setPdfDoc] = useState<PDFDocumentProxy | null>(null)
  const [loadError, setLoadError] = useState('')
  const [rendering, setRendering] = useState(false)
  const [viewportSize, setViewportSize] = useState({ width: 0, height: 0 })
  const [displayScale, setDisplayScale] = useState(1)
  const [overlays, setOverlays] = useState<OverlayItem[]>([])

  const safePage = Math.min(Math.max(currentPage, 1), Math.max(pageCount, 1))

  useEffect(() => {
    let cancelled = false
    setLoadError('')
    setPdfDoc(null)

    const loadingTask = pdfjsLib.getDocument(pdfUrl)
    loadingTask.promise
      .then((doc) => {
        if (!cancelled) setPdfDoc(doc)
      })
      .catch((err) => {
        if (!cancelled) {
          setLoadError(err instanceof Error ? err.message : 'PDF 加载失败')
        }
      })

    return () => {
      cancelled = true
      void loadingTask.destroy()
    }
  }, [pdfUrl])

  const cancelActiveRender = useCallback(() => {
    renderTaskRef.current?.cancel()
    renderTaskRef.current = null
  }, [])

  const renderPage = useCallback(async () => {
    if (!pdfDoc || !canvasRef.current || !containerRef.current) return

    cancelActiveRender()
    const generation = ++renderGenerationRef.current

    setRendering(true)
    try {
      const page = await pdfDoc.getPage(safePage)
      if (generation !== renderGenerationRef.current) return

      const baseViewport = page.getViewport({ scale: 1 })
      const containerWidth = containerRef.current.clientWidth || baseViewport.width
      const scale = containerWidth / baseViewport.width
      const viewport = page.getViewport({ scale })

      const canvas = canvasRef.current
      const context = canvas.getContext('2d')
      if (!context) return

      canvas.width = viewport.width
      canvas.height = viewport.height
      canvas.style.width = `${viewport.width}px`
      canvas.style.height = `${viewport.height}px`

      const renderTask = page.render({ canvasContext: context, viewport })
      renderTaskRef.current = renderTask
      await renderTask.promise
      if (generation !== renderGenerationRef.current) return

      renderTaskRef.current = null
      setViewportSize({ width: baseViewport.width, height: baseViewport.height })
      setDisplayScale(scale)

      const pageBlocks = blocksForPage(blocks, safePage)
      const nextOverlays: OverlayItem[] = []
      for (const block of pageBlocks) {
        if (!block.bbox?.length || block.bbox.length < 4) continue
        const blockId = block.id
        const pixelRect = mineruBboxToPixelRect(
          block.bbox,
          baseViewport.width,
          baseViewport.height,
        )
        if (!pixelRect) continue
        nextOverlays.push({
          blockId,
          rect: scalePixelRect(pixelRect, scale),
        })
      }
      setOverlays(nextOverlays)
    } catch (err) {
      if (generation !== renderGenerationRef.current || isRenderCancelled(err)) return
      setLoadError(err instanceof Error ? err.message : 'PDF 渲染失败')
    } finally {
      if (generation === renderGenerationRef.current) {
        setRendering(false)
      }
    }
  }, [pdfDoc, safePage, blocks, cancelActiveRender])

  useEffect(() => {
    void renderPage()

    const container = containerRef.current
    if (!container) {
      return () => {
        cancelActiveRender()
      }
    }

    let resizeTimer: ReturnType<typeof setTimeout> | undefined
    const observer = new ResizeObserver(() => {
      if (resizeTimer) clearTimeout(resizeTimer)
      resizeTimer = setTimeout(() => {
        void renderPage()
      }, 150)
    })
    observer.observe(container)

    return () => {
      if (resizeTimer) clearTimeout(resizeTimer)
      observer.disconnect()
      cancelActiveRender()
    }
  }, [renderPage, cancelActiveRender])

  if (loadError) {
    return (
      <div className="flex h-full items-center justify-center px-4 text-center text-[11px] text-destructive">
        {loadError}
      </div>
    )
  }

  return (
    <div ref={containerRef} className="relative h-full overflow-auto bg-[#525659]">
      {!pdfDoc || rendering ? (
        <div className="absolute inset-0 z-10 flex items-center justify-center bg-background/60 text-[11px] text-muted">
          {pdfDoc ? '渲染中…' : '加载 PDF…'}
        </div>
      ) : null}
      <div className="relative mx-auto w-fit shrink-0">
        <canvas ref={canvasRef} aria-label={`${fileName} 第 ${safePage} 页`} />
        {viewportSize.width > 0 ? (
          <svg
            className="pointer-events-none absolute left-0 top-0"
            width={viewportSize.width * displayScale}
            height={viewportSize.height * displayScale}
            aria-hidden
          >
            {overlays.map(({ blockId, rect }) => {
              const isActive = activeBlockId === blockId
              return (
                <rect
                  key={blockId}
                  x={rect.left}
                  y={rect.top}
                  width={rect.width}
                  height={rect.height}
                  className="pointer-events-auto cursor-pointer transition-colors"
                  fill={isActive ? 'rgba(251, 191, 36, 0.35)' : 'transparent'}
                  stroke={isActive ? 'rgb(245, 158, 11)' : 'transparent'}
                  strokeWidth={isActive ? 2 : 0}
                  onClick={() => onBlockSelect(blockId)}
                />
              )
            })}
          </svg>
        ) : null}
      </div>
      {overlays.length === 0 && pdfDoc && !rendering ? (
        <p className="pointer-events-none absolute bottom-2 left-0 right-0 text-center text-[10px] text-white/70">
          当前页无 bbox 数据，仅显示 PDF 原文
        </p>
      ) : null}
    </div>
  )
}
