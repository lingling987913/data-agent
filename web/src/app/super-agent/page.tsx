import { Suspense } from 'react'
import SuperAgentWizardPage from '@/features/super-agent/components/SuperAgentWizardPage'

export default function SuperAgentPage() {
  return (
    <Suspense fallback={null}>
      <SuperAgentWizardPage />
    </Suspense>
  )
}
