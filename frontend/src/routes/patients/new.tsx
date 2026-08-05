import { createFileRoute } from '@tanstack/react-router'
import { RequirePermission } from '@/components/PermissionGate'
import { PageHeader } from '@/components/ui/Misc'
import { PatientForm } from '@/features/patients/PatientForm'
import { useDocumentTitle } from '@/hooks/useDocumentTitle'

function NewPatient() {
  useDocumentTitle('New patient')
  return (
    <div className="space-y-6">
      <PageHeader title="New patient" description="Add a patient record." />
      <PatientForm />
    </div>
  )
}

export const Route = createFileRoute('/patients/new')({
  component: () => (
    <RequirePermission permission="patient:create">
      <NewPatient />
    </RequirePermission>
  ),
})
