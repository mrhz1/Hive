import { createFileRoute, useNavigate } from '@tanstack/react-router'
import { ConfirmDeleteModal } from '@/components/ConfirmDeleteModal'
import { DataTable, type Column } from '@/components/DataTable'
import { Can, RequirePermission } from '@/components/PermissionGate'
import { Button } from '@/components/ui/Button'
import { Badge, PageHeader } from '@/components/ui/Misc'
import { usePermissions } from '@/hooks/useCurrentUser'
import { useDeleteDialog } from '@/hooks/useDeleteDialog'
import { useDocumentTitle } from '@/hooks/useDocumentTitle'
import { roleHooks } from '@/hooks/useResources'
import type { Role } from '@/schemas/role'

const columns: Array<Column<Role>> = [
  {
    id: 'name',
    header: 'Name',
    cell: (role) => <span className="font-semibold">{role.name}</span>,
    sortValue: (role) => role.name,
  },
  {
    id: 'count',
    header: 'Grants',
    isNumeric: true,
    cell: (role) => role.permissions.length,
    sortValue: (role) => role.permissions.length,
  },
  {
    id: 'permissions',
    header: 'Permissions',
    cell: (role) =>
      role.permissions.length === 0 ? (
        <span className="text-[rgb(var(--foreground-muted))]">None</span>
      ) : (
        <div className="flex flex-wrap gap-1">
          {role.permissions.slice(0, 6).map((permission) => (
            <Badge key={permission}>{permission}</Badge>
          ))}
          {role.permissions.length > 6 ? (
            <Badge tone="info">+{role.permissions.length - 6} more</Badge>
          ) : null}
        </div>
      ),
  },
]

function RolesList() {
  useDocumentTitle('Roles')

  const navigate = useNavigate()
  const { can } = usePermissions()

  const { data, isLoading, isFetching, error } = roleHooks.useList()
  const remove = roleHooks.useRemove()

  const deleteDialog = useDeleteDialog<Role>((role) => remove.mutateAsync(role.id))

  const canModify = can('role:update') || can('role:delete')

  return (
    <div className="space-y-6">
      <PageHeader
        title="Role Management"
        description="Permission sets assigned to users."
        actions={
          <Can permission="role:create">
            <Button onClick={() => void navigate({ to: '/roles/new' })}>Add Role</Button>
          </Can>
        }
      />

      <DataTable
        data={data}
        columns={columns}
        getRowId={(role) => role.id}
        isLoading={isLoading}
        isFetching={isFetching}
        error={error}
        loadingLabel="Loading roles"
        emptyMessage="No roles found."
        rowActions={
          canModify
            ? (role) => (
                <>
                  <Can permission="role:update">
                    <Button
                      size="sm"
                      aria-label={`Edit ${role.name}`}
                      onClick={() =>
                        void navigate({
                          to: '/roles/$roleId/edit',
                          params: { roleId: role.id },
                        })
                      }
                    >
                      Edit
                    </Button>
                  </Can>
                  <Can permission="role:delete">
                    <Button
                      size="sm"
                      variant="danger"
                      aria-label={`Delete ${role.name}`}
                      onClick={() => deleteDialog.request(role)}
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
        entityLabel="Role"
        targetName={deleteDialog.target?.name}
        isDeleting={deleteDialog.isDeleting}
        onCancel={deleteDialog.cancel}
        onConfirm={() => void deleteDialog.confirm()}
      />
    </div>
  )
}

export const Route = createFileRoute('/roles/')({
  component: () => (
    <RequirePermission permission="role:view">
      <RolesList />
    </RequirePermission>
  ),
})
