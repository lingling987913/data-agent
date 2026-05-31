import type { SuperAgentRun } from '@/features/super-agent/types'
import { parsePreviewFromRun } from '@/features/super-agent/utils/superAgentWizardRecovery'
import { COMPREHENSIVE_REVIEW_TERMS } from '@/lib/aeroTerminology'
import {
  createChatMessage,
  type ComprehensiveReviewMessage,
} from '@/features/comprehensive-review/utils/comprehensiveReviewMessages'

export function buildRestoredManualMessages(run: SuperAgentRun): ComprehensiveReviewMessage[] {
  const messages = [
    createChatMessage(
      'assistant',
      '综合审查 Agent',
      '已从历史任务恢复。你可以查看之前的审查进度、节点轨迹与最终报告。',
      { status: 'completed', chips: ['历史任务'] },
    ),
  ]
  if (run.objective?.trim()) {
    messages.push(createChatMessage('user', '你', run.objective.trim(), { status: 'completed' }))
  }
  return messages
}

export function restoreComprehensiveReviewFromRun(run: SuperAgentRun) {
  return {
    objective: run.objective?.trim() || COMPREHENSIVE_REVIEW_TERMS.objectivePlaceholder,
    selectedRoute: run.requested_route,
    preview: parsePreviewFromRun(run),
    run,
    error: run.error || '',
    manualMessages: buildRestoredManualMessages(run),
  }
}
