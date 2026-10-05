import { createFileRoute } from '@tanstack/react-router'
import { Check, X } from 'lucide-react'
import { useState } from 'react'
import { DataTable, type Column } from '@/components/DataTable'
import { ReasonDialog } from '@/components/ReasonDialog'
import { RequirePermission } from '@/components/PermissionGate'
import { Button } from '@/components/ui/Button'
import { SelectField } from '@/components/ui/Field'
import { Badge, Card, PageHeader } from '@/components/ui/Misc'
import { LoadingBlock } from '@/components/ui/Spinner'
import { useDocumentTitle } from '@/hooks/useDocumentTitle'
import {
  useApproveRelease,
  useRejectRelease,
  useZone2Release,
  useZone2Releases,
} from '@/hooks/useResources'
import { releaseTone, type ReleaseSummary } from '@/schemas/project'

export const Route = createFileRoute('/zone2-inbox/')({
  component: () => (
    <RequirePermission permission="zone2:review">
      <Zone2InboxPage />
    </RequirePermission>
  ),
})

const titleClass =
  'text-[11px] font-bold tracking-widest text-[rgb(var(--foreground-muted))] uppercase'

const VIEWS = [
  { value: 'in_review', label: 'Waiting for review' },
  { value: 'approved', label: 'Released' },
  { value: 'rejected', label: 'Sent back' },
]

const TABLES: Array<{ key: string; label: string }> = [
  { key: 'patients', label: 'patients.csv' },
  { key: 'applications', label: 'applications.csv' },
  { key: 'documents', label: 'documents.csv' },
]

function when(value: string | null | undefined) {
  return value ? value.slice(0, 16).replace('T', ' ') : '—'
}

function Zone2InboxPage() {
  useDocumentTitle('Zone 2 inbox')
  const [view, setView] = useState('in_review')
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const releases = useZone2Releases(view)

  const columns: Array<Column<ReleaseSummary>> = [
    {
      id: 'project',
      header: 'Project',
      cell: (r) => (
        <div className="min-w-0">
          <span className="block truncate font-semibold">{r.project_name}</span>
          <span className="block font-mono text-xs text-[rgb(var(--foreground-muted))]">
            {r.project_short_code} · {r.id}
          </span>
        </div>
      ),
      sortValue: (r) => r.project_name.toLowerCase(),
    },
    {
      id: 'contents',
      header: 'Contents',
      cell: (r) => (
        <span className="text-sm">
          {r.patients} patients · {r.applications} applications · {r.documents} documents
          {r.files_included ? ' (files included)' : ''}
        </span>
      ),
    },
    {
      id: 'status',
      header: 'Status',
      cell: (r) => (
        <Badge tone={releaseTone(r.status)}>
          {VIEWS.find((v) => v.value === r.status)?.label ?? r.status}
        </Badge>
      ),
    },
    {
      id: 'prepared',
      header: 'Prepared',
      cell: (r) => <span className="text-sm">{when(r.prepared_at)}</span>,
      sortValue: (r) => r.prepared_at ?? '',
    },
  ]

  return (
    <div className="space-y-6">
      <PageHeader
        title="Zone 2 inbox"
        description="Safe copies waiting for the CHSS manager. Check that they are free from identifiers and that the preparation was applied properly, then release them to Zone 2 or send them back."
      />

      <div className="flex flex-wrap items-end gap-3 rounded-lg border border-[rgb(var(--border))] bg-[rgb(var(--surface))] p-4">
        <div className="w-56">
          <SelectField
            label="Show"
            value={view}
            options={VIEWS}
            onChange={(event) => {
              setView(event.target.value)
              setSelectedId(null)
            }}
          />
        </div>
      </div>

      <DataTable
        data={releases.data ?? []}
        columns={columns}
        getRowId={(r) => r.id}
        isLoading={releases.isLoading}
        isFetching={releases.isFetching}
        error={releases.error}
        loadingLabel="Loading releases"
        emptyMessage={
          view === 'in_review' ? 'Nothing is waiting for review.' : 'Nothing here yet.'
        }
        rowActions={(r) => (
          <Button
            size="sm"
            variant={selectedId === r.id ? 'primary' : 'outline'}
            onClick={() => setSelectedId(selectedId === r.id ? null : r.id)}
          >
            {selectedId === r.id ? 'Hide' : 'Review'}
          </Button>
        )}
      />

      {selectedId ? (
        <ReleaseReview
          key={selectedId}
          releaseId={selectedId}
          onDecided={() => setSelectedId(null)}
        />
      ) : null}
    </div>
  )
}

function ReleaseReview({
  releaseId,
  onDecided,
}: {
  releaseId: string
  onDecided: () => void
}) {
  const query = useZone2Release(releaseId)
  const approve = useApproveRelease()
  const reject = useRejectRelease()
  const [rejecting, setRejecting] = useState(false)

  if (query.isLoading) return <LoadingBlock label="Loading the safe copy" />
  const release = query.data
  if (!release) return null
  const pending = release.status === 'in_review'

  return (
    <Card className="space-y-5 p-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h2 className={titleClass}>
            {release.project_name} · {release.id}
          </h2>
          <p className="mt-1 text-sm">
            {release.patients} patients · {release.applications} submitted applications ·{' '}
            {release.documents} documents{' '}
            {release.files_included
              ? '(the de-identified files are included)'
              : '(listed only; the files are not included)'}
          </p>
          <p className="mt-1 font-mono text-[11px] break-all text-[rgb(var(--foreground-muted))]">
            {release.release_path ?? release.inbox_path}
          </p>
          {release.status_reason ? (
            <p className="mt-1 text-sm">Reason: {release.status_reason}</p>
          ) : null}
        </div>
        {pending ? (
          <div className="flex gap-2">
            <Button
              variant="danger"
              leadingIcon={<X className="size-4" aria-hidden="true" />}
              onClick={() => setRejecting(true)}
            >
              Send back
            </Button>
            <Button
              isLoading={approve.isPending}
              leadingIcon={<Check className="size-4" aria-hidden="true" />}
              onClick={() =>
                void approve
                  .mutateAsync(release.id)
                  .then(onDecided)
                  .catch(() => undefined)
              }
            >
              Release to Zone 2
            </Button>
          </div>
        ) : null}
      </div>

      {release.files_included ? (
        <p className="rounded-lg border border-[rgb(var(--border))] bg-[rgb(var(--background-secondary))] p-3 text-sm">
          This copy includes documents. Open a few from the folder above in a Cloudera
          Session to confirm they are fully de-identified before releasing.
        </p>
      ) : null}

      {TABLES.map(({ key, label }) => {
        const header = release.columns[key] ?? []
        const rows = release.samples[key] ?? []
        return (
          <div key={key}>
            <h3 className="mb-2 font-mono text-xs font-semibold">
              {label}{' '}
              <span className="font-sans font-normal text-[rgb(var(--foreground-muted))]">
                first {rows.length} row{rows.length === 1 ? '' : 's'}
              </span>
            </h3>
            {header.length === 0 ? (
              <p className="text-sm text-[rgb(var(--foreground-muted))]">
                Not available.
              </p>
            ) : (
              <div className="overflow-x-auto rounded-lg border border-[rgb(var(--border))]">
                <table className="w-full border-collapse text-xs">
                  <thead className="bg-[rgb(var(--background-secondary))]">
                    <tr>
                      {header.map((column) => (
                        <th
                          key={column}
                          className="px-3 py-2 text-left font-mono font-semibold"
                        >
                          {column}
                        </th>
                      ))}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[rgb(var(--border))]">
                    {rows.map((row, index) => (
                      <tr key={index}>
                        {header.map((column) => (
                          <td key={column} className="px-3 py-1.5 font-mono">
                            {row[column] || '—'}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )
      })}

      {rejecting ? (
        <ReasonDialog
          title={`Send ${release.project_name} back?`}
          description="The safe copy is removed from the inbox and the project goes back with your reason, to be fixed and prepared again. The archive is kept."
          confirmLabel="Send back"
          placeholder="e.g. state column is too specific for this cohort"
          isBusy={reject.isPending}
          onCancel={() => setRejecting(false)}
          onConfirm={(reason) =>
            void reject
              .mutateAsync({ id: release.id, reason })
              .then(() => {
                setRejecting(false)
                onDecided()
              })
              .catch(() => undefined)
          }
        />
      ) : null}
    </Card>
  )
}
