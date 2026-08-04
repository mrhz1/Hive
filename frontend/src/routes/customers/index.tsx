import { createFileRoute, useNavigate } from '@tanstack/react-router'
import { FileText } from 'lucide-react'
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
import { customerHooks } from '@/hooks/useResources'
import type { Customer } from '@/schemas/customer'

const columns: Array<Column<Customer>> = [
  // Combined for the same reason as the users table -- see the note there.
  {
    id: 'name',
    header: 'Name',
    cell: (c) => `${c.first_name} ${c.last_name}`,
    sortValue: (c) => `${c.first_name} ${c.last_name}`,
  },
  { id: 'email', header: 'Email', cell: (c) => c.email, sortValue: (c) => c.email },
  {
    id: 'phone',
    header: 'Phone',
    cell: (c) => c.phone_number,
    sortValue: (c) => c.phone_number,
  },
  {
    id: 'address',
    header: 'Address',
    cell: (c) => (
      <span className="text-[rgb(var(--foreground-muted))]">{c.address || '—'}</span>
    ),
    sortValue: (c) => c.address,
  },
  {
    id: 'status',
    header: 'Status',
    cell: (c) => (
      <Badge tone={c.is_active ? 'success' : 'danger'}>
        {c.is_active || c.status === 'inactive' ? c.status : `${c.status} (inactive)`}
      </Badge>
    ),
    sortValue: (c) => c.status,
  },
]

function CustomersList() {
  useDocumentTitle('Customers')

  const navigate = useNavigate()
  const { can } = usePermissions()
  const [search, setSearch] = useState('')

  const { data, isLoading, isFetching, error } = customerHooks.useList()
  const remove = customerHooks.useRemove()

  const deleteDialog = useDeleteDialog<Customer>((customer) =>
    remove.mutateAsync(customer.id)
  )

  const filtered = useMemo(() => {
    const term = search.trim().toLowerCase()
    if (!term) return data
    return (data ?? []).filter((customer) =>
      [customer.first_name, customer.last_name, customer.email, customer.phone_number]
        .join(' ')
        .toLowerCase()
        .includes(term)
    )
  }, [data, search])

  const canModify = can('customers:update') || can('customers:delete')

  return (
    <div className="space-y-6">
      <PageHeader
        title="Customer Management"
        description="Customer records held in Hive."
        actions={
          <Can permission="customers:create">
            <Button onClick={() => void navigate({ to: '/customers/new' })}>
              Add Customer
            </Button>
          </Can>
        }
      />

      <div className="flex flex-wrap items-center justify-between gap-4 rounded-lg border border-[rgb(var(--border))] bg-[rgb(var(--surface))] p-4">
        <TextField
          label="Search"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="Search by name, email or phone..."
          aria-label="Search customers"
        />
      </div>

      <DataTable
        data={filtered}
        columns={columns}
        getRowId={(customer) => customer.id}
        isLoading={isLoading}
        isFetching={isFetching}
        error={error}
        loadingLabel="Loading customers"
        emptyMessage="No customers found."
        rowActions={(customer) => (
          <>
            {/* Files is available to anyone who can read customers, so
                this column renders even for a read-only role. */}
            <Button
              size="sm"
              variant="secondary"
              aria-label={`Files for ${customer.email}`}
              leadingIcon={<FileText className="size-3.5" aria-hidden="true" />}
              onClick={() =>
                void navigate({
                  to: '/customers/$customerId/files',
                  params: { customerId: customer.id },
                })
              }
            >
              Files
            </Button>
            {canModify ? (
              <>
                <Can permission="customers:update">
                  <Button
                    size="sm"
                    aria-label={`Edit ${customer.email}`}
                    onClick={() =>
                      void navigate({
                        to: '/customers/$customerId/edit',
                        params: { customerId: customer.id },
                      })
                    }
                  >
                    Edit
                  </Button>
                </Can>
                <Can permission="customers:delete">
                  <Button
                    size="sm"
                    variant="danger"
                    aria-label={`Delete ${customer.email}`}
                    onClick={() => deleteDialog.request(customer)}
                  >
                    Delete
                  </Button>
                </Can>
              </>
            ) : null}
          </>
        )}
      />

      <ConfirmDeleteModal
        open={deleteDialog.isOpen}
        entityLabel="Customer"
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

export const Route = createFileRoute('/customers/')({
  component: () => (
    <RequirePermission permission="customers:read">
      <CustomersList />
    </RequirePermission>
  ),
})
