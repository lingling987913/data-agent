export type ReviewProcessStatus =
  | 'pending'
  | 'running'
  | 'completed'
  | 'failed'
  | 'skipped'
  | 'awaiting_confirm'
  | 'blocked'

export type ReviewProcessKind = 'gnc' | 'review_plus' | 'smart_committee' | 'hybrid' | 'generic'

export interface ReviewProcessStep {
  stepKey: string
  label: string
  status: ReviewProcessStatus
  subtitle?: string
  summary?: string
  error?: string
  durationMs?: number | null
  isCurrent?: boolean
  conditionalNote?: string
}

export interface ReviewProcessSubflowLane {
  laneKey: string
  label: string
  enabled: boolean
  skipReason?: string
  summary?: string
  verdict?: string
  status: ReviewProcessStatus
  stages: ReviewProcessStep[]
}

export interface ReviewProcessStageDef {
  stageKey: string
  label: string
  description: string
  stepKeys: readonly string[]
  conditionalStepKeys?: readonly string[]
}

export interface ReviewProcessStage {
  stageKey: string
  label: string
  description: string
  status: ReviewProcessStatus
  isCurrent: boolean
  subtitle?: string
  summary?: string
  error?: string
  conditionalNote?: string
  durationMs?: number | null
  stepKeys: string[]
  steps: ReviewProcessStep[]
  subflowLanes?: ReviewProcessSubflowLane[]
  stageIndex: number
  badge?: string
}

export interface ReviewProcessModel {
  processKind: ReviewProcessKind
  title: string
  subtitle?: string
  currentStageLabel: string
  stages: ReviewProcessStage[]
}

export interface ReviewProcessStageView {
  step: ReviewProcessStep
  stepIndex: number
  conditionalNote?: string
}
