import { createFileRoute, useNavigate } from '@tanstack/react-router'
import { useMemo, useState } from 'react'
import { ConfirmDeleteModal } from '@/components/ConfirmDeleteModal'
import { DataTable, type Column } from '@/components/DataTable'
import { Can, RequirePermission } from '@/components/PermissionGate'
import { Button } from '@/components/ui/Button'
import { TextField } from '@/components/ui/Field'
import { PageHeader } from '@/components/ui/Misc'
import { usePermissions } from '@/hooks/useCurrentUser'
import { useDeleteDialog } from '@/hooks/useDeleteDialog'
import { useDocumentTitle } from '@/hooks/useDocumentTitle'
import { patientHooks } from '@/hooks/useResources'
import { PatientApplicationsModal } from '@/features/patients/PatientApplicationsModal'
import { patientName, type Patient } from '@/schemas/patient'

/** Most patient columns are nullable; render a dash, not an empty cell. */
function Muted({ value }: { value: string | null | undefined }) {
  return <span className="text-[rgb(var(--foreground-muted))]">{value || '—'}</span>
}

const columns: Array<Column<Patient>> = [
  {
    id: 'id',
    header: 'Id',
    cell: (p) => <span className="font-mono text-xs tabular-nums">{p.id}</span>,
    sortValue: (p) => p.id,
  },
  // Combined for the same reason as the users table -- see the note there.
  {
    id: 'name',
    header: 'Name',
    cell: (p) => patientName(p),
    sortValue: (p) => patientName(p),
  },
  {
    id: 'dt_b',
    header: 'Date of birth',
    cell: (p) => <Muted value={p.dt_b} />,
    sortValue: (p) => p.dt_b ?? '',
  },
  {
    id: 'ptemail',
    header: 'Email',
    cell: (p) => <Muted value={p.ptemail} />,
    sortValue: (p) => p.ptemail ?? '',
  },
  {
    id: 'ptphone',
    header: 'Phone',
    cell: (p) => <Muted value={p.ptphone} />,
    sortValue: (p) => p.ptphone ?? '',
  },
  {
    id: 'instcode',
    header: 'Institution',
    cell: (p) => <Muted value={p.instcode || p.pname} />,
    sortValue: (p) => p.instcode ?? '',
  },
]

function PatientsList() {
  useDocumentTitle('Patients')

  const navigate = useNavigate()
  const { can } = usePermissions()
  const [search, setSearch] = useState('')
  const [showingApplicationsFor, setShowingApplicationsFor] =
    useState<Patient | null>(null)

  const { data, isLoading, isFetching, error } = patientHooks.useList()
  const remove = patientHooks.useRemove()

  const deleteDialog = useDeleteDialog<Patient>((patient) =>
    remove.mutateAsync(patient.id)
  )

  const filtered = useMemo(() => {
    const term = search.trim().toLowerCase()
    if (!term) return data
    return (data ?? []).filter((patient) =>
      [
        patient.fstname,
        patient.lstname,
        patient.ptemail,
        patient.ptphone,
        patient.instcode,
        patient.pname,
      ]
        .filter(Boolean)
        .join(' ')
        .toLowerCase()
        .includes(term)
    )
  }, [data, search])

  const canModify = can('patient:update') || can('patient:delete')

  return (
    <div className="space-y-6">
      <PageHeader
        title="Patient Management"
        description="Patient records held in Hive."
        actions={
          <Can permission="patient:create">
            <Button onClick={() => void navigate({ to: '/patients/new' })}>
              Add Patient
            </Button>
          </Can>
        }
      />

      <div className="flex flex-wrap items-center justify-between gap-4 rounded-lg border border-[rgb(var(--border))] bg-[rgb(var(--surface))] p-4">
        <TextField
          label="Search"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          placeholder="Search by name, email, phone or institution..."
          aria-label="Search patients"
        />
      </div>

      <DataTable
        data={filtered}
        columns={columns}
        getRowId={(patient) => patient.id}
        isLoading={isLoading}
        isFetching={isFetching}
        error={error}
        loadingLabel="Loading patients"
        emptyMessage="No patients found."
        rowActions={(patient) => (
          <>
            {/* No Files action here any more: documents hang off an
                application, not off the patient, so they are reached
                through Applications rather than from this row. Their
                applications are, though -- see below. */}
            <Can permission="application:view">
              <Button
                size="sm"
                variant="outline"
                aria-label={`Show applications for ${patientName(patient)}`}
                onClick={() => setShowingApplicationsFor(patient)}
              >
                Applications
              </Button>
            </Can>
            {canModify ? (
              <>
                <Can permission="patient:update">
                  <Button
                    size="sm"
                    aria-label={`Edit ${patientName(patient)}`}
                    onClick={() =>
                      void navigate({
                        to: '/patients/$patientId/edit',
                        params: { patientId: patient.id },
                      })
                    }
                  >
                    Edit
                  </Button>
                </Can>
                <Can permission="patient:delete">
                  <Button
                    size="sm"
                    variant="danger"
                    aria-label={`Delete ${patientName(patient)}`}
                    onClick={() => deleteDialog.request(patient)}
                  >
                    Delete
                  </Button>
                </Can>
              </>
            ) : null}
          </>
        )}
      />

      {showingApplicationsFor ? (
        <PatientApplicationsModal
          patient={showingApplicationsFor}
          onClose={() => setShowingApplicationsFor(null)}
        />
      ) : null}

      <ConfirmDeleteModal
        open={deleteDialog.isOpen}
        entityLabel="Patient"
        targetName={deleteDialog.target ? patientName(deleteDialog.target) : undefined}
        isDeleting={deleteDialog.isDeleting}
        onCancel={deleteDialog.cancel}
        onConfirm={() => void deleteDialog.confirm()}
      />
    </div>
  )
}

export const Route = createFileRoute('/patients/')({
  component: () => (
    <RequirePermission permission="patient:view">
      <PatientsList />
    </RequirePermission>
  ),
})
