'use client'

import { useEffect, useState } from 'react'
import * as pdfjsLib from 'pdfjs-dist'

pdfjsLib.GlobalWorkerOptions.workerSrc = new URL(
  'pdfjs-dist/build/pdf.worker.min.mjs',
  import.meta.url,
).toString()

export interface PdfPageDimensions {
  width: number
  height: number
}

/** PDF.js viewport size at scale=1 — matches PdfBlockOverlayViewer bbox mapping. */
export function usePdfPageDimensions(
  pdfUrl: string | null | undefined,
  page: number,
): PdfPageDimensions | null {
  const [dimensions, setDimensions] = useState<PdfPageDimensions | null>(null)

  useEffect(() => {
    if (!pdfUrl || page <= 0) {
      setDimensions(null)
      return
    }

    let cancelled = false
    const loadingTask = pdfjsLib.getDocument(pdfUrl)

    void loadingTask.promise
      .then((doc) => doc.getPage(page))
      .then((pdfPage) => {
        if (cancelled) return
        const viewport = pdfPage.getViewport({ scale: 1 })
        setDimensions({ width: viewport.width, height: viewport.height })
      })
      .catch(() => {
        if (!cancelled) setDimensions(null)
      })

    return () => {
      cancelled = true
      void loadingTask.destroy()
    }
  }, [pdfUrl, page])

  return dimensions
}
