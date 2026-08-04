import { createFileRoute } from '@tanstack/react-router'
import { NotFoundPage } from '@/components/ErrorPages'
import { RequirePermission } from '@/components/PermissionGate'
import { PageHeader } from '@/components/ui/Misc'
import { LoadingBlock } from '@/components/ui/Spinner'
import { UserForm } from '@/features/users/UserForm'
import { useDocumentTitle } from '@/hooks/useDocumentTitle'
import { userHooks } from '@/hooks/useResources'
import { ApiError } from '@/lib/api/client'

function EditUser() {
  const { userId } = Route.useParams()
  const { data: user, isLoading, error } = userHooks.useDetail(userId)

  useDocumentTitle(user ? `Edit ${user.username}` : 'Edit user')

  if (isLoading) return <LoadingBlock label="Loading user" />
  if (error instanceof ApiError && error.isNotFound) return <NotFoundPage />
  if (!user) return <NotFoundPage />

  return (
    <div className="space-y-6">
      <PageHeader
        title={`Edit ${user.username}`}
        description="Update this user's details or role."
      />
      <UserForm user={user} />
    </div>
  )
}

export const Route = createFileRoute('/users/$userId/edit')({
  component: () => (
    <RequirePermission permission="users:update">
      <EditUser />
    </RequirePermission>
  ),
})
