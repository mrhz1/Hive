import { createFileRoute } from '@tanstack/react-router'
import { RequirePermission } from '@/components/PermissionGate'
import { ApplicationWizard } from '@/features/applications/ApplicationWizard'
import { useDocumentTitle } from '@/hooks/useDocumentTitle'

function NewApplication() {
  useDocumentTitle('New application')
  return <ApplicationWizard />
}

export const Route = createFileRoute('/applications/new')({
  // Step 1 creates a patient, so the wizard needs that grant too -- the
  // stricter of the two is what the page is gated on.
  component: () => (
    <RequirePermission permission="application:create">
      <RequirePermission permission="patient:create">
        <NewApplication />
      </RequirePermission>
    </RequirePermission>
  ),
})
