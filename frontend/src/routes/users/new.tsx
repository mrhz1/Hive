import { createFileRoute } from '@tanstack/react-router'
import { RequirePermission } from '@/components/PermissionGate'
import { PageHeader } from '@/components/ui/Misc'
import { UserForm } from '@/features/users/UserForm'
import { useDocumentTitle } from '@/hooks/useDocumentTitle'

function NewUser() {
  useDocumentTitle('New user')
  return (
    <div className="space-y-6">
      <PageHeader
        title="New user"
        description="Create a dashboard user and assign a role."
      />
      <UserForm />
    </div>
  )
}

export const Route = createFileRoute('/users/new')({
  component: () => (
    <RequirePermission permission="user:create">
      <NewUser />
    </RequirePermission>
  ),
})
