'use client'

import { createContext, useContext, useMemo, useState, type ReactNode } from 'react'
import type { UnifiedWorkbenchTabKey } from '@/features/unified-review-workbench/types'

export interface GncWorkbenchLinkState {
  selectedFindingId: string
  selectedEvidenceId: string
  selectedRidId: string
  selectedCommitteeGroupKey: string
  selectedCommitteeStageKey: string
  selectedCommitteeUnitKey: string
  setSelectedFindingId: (id: string) => void
  setSelectedEvidenceId: (id: string) => void
  setSelectedRidId: (id: string) => void
  setSelectedCommitteeGroupKey: (groupKey: string) => void
  setSelectedCommitteeStageKey: (stageKey: string) => void
  setSelectedCommitteeUnitKey: (unitKey: string) => void
  openLinkedTab: (tab: UnifiedWorkbenchTabKey) => void
}

const GncWorkbenchLinkContext = createContext<GncWorkbenchLinkState | null>(null)

export function GncWorkbenchLinkProvider({
  children,
  onOpenTab,
}: {
  children: ReactNode
  onOpenTab: (tab: UnifiedWorkbenchTabKey) => void
}) {
  const [selectedFindingId, setSelectedFindingId] = useState('')
  const [selectedEvidenceId, setSelectedEvidenceId] = useState('')
  const [selectedRidId, setSelectedRidId] = useState('')
  const [selectedCommitteeGroupKey, setSelectedCommitteeGroupKey] = useState('')
  const [selectedCommitteeStageKey, setSelectedCommitteeStageKey] = useState('')
  const [selectedCommitteeUnitKey, setSelectedCommitteeUnitKey] = useState('')

  const value = useMemo(
    () => ({
      selectedFindingId,
      selectedEvidenceId,
      selectedRidId,
      selectedCommitteeGroupKey,
      selectedCommitteeStageKey,
      selectedCommitteeUnitKey,
      setSelectedFindingId,
      setSelectedEvidenceId,
      setSelectedRidId,
      setSelectedCommitteeGroupKey,
      setSelectedCommitteeStageKey,
      setSelectedCommitteeUnitKey,
      openLinkedTab: onOpenTab,
    }),
    [
      onOpenTab,
      selectedCommitteeGroupKey,
      selectedCommitteeStageKey,
      selectedCommitteeUnitKey,
      selectedEvidenceId,
      selectedFindingId,
      selectedRidId,
    ],
  )

  return <GncWorkbenchLinkContext.Provider value={value}>{children}</GncWorkbenchLinkContext.Provider>
}

export function useGncWorkbenchLink(): GncWorkbenchLinkState {
  const ctx = useContext(GncWorkbenchLinkContext)
  if (!ctx) {
    throw new Error('useGncWorkbenchLink must be used within GncWorkbenchLinkProvider')
  }
  return ctx
}

export function useOptionalGncWorkbenchLink(): GncWorkbenchLinkState | null {
  return useContext(GncWorkbenchLinkContext)
}
