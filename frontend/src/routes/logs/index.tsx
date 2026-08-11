import { createFileRoute, useNavigate } from '@tanstack/react-router'
import { useState } from 'react'
import { DataTable, type Column } from '@/components/DataTable'
import { RequirePermission } from '@/components/PermissionGate'
import { Button } from '@/components/ui/Button'
import { SelectField, TextField } from '@/components/ui/Field'
import { Badge, PageHeader } from '@/components/ui/Misc'
import { useDocumentTitle } from '@/hooks/useDocumentTitle'
import { useAuditLogs, userHooks } from '@/hooks/useResources'
import { AUDIT_ACTIONS, type AuditAction, type AuditLog } from '@/schemas/log'

const ACTION_TONE: Record<AuditAction, 'success' | 'info' | 'danger'> = {
  CREATE: 'success',
  UPDATE: 'info',
  DELETE: 'danger',
}

function LogsList() {
  useDocumentTitle('Audit log')

  const navigate = useNavigate()
  const [entityType, setEntityType] = useState('')
  const [entityId, setEntityId] = useState('')
  const [userId, setUserId] = useState('')
  const [action, setAction] = useState('')
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')

  const users = userHooks.useList()
  const nameFor = (id?: string | null) =>
    users.data?.find((user) => user.id === id)?.username ?? id ?? '--'

  const filters = {
    ...(entityType ? { entity_type: entityType } : {}),
    ...(entityId ? { entity_id: entityId } : {}),
    ...(userId ? { user_id: userId } : {}),
    ...(action ? { action } : {}),
    ...(dateFrom ? { date_from: dateFrom } : {}),
    ...(dateTo ? { date_to: dateTo } : {}),
    limit: 200,
  }

  const { data, isLoading, isFetching, error } = useAuditLogs(filters)

  const columns: Array<Column<AuditLog>> = [
    {
      id: 'action',
      header: 'Action',
      cell: (entry) => <Badge tone={ACTION_TONE[entry.action]}>{entry.action}</Badge>,
      sortValue: (entry) => entry.action,
    },
    {
      id: 'entity',
      header: 'Entity',
      cell: (entry) => <span className="font-semibold">{entry.entity_type}</span>,
      sortValue: (entry) => entry.entity_type,
    },
    {
      id: 'entity_id',
      header: 'Record',
      cell: (entry) => (
        <code className="text-xs break-all text-[rgb(var(--foreground-muted))]">
          {entry.entity_id}
        </code>
      ),
      sortValue: (entry) => entry.entity_id,
    },
    {
      id: 'who',
      header: 'Who',
      cell: (entry) => (
        <span className="text-sm font-semibold">{nameFor(entry.user_id)}</span>
      ),
      sortValue: (entry) => entry.user_id ?? '',
    },
    {
      id: 'created',
      header: 'When',
      cell: (entry) => (
        <span className="text-[rgb(var(--foreground-muted))]">{entry.created_at}</span>
      ),
      sortValue: (entry) => entry.created_at,
    },
  ]

  return (
    <div className="space-y-6">
      <PageHeader
        title="Audit Log"
        description="Every create, update and delete recorded by the API. For who *read* or downloaded something, see the Access log."
      />

      <div className="grid gap-4 rounded-lg border border-[rgb(var(--border))] bg-[rgb(var(--surface))] p-4 sm:grid-cols-2 lg:grid-cols-3">
        <SelectField
          label="Entity type"
          placeholder="All types"
          value={entityType}
          onChange={(event) => setEntityType(event.target.value)}
          options={[
            { value: 'user', label: 'user' },
            { value: 'patient', label: 'patient' },
          ]}
        />
        <TextField
          label="Record id"
          placeholder="Filter by entity id"
          value={entityId}
          onChange={(event) => setEntityId(event.target.value)}
        />
        {/* Who and when: the question an access review and an incident
            both start from, and which this page could not be asked. */}
        <SelectField
          label="Who"
          placeholder="Anyone"
          value={userId}
          onChange={(event) => setUserId(event.target.value)}
          options={(users.data ?? []).map((user) => ({
            value: user.id,
            label: user.username,
          }))}
        />
        <SelectField
          label="Action"
          placeholder="Any action"
          value={action}
          onChange={(event) => setAction(event.target.value)}
          options={AUDIT_ACTIONS.map((value) => ({ value, label: value }))}
        />
        <TextField
          label="From"
          type="date"
          value={dateFrom}
          onChange={(event) => setDateFrom(event.target.value)}
        />
        <TextField
          label="To"
          type="date"
          value={dateTo}
          onChange={(event) => setDateTo(event.target.value)}
        />
        <div className="flex items-end">
          <Button
            variant="outline"
            onClick={() => {
              setEntityType('')
              setEntityId('')
              setUserId('')
              setAction('')
              setDateFrom('')
              setDateTo('')
            }}
            disabled={
              !entityType && !entityId && !userId && !action && !dateFrom && !dateTo
            }
          >
            Clear filters
          </Button>
        </div>
      </div>

      <DataTable
        data={data}
        columns={columns}
        getRowId={(entry) => entry.id}
        isLoading={isLoading}
        isFetching={isFetching}
        error={error}
        loadingLabel="Loading audit log"
        emptyMessage="No audit entries found."
        rowActions={(entry) => (
          <Button
            size="sm"
            variant="outline"
            onClick={() =>
              void navigate({ to: '/logs/$logId', params: { logId: entry.id } })
            }
          >
            Details
          </Button>
        )}
      />
    </div>
  )
}

export const Route = createFileRoute('/logs/')({
  component: () => (
    <RequirePermission permission="log:view">
      <LogsList />
    </RequirePermission>
  ),
})
