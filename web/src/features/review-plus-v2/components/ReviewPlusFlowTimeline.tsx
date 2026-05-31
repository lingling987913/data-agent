'use client'

import { WorkflowDAGViewer } from '@aqua/workflow-core'
import { buildReviewPlusWorkflowGraph, resolveActiveWorkflowStepKey } from '@/features/review-plus-v2/utils/reviewPlusWorkflowGraph'
import type { ReviewPlusTaskDetail } from '@/features/review-plus-v2/types'

interface Props {
  task: ReviewPlusTaskDetail
  onSelectStep?: (stepKey: string) => void
}

export default function ReviewPlusFlowTimeline({ task, onSelectStep }: Props) {
  const graph = buildReviewPlusWorkflowGraph(task)
  const activeStepKey = resolveActiveWorkflowStepKey(task)

  return (
    <WorkflowDAGViewer
      className="h-full min-h-[420px]"
      graph={graph}
      mode="live"
      activeNodeId={activeStepKey ? `node_${activeStepKey}` : undefined}
      onSelectNode={onSelectStep ? (nodeId) => onSelectStep(nodeId.replace(/^node_/, '')) : undefined}
      defaultAutoLayoutVariant="horizontal"
    />
  )
}
