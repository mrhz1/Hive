import { createFileRoute } from '@tanstack/react-router'
import { RequirePermission } from '@/components/PermissionGate'
import { ApplicationWizard } from '@/features/applications/ApplicationWizard'
import { useDocumentTitle } from '@/hooks/useDocumentTitle'

function NewApplication() {
  useDocumentTitle('New application')
  return <ApplicationWizard />
}

export const Route = createFileRoute('/applications/new')({
  component: () => (
    <RequirePermission permission="application:create">
      <RequirePermission permission="patient:create">
        <NewApplication />
      </RequirePermission>
    </RequirePermission>
  ),
})
