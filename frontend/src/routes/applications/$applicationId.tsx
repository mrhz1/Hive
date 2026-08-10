import { createFileRoute } from '@tanstack/react-router'
import { NotFoundPage } from '@/components/ErrorPages'
import { RequirePermission } from '@/components/PermissionGate'
import { LoadingBlock } from '@/components/ui/Spinner'
import { ApplicationWizard } from '@/features/applications/ApplicationWizard'
import { useDocumentTitle } from '@/hooks/useDocumentTitle'
import { patientHooks, useApplication } from '@/hooks/useResources'
import { ApiError } from '@/lib/api/client'

function ApplicationDetail() {
  const { applicationId } = Route.useParams()
  useDocumentTitle('Application')

  const applicationQuery = useApplication(applicationId)
  const application = applicationQuery.data

  const patientQuery = patientHooks.useDetail(application?.patient_id ?? '', {
    enabled: Boolean(application?.patient_id),
  })

  if (applicationQuery.isLoading || patientQuery.isLoading) {
    return <LoadingBlock label="Loading application" />
  }
  if (applicationQuery.error instanceof ApiError && applicationQuery.error.isNotFound) {
    return <NotFoundPage />
  }
  if (!application) return <NotFoundPage />

  return (
    <ApplicationWizard
      application={application}
      {...(patientQuery.data ? { initialPatient: patientQuery.data } : {})}
    />
  )
}

export const Route = createFileRoute('/applications/$applicationId')({
  component: () => (
    <RequirePermission permission="application:view">
      <ApplicationDetail />
    </RequirePermission>
  ),
})
