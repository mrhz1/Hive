import { createFileRoute } from '@tanstack/react-router'
import { useState } from 'react'
import { DataTable, type Column } from '@/components/DataTable'
import { RequirePermission } from '@/components/PermissionGate'
import { Button } from '@/components/ui/Button'
import { CheckboxField, SelectField, TextField } from '@/components/ui/Field'
import { Badge, PageHeader } from '@/components/ui/Misc'
import { useAccessLogs } from '@/hooks/useResources'
import { useDocumentTitle } from '@/hooks/useDocumentTitle'
import {
  ACCESS_ACTIONS,
  accessSummary,
  accessTone,
  type AccessLog,
} from '@/schemas/accessLog'

export const Route = createFileRoute('/access-logs/')({
  component: AccessLogPage,
})

function formatWhen(value: string): string {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}

function AccessLogPage() {
  useDocumentTitle('Access log')

  const [actor, setActor] = useState('')
  const [patientId, setPatientId] = useState('')
  const [action, setAction] = useState('')
  const [identifiedOnly, setIdentifiedOnly] = useState(false)
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')

  const filters = {
    ...(actor ? { actor_username: actor } : {}),
    ...(patientId ? { patient_id: patientId } : {}),
    ...(action ? { action } : {}),
    ...(identifiedOnly ? { identified_only: true } : {}),
    ...(dateFrom ? { date_from: dateFrom } : {}),
    ...(dateTo ? { date_to: dateTo } : {}),
    limit: 500,
  }

  const { data, isLoading, isFetching, error } = useAccessLogs(filters)

  const columns: Array<Column<AccessLog>> = [
    {
      id: 'when',
      header: 'When',
      cell: (entry) => (
        <span className="whitespace-nowrap text-sm">
          {formatWhen(entry.occurred_at)}
        </span>
      ),
      sortValue: (entry) => entry.occurred_at,
    },
    {
      id: 'who',
      header: 'Who',
      cell: (entry) => (
        <div className="min-w-0">
          <span className="block truncate font-semibold">
            {entry.actor_username ?? '(unauthenticated)'}
          </span>
          <span className="block truncate text-xs text-[rgb(var(--foreground-muted))]">
            {entry.source_ip ?? '--'}
          </span>
        </div>
      ),
      sortValue: (entry) => entry.actor_username ?? '',
    },
    {
      id: 'what',
      header: 'What',
      cell: (entry) => (
        <div className="min-w-0">
          <Badge tone={accessTone(entry.action, entry.outcome)}>
            {entry.action}
          </Badge>
          <span className="mt-1 block truncate text-xs text-[rgb(var(--foreground-muted))]">
            {accessSummary(entry)}
          </span>
        </div>
      ),
      sortValue: (entry) => entry.action,
    },
    {
      id: 'patient',
      header: 'Patient',
      cell: (entry) => (
        <code className="text-xs">{entry.patient_id ?? '--'}</code>
      ),
      sortValue: (entry) => entry.patient_id ?? '',
    },
    {
      id: 'identified',
      header: 'Identified',
      cell: (entry) =>
        entry.identified ? (
          // The distinction a breach assessment turns on.
          <Badge tone="danger">identified</Badge>
        ) : entry.identified === false ? (
          <Badge tone="success">de-identified</Badge>
        ) : (
          <span className="text-xs text-[rgb(var(--foreground-muted))]">--</span>
        ),
      sortValue: (entry) => String(entry.identified),
    },
  ]

  const anyFilter =
    actor || patientId || action || identifiedOnly || dateFrom || dateTo

  return (
    <RequirePermission permission="log:view">
      <div className="space-y-6">
        <PageHeader
          title="Access log"
          description="Who read, downloaded or exported what -- and who was refused."
        />

        <div className="grid gap-4 rounded-lg border border-[rgb(var(--border))] bg-[rgb(var(--surface))] p-4 sm:grid-cols-2 lg:grid-cols-3">
          <TextField
            label="Who"
            placeholder="Username"
            value={actor}
            onChange={(event) => setActor(event.target.value)}
          />
          <TextField
            label="Patient"
            placeholder="Patient id"
            value={patientId}
            onChange={(event) => setPatientId(event.target.value)}
          />
          <SelectField
            label="Action"
            placeholder="Any action"
            value={action}
            onChange={(event) => setAction(event.target.value)}
            options={ACCESS_ACTIONS.map((value) => ({ value, label: value }))}
          />
          <TextField
            label="From"
            type="date"
            value={dateFrom}
            onChange={(event) => setDateFrom(event.target.value)}
            hint="Bounding the dates keeps the query fast -- it selects partitions."
          />
          <TextField
            label="To"
            type="date"
            value={dateTo}
            onChange={(event) => setDateTo(event.target.value)}
          />
          <div className="flex flex-col justify-end gap-3">
            <CheckboxField
              label="Disclosures only"
              description="Reads where identified PHI left, not redacted copies."
              checked={identifiedOnly}
              onChange={(event) => setIdentifiedOnly(event.target.checked)}
            />
            <Button
              variant="outline"
              disabled={!anyFilter}
              onClick={() => {
                setActor('')
                setPatientId('')
                setAction('')
                setIdentifiedOnly(false)
                setDateFrom('')
                setDateTo('')
              }}
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
          loadingLabel="Loading access log"
          emptyMessage={
            anyFilter
              ? 'No access matches those filters.'
              : 'Nothing recorded yet.'
          }
        />
      </div>
    </RequirePermission>
  )
}
