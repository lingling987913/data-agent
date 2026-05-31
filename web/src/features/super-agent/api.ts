import { buildAuthHeaders, fetchApi, fetchApiJson } from '@/lib/apiClient'
import type {
  CreateSuperAgentRunInput,
  MaterialClassification,
  ParsePreviewResponse,
  SaveWizardCheckpointInput,
  SuperAgentBenchmarkReport,
  SuperAgentCapabilities,
  SuperAgentGncStatus,
  SuperAgentReviewRunInput,
  SuperAgentRun,
  SuperAgentUploadResponse,
} from './types'

const SUPER_AGENT_PREFIX = '/api/v1/super-agent'

type ParsePreviewJob = {
  job_id: string
  run_id: string
  status: 'queued' | 'running' | 'completed' | 'failed'
  progress: number
  message: string
  error?: string
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms))
}

export async function getSuperAgentCapabilities(): Promise<SuperAgentCapabilities> {
  return fetchApiJson<SuperAgentCapabilities>(`${SUPER_AGENT_PREFIX}/capabilities`)
}

export async function listSuperAgentRuns(): Promise<SuperAgentRun[]> {
  return fetchApiJson<SuperAgentRun[]>(`${SUPER_AGENT_PREFIX}/runs?page=1&size=50`)
}

export async function createSuperAgentRun(body: CreateSuperAgentRunInput): Promise<SuperAgentRun> {
  return fetchApiJson<SuperAgentRun>(`${SUPER_AGENT_PREFIX}/runs`, {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export async function uploadSuperAgentMaterials(files: File[]): Promise<SuperAgentUploadResponse> {
  const formData = new FormData()
  files.forEach((f) => formData.append('files', f))
  const res = await fetchApi(`${SUPER_AGENT_PREFIX}/uploads`, {
    method: 'POST',
    body: formData,
    headers: buildAuthHeaders(false),
  })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`材料上传失败 ${res.status}: ${text}`)
  }
  const json = await res.json()
  return json.data as SuperAgentUploadResponse
}

export async function updateSuperAgentRun(runId: string, body: CreateSuperAgentRunInput): Promise<SuperAgentRun> {
  return fetchApiJson<SuperAgentRun>(`${SUPER_AGENT_PREFIX}/runs/${runId}`, {
    method: 'PUT',
    body: JSON.stringify(body),
  })
}

export async function executeSuperAgentRun(runId: string): Promise<SuperAgentRun> {
  return fetchApiJson<SuperAgentRun>(`${SUPER_AGENT_PREFIX}/runs/${runId}/execute`, {
    method: 'POST',
  })
}

export async function reviewSuperAgentRun(
  runId: string,
  body?: SuperAgentReviewRunInput,
): Promise<SuperAgentRun> {
  return fetchApiJson<SuperAgentRun>(`${SUPER_AGENT_PREFIX}/runs/${runId}/review`, {
    method: 'POST',
    body: JSON.stringify(body ?? {}),
  })
}

export async function resumeSuperAgentRun(runId: string): Promise<SuperAgentRun> {
  return fetchApiJson<SuperAgentRun>(`${SUPER_AGENT_PREFIX}/runs/${runId}/resume`, {
    method: 'POST',
  })
}

export async function interruptSuperAgentRun(runId: string): Promise<SuperAgentRun> {
  return fetchApiJson<SuperAgentRun>(`${SUPER_AGENT_PREFIX}/runs/${runId}/interrupt`, {
    method: 'POST',
  })
}

export async function getSuperAgentRun(runId: string): Promise<SuperAgentRun> {
  return fetchApiJson<SuperAgentRun>(`${SUPER_AGENT_PREFIX}/runs/${runId}`)
}

export async function deleteSuperAgentRun(
  runId: string,
  options?: { force?: boolean },
): Promise<{ deleted: boolean; run_id: string; force?: boolean }> {
  const force = options?.force ? 'true' : 'false'
  return fetchApiJson<{ deleted: boolean; run_id: string; force?: boolean }>(
    `${SUPER_AGENT_PREFIX}/runs/${runId}?force=${force}`,
    { method: 'DELETE' },
  )
}

export async function saveWizardCheckpoint(
  runId: string,
  body: SaveWizardCheckpointInput,
): Promise<SuperAgentRun> {
  return fetchApiJson<SuperAgentRun>(`${SUPER_AGENT_PREFIX}/runs/${runId}/wizard`, {
    method: 'PATCH',
    body: JSON.stringify(body),
  })
}

export async function classifyRunMaterials(
  runId: string,
): Promise<{ classification: MaterialClassification; run: SuperAgentRun }> {
  return fetchApiJson<{ classification: MaterialClassification; run: SuperAgentRun }>(
    `${SUPER_AGENT_PREFIX}/runs/${runId}/classify`,
    { method: 'POST' },
  )
}

export async function parsePreviewFromRun(
  runId: string,
  options?: { forceReparse?: boolean; onProgress?: (job: ParsePreviewJob) => void },
): Promise<{ preview: ParsePreviewResponse; run: SuperAgentRun }> {
  const force = options?.forceReparse ? '?force_reparse=true' : ''
  const startRes = await fetchApi(`${SUPER_AGENT_PREFIX}/runs/${runId}/parse-preview/jobs${force}`, {
    method: 'POST',
    headers: buildAuthHeaders(true),
  })
  if (!startRes.ok) {
    const text = await startRes.text().catch(() => '')
    if (startRes.status >= 500 && /Internal Server Error|timeout|ECONNRESET/i.test(text)) {
      throw new Error(
        '材料解析预览失败：后端处理超时或服务异常。若本地 MinerU 未启动，请确认 MINERU_LOCAL_ENABLED 或等待在线解析完成。',
      )
    }
    throw new Error(`材料解析预览失败 ${startRes.status}: ${text}`)
  }
  const startJson = await startRes.json()
  const started = startJson.data as { job: ParsePreviewJob }
  const jobId = started.job.job_id
  options?.onProgress?.(started.job)
  const pollIntervalMs = 2000
  const maxAttempts = 5400 // 3 hours at 2s interval, for slow VLM calibration.
  for (let attempt = 0; attempt < maxAttempts; attempt += 1) {
    await sleep(pollIntervalMs)
    const statusRes = await fetchApi(`${SUPER_AGENT_PREFIX}/runs/${runId}/parse-preview/jobs/${jobId}`, {
      method: 'GET',
      headers: buildAuthHeaders(true),
    })
    if (!statusRes.ok) {
      const text = await statusRes.text().catch(() => '')
      throw new Error(`材料解析预览状态查询失败 ${statusRes.status}: ${text}`)
    }
    const statusJson = await statusRes.json()
    const data = statusJson.data as {
      job: ParsePreviewJob
      preview?: ParsePreviewResponse
      run?: SuperAgentRun
    }
    options?.onProgress?.(data.job)
    if (data.job.status === 'failed') {
      throw new Error(`材料解析预览失败：${data.job.error || data.job.message || '后台任务失败'}`)
    }
    if (data.job.status === 'completed' && data.preview && data.run) {
      return {
        preview: data.preview,
        run: { ...data.run, parse_preview: data.preview },
      }
    }
  }
  throw new Error('材料解析预览仍在后台运行（已等待约 3 小时），请稍后刷新当前 Run 查看结果。')
}

export async function runSuperAgentBenchmark(): Promise<SuperAgentBenchmarkReport> {
  return fetchApiJson<SuperAgentBenchmarkReport>(`${SUPER_AGENT_PREFIX}/benchmarks/builtin`, {
    method: 'POST',
  })
}

export async function getSuperAgentGncStatus(runId: string): Promise<SuperAgentGncStatus> {
  return fetchApiJson<SuperAgentGncStatus>(`${SUPER_AGENT_PREFIX}/runs/${runId}/gnc/status`)
}

export async function getSuperAgentGncResult(runId: string): Promise<Record<string, unknown>> {
  return fetchApiJson<Record<string, unknown>>(`${SUPER_AGENT_PREFIX}/runs/${runId}/gnc/result`)
}

export async function classifyMaterials(files: File[]): Promise<MaterialClassification> {
  const formData = new FormData()
  files.forEach((f) => formData.append('files', f))
  const res = await fetchApi(`${SUPER_AGENT_PREFIX}/classify`, {
    method: 'POST',
    body: formData,
    headers: buildAuthHeaders(false),
  })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`材料识别失败 ${res.status}: ${text}`)
  }
  const json = await res.json()
  return json.data as MaterialClassification
}

export async function parseMaterialsPreview(
  files: File[],
  processingMode = 'OPTIMAL',
  objective = '',
  knownClassification?: MaterialClassification | null,
  options?: { parserType?: string; mineruParseMode?: string },
): Promise<ParsePreviewResponse> {
  const formData = new FormData()
  files.forEach((f) => formData.append('files', f))
  formData.append('processing_mode', processingMode)
  formData.append('objective', objective)
  formData.append('parser_type', options?.parserType || 'auto')
  if (options?.mineruParseMode) {
    formData.append('mineru_parse_mode', options.mineruParseMode)
  }
  if (knownClassification) {
    formData.append('known_classification_json', JSON.stringify(knownClassification))
  }
  const res = await fetchApi(`${SUPER_AGENT_PREFIX}/parse-preview`, {
    method: 'POST',
    body: formData,
    headers: buildAuthHeaders(false),
  })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    if (res.status >= 500 && /Internal Server Error|socket hang up|ECONNRESET|ECONNREFUSED/i.test(text)) {
      throw new Error('材料解析预览失败：后端服务不可用或正在重启，请确认 ./scripts/dev.sh restart 后端已稳定运行')
    }
    throw new Error(`材料解析预览失败 ${res.status}: ${text}`)
  }
  const json = await res.json()
  return json.data as ParsePreviewResponse
}

export async function fetchSourceFileBlob(sourceDownloadUrl: string): Promise<Blob> {
  const res = await fetchApi(sourceDownloadUrl, { method: 'GET' })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`原文下载失败 ${res.status}: ${text}`)
  }
  return res.blob()
}

export async function fetchFigureImageBlob(imageUrl: string): Promise<Blob> {
  const res = await fetchApi(imageUrl, { method: 'GET' })
  if (!res.ok) {
    const text = await res.text().catch(() => '')
    throw new Error(`图块图片下载失败 ${res.status}: ${text}`)
  }
  return res.blob()
}
