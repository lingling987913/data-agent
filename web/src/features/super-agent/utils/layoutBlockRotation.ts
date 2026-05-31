import type { CSSProperties } from 'react'
import type { ParsePreviewBlock } from '@/features/super-agent/types'
import { mineruBboxToPercentRect } from '@/features/super-agent/utils/bboxGeometry'
import { isTableBlockType } from '@/features/super-agent/utils/layoutBlockContent'

const VALID_ANGLES = new Set([0, 90, 180, 270])

function normalizeAngle(value: number): number {
  const angle = ((value % 360) + 360) % 360
  return VALID_ANGLES.has(angle) ? angle : 0
}

/** Resolve reading rotation for layout view (degrees clockwise in PDF). */
export function resolveLayoutBlockRotation(block: ParsePreviewBlock): number {
  if (typeof block.angle === 'number' && Number.isFinite(block.angle)) {
    const normalized = normalizeAngle(block.angle)
    if (normalized !== 0) return normalized
  }

  // Fallback: tall-narrow table bbox often indicates a landscape table rotated 90°.
  if (
    isTableBlockType(block.block_type) &&
    Array.isArray(block.bbox) &&
    block.bbox.length >= 4
  ) {
    const rect = mineruBboxToPercentRect(block.bbox)
    if (
      rect &&
      rect.height > rect.width * 1.25 &&
      rect.height < 60 &&
      rect.width < 35
    ) {
      return 90
    }
  }

  return 0
}

/** Counter-rotate block content so text reads in normal orientation. */
export function layoutBlockRotationStyle(angle: number): CSSProperties | undefined {
  if (!angle) return undefined
  return {
    transform: `rotate(${-angle}deg)`,
    transformOrigin: 'center center',
  }
}
