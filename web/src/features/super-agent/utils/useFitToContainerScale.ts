import { useEffect, useState, type RefObject } from 'react'

export function computeFitScale(
  containerWidth: number,
  containerHeight: number,
  contentWidth: number,
  contentHeight: number,
  maxScale = 1,
): number {
  if (containerWidth <= 0 || containerHeight <= 0 || contentWidth <= 0 || contentHeight <= 0) {
    return 1
  }
  return Math.min(maxScale, containerWidth / contentWidth, containerHeight / contentHeight)
}

export function useFitToContainerScale(
  containerRef: RefObject<HTMLElement | null>,
  contentRef: RefObject<HTMLElement | null>,
  deps: unknown[] = [],
  maxScale = 1,
): number {
  const [scale, setScale] = useState(1)

  useEffect(() => {
    const container = containerRef.current
    const content = contentRef.current
    if (!container || !content) return

    const update = () => {
      setScale(
        computeFitScale(
          container.clientWidth,
          container.clientHeight,
          content.offsetWidth,
          content.offsetHeight,
          maxScale,
        ),
      )
    }

    update()
    const observer = new ResizeObserver(() => update())
    observer.observe(container)
    observer.observe(content)
    return () => observer.disconnect()
  }, [containerRef, contentRef, maxScale, ...deps])

  return scale
}
