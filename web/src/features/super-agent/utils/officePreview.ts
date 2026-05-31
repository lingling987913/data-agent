import type { OfficePreviewKind } from '@/features/super-agent/utils/parsePreviewFormat'
import { resolveOfficePreviewKind } from '@/features/super-agent/utils/parsePreviewFormat'

export interface OfficePreviewSheet {
  name: string
  html: string
}

export interface OfficePreviewSlide {
  index: number
  lines: string[]
}

export interface OfficePreviewResult {
  kind: OfficePreviewKind
  pageCount: number
  html?: string
  sheets?: OfficePreviewSheet[]
  slides?: OfficePreviewSlide[]
}

const SLIDE_XML_PATH = /^ppt\/slides\/slide(\d+)\.xml$/i
const SLIDE_TEXT_REGEX = /<a:t(?:\s[^>]*)?>([^<]*)<\/a:t>/g
const WORD_PAGE_BREAK_REGEX = /<hr[^>]*class="[^"]*docx-page-break[^"]*"[^>]*\/?>/gi

const WORD_PREVIEW_STYLE_MAP = ["br[type='page'] => hr.docx-page-break:fresh"]

function toUint8Array(data: ArrayBuffer): Uint8Array {
  return data instanceof Uint8Array ? data : new Uint8Array(data)
}

async function loadXlsxModule() {
  const mod = await import('xlsx')
  const candidate = 'default' in mod && mod.default ? mod.default : mod
  const XLSX = candidate as typeof mod
  if (typeof XLSX.read !== 'function' || !XLSX.utils) {
    throw new Error('Excel 预览模块加载失败，请刷新页面后重试')
  }
  return XLSX
}

async function loadMammothModule() {
  const mod = await import('mammoth')
  const candidate = 'default' in mod && mod.default ? mod.default : mod
  const mammoth = candidate as Pick<typeof mod, 'convertToHtml'>
  if (typeof mammoth.convertToHtml !== 'function') {
    throw new Error('Word 预览模块加载失败，请刷新页面后重试')
  }
  return mammoth
}

function formatExcelReadError(error: unknown): string {
  const message = error instanceof Error ? error.message : String(error)
  if (/password|encrypted|protected/i.test(message)) {
    return 'Excel 文件已加密或受保护，无法在浏览器中预览'
  }
  if (/unsupported|unrecognized|invalid|corrupt|zip/i.test(message)) {
    return 'Excel 文件格式无效或已损坏，请确认文件为 .xlsx / .xls'
  }
  return `Excel 解析失败：${message}`
}

const EXCEL_EMPTY_SHEET_HTML =
  '<p class="office-preview-empty-sheet text-sm text-muted-foreground">此工作表为空，无可预览内容</p>'

function hasExcelSheetRange(sheet: Record<string, unknown> | undefined): boolean {
  const ref = sheet?.['!ref']
  return typeof ref === 'string' && ref.length > 0
}

function renderExcelSheetHtml(
  XLSX: Awaited<ReturnType<typeof loadXlsxModule>>,
  sheet: Record<string, unknown>,
  sheetIndex: number,
): string {
  if (!hasExcelSheetRange(sheet)) {
    return EXCEL_EMPTY_SHEET_HTML
  }
  return XLSX.utils.sheet_to_html(sheet, { id: `sheet-${sheetIndex + 1}`, editable: false })
}

export function wrapWordPreviewHtml(html: string): string {
  const trimmed = html.trim()
  if (!trimmed) return trimmed

  const parts = trimmed
    .split(WORD_PAGE_BREAK_REGEX)
    .map((part) => part.trim())
    .filter(Boolean)

  if (parts.length <= 1) {
    return `<div class="docx-preview-page">${trimmed}</div>`
  }

  return parts.map((part) => `<div class="docx-preview-page">${part}</div>`).join('')
}

export function extractPptxSlideTexts(xml: string): string[] {
  const texts: string[] = []
  for (const match of xml.matchAll(SLIDE_TEXT_REGEX)) {
    const text = match[1]?.trim()
    if (text) texts.push(text)
  }
  return texts
}

export function sortPptxSlideNames(names: string[]): string[] {
  return names
    .filter((name) => SLIDE_XML_PATH.test(name))
    .sort((left, right) => {
      const leftMatch = left.match(SLIDE_XML_PATH)
      const rightMatch = right.match(SLIDE_XML_PATH)
      return Number(leftMatch?.[1] || 0) - Number(rightMatch?.[1] || 0)
    })
}

async function buildWordPreview(data: ArrayBuffer): Promise<OfficePreviewResult> {
  const mammoth = await loadMammothModule()
  const result = await mammoth.convertToHtml(
    { arrayBuffer: data },
    { styleMap: WORD_PREVIEW_STYLE_MAP },
  )
  return {
    kind: 'word',
    pageCount: 1,
    html: wrapWordPreviewHtml(result.value),
  }
}

async function buildExcelPreview(data: ArrayBuffer): Promise<OfficePreviewResult> {
  const XLSX = await loadXlsxModule()
  let workbook
  try {
    workbook = XLSX.read(toUint8Array(data), { type: 'array' })
  } catch (error) {
    throw new Error(formatExcelReadError(error))
  }

  if (!workbook.SheetNames.length) {
    throw new Error('Excel 文件中未找到可预览的工作表')
  }

  const sheets: OfficePreviewSheet[] = workbook.SheetNames.map((name, index) => {
    const sheet = workbook.Sheets[name]
    if (!sheet) {
      return { name, html: EXCEL_EMPTY_SHEET_HTML }
    }
    try {
      return { name, html: renderExcelSheetHtml(XLSX, sheet, index) }
    } catch (error) {
      const detail = error instanceof Error ? error.message : '未知错误'
      return {
        name,
        html: `<p class="office-preview-sheet-error text-sm text-destructive">工作表预览失败：${detail}</p>`,
      }
    }
  })

  if (!sheets.some((sheet) => sheet.html.includes('<table'))) {
    throw new Error('Excel 工作表为空，没有可预览的单元格内容')
  }

  return {
    kind: 'excel',
    pageCount: Math.max(sheets.length, 1),
    sheets,
  }
}

async function buildPptPreview(data: ArrayBuffer): Promise<OfficePreviewResult> {
  const JSZip = (await import('jszip')).default
  const zip = await JSZip.loadAsync(data)
  const slideNames = sortPptxSlideNames(Object.keys(zip.files))
  const slides: OfficePreviewSlide[] = []

  for (const [slideIndex, slideName] of slideNames.entries()) {
    const entry = zip.file(slideName)
    if (!entry) continue
    const xml = await entry.async('text')
    slides.push({
      index: slideIndex + 1,
      lines: extractPptxSlideTexts(xml),
    })
  }

  return {
    kind: 'ppt',
    pageCount: Math.max(slides.length, 1),
    slides,
  }
}

export async function buildOfficePreview(fileName: string, data: ArrayBuffer): Promise<OfficePreviewResult | null> {
  const kind = resolveOfficePreviewKind(fileName)
  if (!kind) return null

  switch (kind) {
    case 'word':
      return buildWordPreview(data)
    case 'excel':
      return buildExcelPreview(data)
    case 'ppt':
      return buildPptPreview(data)
    default:
      return null
  }
}
