import type { WorkflowStepStatus } from '@aqua/workflow-core'
import type { ParsePreviewResponse, SuperAgentRun, SuperAgentSkillTrace } from '@/features/super-agent/types'
import { sanitizeBusinessReportText } from '@/features/super-agent/utils/diagnosticsSanitizer'
import { AGENT_RUN_STATUS_LABELS, ROUTE_LABELS, formatElapsedMs } from '@/lib/aeroTerminology'

export type ComprehensiveReviewMessageRole = 'user' | 'assistant' | 'tool' | 'result'

export interface ComprehensiveReviewMessage {
  id: string
  role: ComprehensiveReviewMessageRole
  title: string
  body: string
  status?: WorkflowStepStatus
  chips?: string[]
}

export type ManualComprehensiveReviewMessage = ComprehensiveReviewMessage & {
  source: 'manual'
}

export function createChatMessage(
  role: ComprehensiveReviewMessageRole,
  title: string,
  body: string,
  options?: Pick<ComprehensiveReviewMessage, 'status' | 'chips'>,
): ManualComprehensiveReviewMessage {
  return {
    id: `chat-${Date.now()}-${Math.random().toString(16).slice(2)}`,
    source: 'manual',
    role,
    title,
    body,
    ...options,
  }
}

export function buildAgentReply(params: {
  text: string
  files: File[]
  preview?: ParsePreviewResponse | null
  run?: SuperAgentRun | null
  canResume?: boolean
  mineruLabel?: string
}): ManualComprehensiveReviewMessage {
  const { files, preview, run, canResume, mineruLabel } = params
  if (!files.length) {
    return createChatMessage(
      'assistant',
      '综合审查 Agent',
      '请先在聊天框附加一个或多个文件。我会先按 .env 中配置的 MinerU 模式解析为 Markdown，再启动综合审查。',
      { status: 'awaiting_confirm', chips: ['等待文件', mineruLabel].filter((chip): chip is string => Boolean(chip)) },
    )
  }
  if (canResume) {
    return createChatMessage(
      'assistant',
      '综合审查 Agent',
      '当前审查处于中断或停滞状态。你可以点击“继续审查”恢复执行，或点击“中断审查”结束当前前端会话。',
      { status: 'interrupted', chips: ['可恢复'] },
    )
  }
  if (run?.status === 'running') {
    return createChatMessage(
      'assistant',
      '综合审查 Agent',
      '审查正在执行中，我会持续刷新并把各个审查节点返回到对话里。',
      { status: 'running', chips: ['执行中'] },
    )
  }
  if (run?.status === 'completed') {
    return createChatMessage(
      'assistant',
      '综合审查 Agent',
      '综合审查已完成，最终报告已在对话中生成。你可以继续上传新文件发起下一轮审查。',
      { status: 'completed', chips: ['已完成'] },
    )
  }
  if (preview) {
    return createChatMessage(
      'assistant',
      '综合审查 Agent',
      '材料已经完成 Markdown 解析，正在准备或已经进入综合审查流程。',
      { status: 'running', chips: ['Markdown 已就绪'] },
    )
  }
  return createChatMessage(
    'assistant',
    '综合审查 Agent',
    '收到。我会以你刚才的消息作为审查目标，先解析附件，再启动 GNC 与文件组综合审查。',
    { status: 'running', chips: ['准备启动'] },
  )
}

function statusFromTrace(trace: SuperAgentSkillTrace): WorkflowStepStatus {
  if (trace.status === 'completed') return 'completed'
  if (trace.status === 'failed') return 'failed'
  if (trace.status === 'running') return 'running'
  return 'pending'
}

function traceTitle(trace: SuperAgentSkillTrace): string {
  const titles: Record<string, string> = {
    bootstrap_review_plus_task: '建立文件组审查任务',
    structure_materials: '结构化 Markdown 材料',
    run_review_plus: '执行文件组审查',
    run_gnc_review: '执行 GNC 审查',
    gnc_committee_review: 'GNC 专家委员会审查',
    gnc_cross_document_consistency: 'GNC 跨文档一致性检查',
    collect_traces: '汇总审查轨迹',
    evaluate_quality: '评估审查质量',
  }
  return titles[trace.skill_id] || trace.tool_name || trace.skill_id
}

function summarizeTrace(trace: SuperAgentSkillTrace): string {
  const output = trace.output_summary || {}
  const warnings = trace.warnings || []
  const fields = Object.entries(output)
    .slice(0, 4)
    .map(([key, value]) => `${key}: ${typeof value === 'object' ? JSON.stringify(value).slice(0, 120) : String(value)}`)
  if (warnings.length) fields.push(`提示: ${warnings.slice(0, 2).join('；')}`)
  return fields.join('\n') || '节点已更新。'
}

export function buildComprehensiveReviewMessages(params: {
  manualMessages?: ComprehensiveReviewMessage[]
  files: File[]
  preview?: ParsePreviewResponse | null
  run?: SuperAgentRun | null
  error?: string
  mineruLabel?: string
}): ComprehensiveReviewMessage[] {
  const messages: ComprehensiveReviewMessage[] = [...(params.manualMessages || [])]
  const { files, preview, run, error } = params

  if (files.length) {
    messages.push({
      id: 'user-files',
      role: 'user',
      title: '已上传材料',
      body: files.map((file) => `- ${file.name}`).join('\n'),
      status: 'completed',
      chips: [`${files.length} 个文件`],
    })
  } else if (run?.materials?.length) {
    messages.push({
      id: 'persisted-materials',
      role: 'user',
      title: '历史材料',
      body: run.materials.map((item) => `- ${item.name || item.file_path || '未命名文件'}`).join('\n'),
      status: 'completed',
      chips: [`${run.materials.length} 个文件`, '已保存'],
    })
  }

  if (preview) {
    const parsedOk = preview.summary?.parsed_ok ?? 0
    const materialCount = preview.summary?.material_count ?? preview.materials.length
    const recommendedRoute = preview.classification?.recommended_route || 'auto'
    messages.push({
      id: 'mineru-preview',
      role: 'tool',
      title: 'MinerU 解析完成',
      body: preview.materials
        .map((item) => `- ${item.file_name} → ${item.content_markdown ? 'Markdown 已生成' : item.parse_status || '已解析'}`)
        .join('\n'),
      status: parsedOk === materialCount ? 'completed' : 'running',
      chips: [
        params.mineruLabel || 'MinerU',
        `成功 ${parsedOk}/${materialCount}`,
        `推荐路由: ${ROUTE_LABELS[recommendedRoute] || recommendedRoute}`,
      ],
    })
  }

  if (run) {
    messages.push({
      id: `run-${run.run_id}`,
      role: 'assistant',
      title: '综合审查已启动',
      body: `任务 ${run.name || run.run_id} 当前状态：${AGENT_RUN_STATUS_LABELS[run.status] || run.status}`,
      status: run.status === 'completed' ? 'completed' : run.status === 'failed' ? 'failed' : run.status === 'interrupted' ? 'interrupted' : 'running',
      chips: [ROUTE_LABELS[run.requested_route] || run.requested_route, run.review_mode],
    })

    for (const [index, trace] of (run.skill_traces || []).entries()) {
      messages.push({
        id: `trace-${index}-${trace.skill_id}-${trace.elapsed_ms}-${trace.status}`,
        role: 'tool',
        title: traceTitle(trace),
        body: summarizeTrace(trace),
        status: statusFromTrace(trace),
        chips: [trace.agent_id || 'system', formatElapsedMs(trace.elapsed_ms)],
      })
    }

    if (run.report_markdown) {
      messages.push({
        id: 'final-report',
        role: 'result',
        title: '综合审查报告',
        body: sanitizeBusinessReportText(run.report_markdown),
        status: 'completed',
        chips: ['最终报告'],
      })
    }
  }

  if (error) {
    messages.push({
      id: 'error',
      role: 'assistant',
      title: '处理失败',
      body: error,
      status: 'failed',
    })
  }

  return messages
}
