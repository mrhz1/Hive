import { createFileRoute } from '@tanstack/react-router'
import { RequirePermission } from '@/components/PermissionGate'
import { PageHeader } from '@/components/ui/Misc'
import { RoleForm } from '@/features/roles/RoleForm'
import { useDocumentTitle } from '@/hooks/useDocumentTitle'

function NewRole() {
  useDocumentTitle('New role')
  return (
    <div className="space-y-6">
      <PageHeader title="New role" description="Define a set of permissions." />
      <RoleForm />
    </div>
  )
}

export const Route = createFileRoute('/roles/new')({
  component: () => (
    <RequirePermission permission="roles:create">
      <NewRole />
    </RequirePermission>
  ),
})
