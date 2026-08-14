import { createFileRoute, useNavigate } from '@tanstack/react-router'
import { useCallback, useMemo, useState } from 'react'
import { DataTable, type Column } from '@/components/DataTable'
import { ReasonDialog } from '@/components/ReasonDialog'
import { Can, RequirePermission } from '@/components/PermissionGate'
import { Button } from '@/components/ui/Button'
import { TextField } from '@/components/ui/Field'
import { Badge, PageHeader } from '@/components/ui/Misc'
import { usePermissions } from '@/hooks/useCurrentUser'
import { useDocumentTitle } from '@/hooks/useDocumentTitle'
import {
  patientHooks,
  useApplications,
  useRejectApplication,
  useDeleteApplication,
} from '@/hooks/useResources'
import { patientName, type Patient } from '@/schemas/patient'
import {
  applicationTone,
  canDelete,
  canReject,
  type PatientApplication,
} from '@/schemas/patientApplication'

function Muted({ value }: { value: string | null | undefined }) {
  return <span className="text-[rgb(var(--foreground-muted))]">{value || '—'}</span>
}

/** Hive TIMESTAMPs arrive as naive ISO strings; the seconds add nothing. */
function shortTimestamp(value: string | null | undefined) {
  return value ? value.slice(0, 16).replace('T', ' ') : null
}

function ApplicationsList() {
  useDocumentTitle('Applications')

  const navigate = useNavigate()
  const { can } = usePermissions()
  const [search, setSearch] = useState('')

  const { data, isLoading, isFetching, error } = useApplications()
  const patients = patientHooks.useList({ enabled: can('patient:view') })
  const remove = useDeleteApplication()
  const reject = useRejectApplication()

  const [deleting, setDeleting] = useState<PatientApplication | null>(null)
  const [rejecting, setRejecting] = useState<PatientApplication | null>(null)

  const patientsById = useMemo(() => {
    const index = new Map<string, Patient>()
    for (const patient of patients.data ?? []) index.set(patient.id, patient)
    return index
  }, [patients.data])

  const labelFor = useCallback(
    (application: PatientApplication) => {
      const patient = patientsById.get(application.patient_id)
      return patient ? patientName(patient) : application.patient_id
    },
    [patientsById]
  )

  const columns: Array<Column<PatientApplication>> = useMemo(
    () => [
      {
        id: 'patient',
        header: 'Patient',
        cell: (a) => labelFor(a),
        sortValue: (a) => labelFor(a),
      },
      {
        id: 'status',
        header: 'Status',
        cell: (a) => <Badge tone={applicationTone(a.status)}>{a.status}</Badge>,
        sortValue: (a) => a.status,
      },
      {
        id: 'assigned_to',
        header: 'Assigned to',
        // Sorted and searchable, because the question it answers is
        // "which of these are mine".
        cell: (a) => <Muted value={a.assigned_to_username} />,
        sortValue: (a) => a.assigned_to_username ?? '',
      },
      {
        id: 'description',
        header: 'Description',
        cell: (a) => <Muted value={a.description} />,
        sortValue: (a) => a.description ?? '',
      },
      {
        id: 'submitted_at',
        header: 'Submitted',
        cell: (a) => <Muted value={shortTimestamp(a.submitted_at)} />,
        sortValue: (a) => a.submitted_at ?? '',
      },
      {
        id: 'reviewed_at',
        header: 'Reviewed',
        cell: (a) => <Muted value={shortTimestamp(a.reviewed_at)} />,
        sortValue: (a) => a.reviewed_at ?? '',
      },
      {
        id: 'created_at',
        header: 'Created',
        cell: (a) => <Muted value={shortTimestamp(a.created_at)} />,
        sortValue: (a) => a.created_at,
      },
    ],
    [labelFor]
  )

  const filtered = useMemo(() => {
    const term = search.trim().toLowerCase()
    if (!term) return data
    return (data ?? []).filter((application) =>
      [
        labelFor(application),
        application.status,
        application.description,
        // So "show me mine" is a matter of typing your username.
        application.assigned_to_username,
      ]
        .filter(Boolean)
        .join(' ')
        .toLowerCase()
        .includes(term)
    )
  }, [data, search, labelFor])

  const canModify = can('application:update') || can('application:delete')

  return (
    <div className="space-y-6">
      <PageHeader
        title="Applications"
        description="Patient submissions and where each one stands in review."
        actions={
          <Can permission="application:create">
            <Button onClick={() => void navigate({ to: '/applications/new' })}>
              Create application
            </Button>
          </Can>
        }
      />

      <div className="flex flex-wrap items-center justify-between gap-4 rounded-lg border border-[rgb(var(--border))] bg-[rgb(var(--surface))] p-4">
        <TextField
          label="Search"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="Search by patient, status or description..."
          aria-label="Search applications"
        />
      </div>

      <DataTable
        data={filtered}
        columns={columns}
        getRowId={(application) => application.id}
        isLoading={isLoading}
        isFetching={isFetching}
        error={error}
        loadingLabel="Loading applications"
        emptyMessage="No applications found."
        rowActions={(application) =>
          canModify ? (
            <>
              <Can permission="application:update">
                <Button
                  size="sm"
                  aria-label={`Open application for ${labelFor(application)}`}
                  onClick={() =>
                    void navigate({
                      to: '/applications/$applicationId',
                      params: { applicationId: application.id },
                    })
                  }
                >
                  Open
                </Button>
              </Can>
              {canReject(application.status) ? (
                <Can permission="application:update">
                  <Button
                    size="sm"
                    variant="outline"
                    aria-label={`Reject application for ${labelFor(application)}`}
                    onClick={() => setRejecting(application)}
                  >
                    Reject
                  </Button>
                </Can>
              ) : null}
              {canDelete(application.status) ? (
                <Can permission="application:delete">
                  <Button
                    size="sm"
                    variant="danger"
                    aria-label={`Delete application for ${labelFor(application)}`}
                    onClick={() => setDeleting(application)}
                  >
                    Delete
                  </Button>
                </Can>
              ) : null}
            </>
          ) : null
        }
      />

      {rejecting ? (
        <ReasonDialog
          title={`Reject the application for ${labelFor(rejecting)}?`}
          description="The reason is kept on the record."
          confirmLabel="Reject application"
          placeholder="e.g. consent form missing"
          isBusy={reject.isPending}
          onCancel={() => setRejecting(null)}
          onConfirm={(reason) => {
            void reject
              .mutateAsync({ id: rejecting.id, reason })
              .then(() => setRejecting(null))
              .catch(() => undefined)
          }}
        />
      ) : null}

      {deleting ? (
        <ReasonDialog
          title={`Delete the documents for ${labelFor(deleting)}?`}
          description={
            'The documents are removed for good. The application itself is ' +
            'kept and marked deleted, with the reason you give here.'
          }
          confirmLabel="Delete documents"
          placeholder="e.g. duplicate submission"
          isBusy={remove.isPending}
          onCancel={() => setDeleting(null)}
          onConfirm={(reason) => {
            void remove
              .mutateAsync({ id: deleting.id, reason })
              .then(() => setDeleting(null))
              .catch(() => undefined)
          }}
        />
      ) : null}
    </div>
  )
}

export const Route = createFileRoute('/applications/')({
  component: () => (
    <RequirePermission permission="application:view">
      <ApplicationsList />
    </RequirePermission>
  ),
})
