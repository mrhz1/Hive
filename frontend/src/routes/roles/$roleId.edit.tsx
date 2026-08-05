import { createFileRoute } from '@tanstack/react-router'
import { NotFoundPage } from '@/components/ErrorPages'
import { RequirePermission } from '@/components/PermissionGate'
import { PageHeader } from '@/components/ui/Misc'
import { LoadingBlock } from '@/components/ui/Spinner'
import { RoleForm } from '@/features/roles/RoleForm'
import { useDocumentTitle } from '@/hooks/useDocumentTitle'
import { roleHooks } from '@/hooks/useResources'
import { ApiError } from '@/lib/api/client'

function EditRole() {
  const { roleId } = Route.useParams()
  const { data: role, isLoading, error } = roleHooks.useDetail(roleId)

  useDocumentTitle(role ? `Edit ${role.name}` : 'Edit role')

  if (isLoading) return <LoadingBlock label="Loading role" />
  if (error instanceof ApiError && error.isNotFound) return <NotFoundPage />
  if (!role) return <NotFoundPage />

  return (
    <div className="space-y-6">
      <PageHeader
        title={`Edit ${role.name}`}
        description="Change this role's permissions."
      />
      <RoleForm role={role} />
    </div>
  )
}

export const Route = createFileRoute('/roles/$roleId/edit')({
  component: () => (
    <RequirePermission permission="role:update">
      <EditRole />
    </RequirePermission>
  ),
})
