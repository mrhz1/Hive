import { createFileRoute, useNavigate } from '@tanstack/react-router'
import { useMemo, useState } from 'react'
import { ConfirmDeleteModal } from '@/components/ConfirmDeleteModal'
import { DataTable, type Column } from '@/components/DataTable'
import { Can, RequirePermission } from '@/components/PermissionGate'
import { Button } from '@/components/ui/Button'
import { TextField } from '@/components/ui/Field'
import { Badge, PageHeader } from '@/components/ui/Misc'
import { usePermissions } from '@/hooks/useCurrentUser'
import { useDeleteDialog } from '@/hooks/useDeleteDialog'
import { useDocumentTitle } from '@/hooks/useDocumentTitle'
import { userHooks } from '@/hooks/useResources'
import type { User } from '@/schemas/user'

const columns: Array<Column<User>> = [
  {
    id: 'username',
    header: 'Username',
    cell: (user) => <span className="font-semibold">{user.username}</span>,
    sortValue: (user) => user.username,
  },
  // First and last name share one column: with Username, Email, Role,
  // Status and Actions, splitting them pushes the table past the content
  // width and the pinned Actions column starts covering Status.
  {
    id: 'name',
    header: 'Name',
    cell: (user) => `${user.first_name} ${user.last_name}`,
    sortValue: (user) => `${user.first_name} ${user.last_name}`,
  },
  {
    id: 'email',
    header: 'Email',
    cell: (user) => user.email,
    sortValue: (user) => user.email,
  },
  {
    id: 'role',
    header: 'Role',
    cell: (user) =>
      user.role_name ? (
        <Badge tone="info">{user.role_name}</Badge>
      ) : (
        <Badge tone="warning">No role</Badge>
      ),
    // Sorts on the underlying name, not the rendered badge; users with
    // no role fall to the end via the null handling in compare().
    sortValue: (user) => user.role_name,
  },
  {
    id: 'status',
    header: 'Status',
    // Only qualify the status when it disagrees with is_active -- an
    // inactive user whose status already reads "inactive" does not need
    // "inactive (inactive)".
    cell: (user) => (
      <Badge tone={user.is_active ? 'success' : 'danger'}>
        {user.is_active || user.status === 'inactive'
          ? user.status
          : `${user.status} (inactive)`}
      </Badge>
    ),
    sortValue: (user) => user.status,
  },
  {
    id: 'created',
    header: 'Created',
    cell: (user) => (
      <span className="text-[rgb(var(--foreground-muted))]">
        {user.created_at.slice(0, 10)}
      </span>
    ),
    sortValue: (user) => user.created_at,
  },
]

function UsersList() {
  useDocumentTitle('Users')

  const navigate = useNavigate()
  const { can } = usePermissions()
  const [search, setSearch] = useState('')

  const { data, isLoading, isFetching, error } = userHooks.useList()
  const remove = userHooks.useRemove()

  const deleteDialog = useDeleteDialog<User>((user) => remove.mutateAsync(user.id))

  // Filtering is client side because the API returns whole collections;
  // it costs no extra Hive query.
  const filtered = useMemo(() => {
    const term = search.trim().toLowerCase()
    if (!term) return data
    return (data ?? []).filter((user) =>
      [user.username, user.first_name, user.last_name, user.email]
        .join(' ')
        .toLowerCase()
        .includes(term)
    )
  }, [data, search])

  // Without this the table would render an empty "Actions" column for a
  // read-only user, since every button inside it is permission-gated.
  const canModify = can('user:update') || can('user:delete')

  return (
    <div className="space-y-6">
      <PageHeader
        title="User Management"
        description="Review and manage dashboard users."
        actions={
          <Can permission="user:create">
            <Button onClick={() => void navigate({ to: '/users/new' })}>Add User</Button>
          </Can>
        }
      />

      <div className="flex flex-wrap items-center justify-between gap-4 rounded-lg border border-[rgb(var(--border))] bg-[rgb(var(--surface))] p-4">
        <TextField
          label="Search"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="Search by name, username or email..."
          aria-label="Search users"
        />
      </div>

      <DataTable
        data={filtered}
        columns={columns}
        getRowId={(user) => user.id}
        isLoading={isLoading}
        isFetching={isFetching}
        error={error}
        loadingLabel="Loading users"
        emptyMessage="No users found."
        rowActions={
          canModify
            ? (user) => (
                <>
                  <Can permission="user:update">
                    <Button
                      size="sm"
                      aria-label={`Edit ${user.username}`}
                      onClick={() =>
                        void navigate({
                          to: '/users/$userId/edit',
                          params: { userId: user.id },
                        })
                      }
                    >
                      Edit
                    </Button>
                  </Can>
                  <Can permission="user:delete">
                    <Button
                      size="sm"
                      variant="danger"
                      aria-label={`Delete ${user.username}`}
                      onClick={() => deleteDialog.request(user)}
                    >
                      Delete
                    </Button>
                  </Can>
                </>
              )
            : undefined
        }
      />

      <ConfirmDeleteModal
        open={deleteDialog.isOpen}
        entityLabel="User"
        targetName={
          deleteDialog.target
            ? `${deleteDialog.target.first_name} ${deleteDialog.target.last_name}`
            : undefined
        }
        isDeleting={deleteDialog.isDeleting}
        onCancel={deleteDialog.cancel}
        onConfirm={() => void deleteDialog.confirm()}
      />
    </div>
  )
}

export const Route = createFileRoute('/users/')({
  component: () => (
    <RequirePermission permission="user:view">
      <UsersList />
    </RequirePermission>
  ),
})
