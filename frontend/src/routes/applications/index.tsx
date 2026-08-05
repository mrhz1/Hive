import { createFileRoute, useNavigate } from '@tanstack/react-router'
import { useCallback, useMemo, useState } from 'react'
import { ConfirmDeleteModal } from '@/components/ConfirmDeleteModal'
import { DataTable, type Column } from '@/components/DataTable'
import { Can, RequirePermission } from '@/components/PermissionGate'
import { Button } from '@/components/ui/Button'
import { TextField } from '@/components/ui/Field'
import { Badge, PageHeader } from '@/components/ui/Misc'
import { usePermissions } from '@/hooks/useCurrentUser'
import { useDeleteDialog } from '@/hooks/useDeleteDialog'
import { useDocumentTitle } from '@/hooks/useDocumentTitle'
import {
  patientHooks,
  useApplications,
  useDeleteApplication,
} from '@/hooks/useResources'
import { patientName, type Patient } from '@/schemas/patient'
import {
  applicationTone,
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
  // The application stores only patient_id, but a list of opaque ids is
  // unusable -- so the patients are fetched alongside and joined here.
  // Skipped entirely without patient:view, in which case the column
  // falls back to the id rather than the page failing.
  const patients = patientHooks.useList({ enabled: can('patient:view') })
  const remove = useDeleteApplication()

  const deleteDialog = useDeleteDialog<PatientApplication>((application) =>
    remove.mutateAsync(application.id)
  )

  const patientsById = useMemo(() => {
    const index = new Map<string, Patient>()
    for (const patient of patients.data ?? []) index.set(patient.id, patient)
    return index
  }, [patients.data])

  // Memoised so the columns and the filter can depend on it directly
  // rather than on the index it closes over.
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
    // labelFor changes with the patient index, so the columns rebuild
    // when the patients finish loading and the ids turn into names.
    [labelFor]
  )

  const filtered = useMemo(() => {
    const term = search.trim().toLowerCase()
    if (!term) return data
    return (data ?? []).filter((application) =>
      [labelFor(application), application.status, application.description]
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
              <Can permission="application:delete">
                <Button
                  size="sm"
                  variant="danger"
                  aria-label={`Delete application for ${labelFor(application)}`}
                  onClick={() => deleteDialog.request(application)}
                >
                  Delete
                </Button>
              </Can>
            </>
          ) : null
        }
      />

      <ConfirmDeleteModal
        open={deleteDialog.isOpen}
        entityLabel="Application"
        targetName={deleteDialog.target ? labelFor(deleteDialog.target) : undefined}
        isDeleting={deleteDialog.isDeleting}
        onCancel={deleteDialog.cancel}
        onConfirm={() => void deleteDialog.confirm()}
      />
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
