import type { ParsePreviewBlock } from '@/features/super-agent/types'

const IMAGE_MD_RE = /!\[[^\]]*\]\([^)]+\)/
const IMAGE_PATH_RE = /(?:^|\/)(?:images\/)?[^/\s]+\.(?:jpe?g|png|gif|webp|bmp|jp2)(?:\?[^/\s]*)?$/i
const THINK_BLOCK_RE = /<think\b[^>]*>[\s\S]*?<\/think>/gi
const FENCED_THINK_RE = /```(?:thinking|think)\s*[\s\S]*?```/gi
const UNUSABLE_VISION_RE = /没有看到|未看到|无法看到|看不到|没有提供图片|没有图片|上传图片|提供图片|图片链接|image is not provided|no image|cannot see|can't see/i

export function looksLikeImageRef(value: string): boolean {
  const text = value.trim()
  if (!text) return false
  if (IMAGE_MD_RE.test(text)) return true
  const lowered = text.toLowerCase()
  if (['image', 'figure', 'img', 'photo', 'picture'].includes(lowered)) return false
  return IMAGE_PATH_RE.test(text)
}

export function sanitizeFigureDescription(value: string): string {
  return value
    .replace(FENCED_THINK_RE, '')
    .replace(THINK_BLOCK_RE, '')
    .replace(/^\s*(assistant|助手)\s*[:：]\s*/i, '')
    .trim()
}

function isUsableFigureDescription(value: string): boolean {
  const text = sanitizeFigureDescription(value)
  if (text.length < 4) return false
  return !UNUSABLE_VISION_RE.test(text)
}

function hasFigureBbox(block: ParsePreviewBlock): boolean {
  return Array.isArray(block.bbox) && block.bbox.length >= 4
}

export function isVisualImageBlock(block: ParsePreviewBlock): boolean {
  const blockType = (block.block_type || '').toLowerCase()
  if (blockType === 'figure' || blockType === 'image' || blockType.includes('figure')) {
    return true
  }
  const content = (block.content || block.markdown || '').trim()
  return hasFigureBbox(block) && looksLikeImageRef(content)
}

export function resolveFigureDescription(block: ParsePreviewBlock): string | null {
  const candidates = [block.image_description, block.caption]
  for (const value of candidates) {
    const text = sanitizeFigureDescription(value || '')
    if (!text || looksLikeImageRef(text)) continue
    if (!isUsableFigureDescription(text)) continue
    return text
  }
  return null
}

export function resolveFigureDisplayText(block: ParsePreviewBlock): string {
  if (!isVisualImageBlock(block)) {
    return (block.content || block.markdown || '').trim()
  }
  const description = resolveFigureDescription(block)
  if (description) return description
  const content = (block.content || block.markdown || '').trim()
  if (!content || content === '[figure]' || looksLikeImageRef(content)) return ''
  return content
}
