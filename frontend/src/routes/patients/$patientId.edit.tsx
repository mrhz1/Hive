import { createFileRoute } from '@tanstack/react-router'
import { NotFoundPage } from '@/components/ErrorPages'
import { RequirePermission } from '@/components/PermissionGate'
import { PageHeader } from '@/components/ui/Misc'
import { LoadingBlock } from '@/components/ui/Spinner'
import { PatientForm } from '@/features/patients/PatientForm'
import { useDocumentTitle } from '@/hooks/useDocumentTitle'
import { patientHooks } from '@/hooks/useResources'
import { ApiError } from '@/lib/api/client'
import { patientName } from '@/schemas/patient'

function EditPatient() {
  const { patientId } = Route.useParams()
  const { data: patient, isLoading, error } = patientHooks.useDetail(patientId)

  useDocumentTitle(patient ? `Edit ${patientName(patient)}` : 'Edit patient')

  if (isLoading) return <LoadingBlock label="Loading patient" />
  if (error instanceof ApiError && error.isNotFound) return <NotFoundPage />
  if (!patient) return <NotFoundPage />

  return (
    <div className="space-y-6">
      <PageHeader
        title={`Edit ${patientName(patient)}`}
        description="Update this patient's details."
      />
      <PatientForm patient={patient} />
    </div>
  )
}

export const Route = createFileRoute('/patients/$patientId/edit')({
  component: () => (
    <RequirePermission permission="patients:update">
      <EditPatient />
    </RequirePermission>
  ),
})
