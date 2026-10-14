import { createFileRoute } from '@tanstack/react-router'
import { CalendarPlus, FileText, FolderPlus, RefreshCw, Trash2 } from 'lucide-react'
import { useEffect, useState } from 'react'
import { DataTable, type Column } from '@/components/DataTable'
import { Can, RequirePermission } from '@/components/PermissionGate'
import { ReasonDialog } from '@/components/ReasonDialog'
import { Button } from '@/components/ui/Button'
import { DropdownMenu, type MenuAction } from '@/components/ui/DropdownMenu'
import { CheckboxField, TextAreaField, TextField } from '@/components/ui/Field'
import { Badge, Card, PageHeader } from '@/components/ui/Misc'
import { useCurrentUser, usePermissions } from '@/hooks/useCurrentUser'
import { useDocumentTitle } from '@/hooks/useDocumentTitle'
import {
  useAbstractionDocuments,
  useAbstractionFolders,
  useAbstractionPreview,
  useCreateAbstractionFolder,
  useDeleteAbstractionFolder,
  useExtendAbstractionFolder,
  useRegenerateAbstractionFolder,
} from '@/hooks/useResources'
import {
  FILE_TYPES,
  daysLeft,
  folderTone,
  splitCodes,
  type AbstractionCriteria,
  type AbstractionDocument,
  type AbstractionFolder,
} from '@/schemas/abstraction'
import { isoDocumentDate } from '@/schemas/applicationFile'

export const Route = createFileRoute('/abstraction/')({
  component: () => (
    <RequirePermission permission="abstraction:view">
      <AbstractionPage />
    </RequirePermission>
  ),
})

const DOCUMENT_COLUMNS: Array<Column<AbstractionDocument>> = [
  {
    id: 'patient',
    header: 'Patient code',
    cell: (d) => <span className="font-mono text-xs font-semibold">{d.patient_id}</span>,
    sortValue: (d) => d.patient_id,
  },
  {
    id: 'name',
    header: 'Document',
    cell: (d) => <span className="font-mono text-xs break-all">{d.name}</span>,
    sortValue: (d) => d.name,
  },
  {
    id: 'modality',
    header: 'Type',
    cell: (d) => <Badge tone="neutral">{d.modality ?? '—'}</Badge>,
    sortValue: (d) => d.modality ?? '',
  },
  {
    id: 'date',
    header: 'Date',
    cell: (d) => (
      <span className="text-xs tabular-nums">
        {isoDocumentDate(d.document_date) ?? '—'}
      </span>
    ),
    sortValue: (d) => d.document_date ?? '',
  },
  {
    id: 'type',
    header: 'Type',
    cell: (d) => d.file_type,
    sortValue: (d) => d.file_type,
  },
]

function NewFolder({ onDone }: { onDone: () => void }) {
  const preview = useAbstractionPreview()
  const create = useCreateAbstractionFolder()

  const [codes, setCodes] = useState('')
  const [modalities, setModalities] = useState('')
  const [fileTypes, setFileTypes] = useState<string[]>([])
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [search, setSearch] = useState('')
  const [name, setName] = useState('')
  const [purpose, setPurpose] = useState('')

  const criteria: AbstractionCriteria = {
    patient_ids: splitCodes(codes),
    modalities: splitCodes(modalities),
    file_types: fileTypes,
    date_from: dateFrom || null,
    date_to: dateTo || null,
    search: search.trim() || null,
  }
  const criteriaKey = JSON.stringify(criteria)

  // A preview is only good for the criteria it was made with.
  const { reset } = preview
  useEffect(() => {
    reset()
  }, [criteriaKey, reset])

  const found = preview.data
  const canCreate = Boolean(found && found.total > 0 && name.trim() && purpose.trim())

  return (
    <Card className="space-y-5 p-5">
      <div>
        <h2 className="text-sm font-bold">New abstraction folder</h2>
        <p className="mt-1 text-xs text-[rgb(var(--foreground-muted))]">
          Pick de-identified documents of submitted applications by their metadata. They
          are copied, read-only, to a folder of your own that is deleted after 90 days
          unless you extend it. Leave a field empty to take any value.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
        <TextField
          label="Patient codes"
          value={codes}
          placeholder="AA1234, AVSD0012"
          hint="Separated by commas or spaces"
          onChange={(event) => setCodes(event.target.value)}
        />
        <TextField
          label="Types / modalities"
          value={modalities}
          placeholder="DISCHARGE, ECHO_REPORT, MR"
          hint="Document types (DISCHARGE, CONSENT, ...) or DICOM modalities (MR, CT); UNKNOWN for not set"
          onChange={(event) => setModalities(event.target.value)}
        />
        <TextField
          label="Document date from"
          type="date"
          value={dateFrom}
          onChange={(event) => setDateFrom(event.target.value)}
        />
        <TextField
          label="Document date to"
          type="date"
          value={dateTo}
          hint="With a date set, documents without a known date are left out"
          onChange={(event) => setDateTo(event.target.value)}
        />
        <TextField
          label="Text in the file name or metadata"
          value={search}
          placeholder="e.g. CHEST, SIEMENS"
          onChange={(event) => setSearch(event.target.value)}
        />
        <fieldset>
          <legend className="mb-2 text-sm font-medium">File types</legend>
          <div className="flex flex-wrap gap-4">
            {FILE_TYPES.map((type) => (
              <CheckboxField
                key={type}
                label={type}
                checked={fileTypes.includes(type)}
                onChange={(event) =>
                  setFileTypes((current) =>
                    event.target.checked
                      ? [...current, type]
                      : current.filter((value) => value !== type)
                  )
                }
              />
            ))}
          </div>
        </fieldset>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <Button
          variant="outline"
          isLoading={preview.isPending}
          onClick={() => preview.mutate(criteria)}
        >
          Find documents
        </Button>
        {found ? (
          <span className="text-sm">
            <strong>{found.total}</strong> document{found.total === 1 ? '' : 's'} for{' '}
            <strong>{found.patients}</strong> patient{found.patients === 1 ? '' : 's'}
            {found.total > found.documents.length
              ? ` (first ${found.documents.length} shown)`
              : ''}
          </span>
        ) : null}
      </div>

      {found && found.total > 0 ? (
        <>
          <DataTable
            data={found.documents}
            columns={DOCUMENT_COLUMNS}
            getRowId={(d) => d.file_id}
            loadingLabel="Loading documents"
            emptyMessage="Nothing matches."
          />

          <div className="grid grid-cols-1 gap-4 md:grid-cols-2">
            <TextField
              label="Folder name"
              required
              value={name}
              placeholder="e.g. Cardiac MRI abstraction"
              onChange={(event) => setName(event.target.value)}
            />
            <TextAreaField
              label="Purpose"
              required
              rows={2}
              value={purpose}
              placeholder="What the documents are needed for"
              onChange={(event) => setPurpose(event.target.value)}
            />
          </div>
        </>
      ) : null}

      <div className="flex flex-wrap justify-end gap-3">
        <Button variant="outline" onClick={onDone}>
          Cancel
        </Button>
        <Button
          isLoading={create.isPending}
          disabled={!canCreate}
          title={
            canCreate
              ? undefined
              : 'Find documents, then give the folder a name and purpose'
          }
          onClick={() =>
            void create
              .mutateAsync({ name: name.trim(), purpose: purpose.trim(), criteria })
              .then(onDone)
              .catch(() => undefined)
          }
        >
          Make folder
        </Button>
      </div>
    </Card>
  )
}

function FolderDocuments({
  folder,
  onClose,
}: {
  folder: AbstractionFolder
  onClose: () => void
}) {
  const documents = useAbstractionDocuments(folder.id)

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') onClose()
    }
    document.addEventListener('keydown', onKeyDown)
    return () => document.removeEventListener('keydown', onKeyDown)
  }, [onClose])

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-[rgb(var(--background))]/80 p-4 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-label={`Documents in ${folder.name}`}
    >
      <div className="max-h-[85vh] w-full max-w-4xl space-y-4 overflow-y-auto rounded-xl border border-[rgb(var(--border))] bg-[rgb(var(--surface))] p-5 shadow-xl">
        <div className="flex items-start justify-between gap-4">
          <div>
            <h2 className="text-sm font-bold">{folder.name}</h2>
            <p className="mt-1 font-mono text-xs break-all text-[rgb(var(--foreground-muted))]">
              {folder.folder_path}
            </p>
          </div>
          <Button variant="outline" onClick={onClose}>
            Close
          </Button>
        </div>
        <DataTable
          data={documents.data ?? []}
          columns={DOCUMENT_COLUMNS}
          getRowId={(d) => d.file_id}
          isLoading={documents.isLoading}
          error={documents.error}
          loadingLabel="Loading documents"
          emptyMessage="None of this folder's documents are available any more."
        />
      </div>
    </div>
  )
}

function AbstractionPage() {
  useDocumentTitle('Abstraction folders')
  const { can } = usePermissions()
  const me = useCurrentUser().data
  const folders = useAbstractionFolders()
  const extend = useExtendAbstractionFolder()
  const regenerate = useRegenerateAbstractionFolder()
  const remove = useDeleteAbstractionFolder()

  const [creating, setCreating] = useState(false)
  const [showing, setShowing] = useState<AbstractionFolder | null>(null)
  const [deleting, setDeleting] = useState<AbstractionFolder | null>(null)

  const manageAll = can('abstraction:delete')

  function actionsFor(folder: AbstractionFolder): MenuAction[] {
    const active = folder.status === 'active'
    const mayChange =
      can('abstraction:update') && (manageAll || folder.owner_id === me?.id)
    const actions: MenuAction[] = [
      {
        id: 'documents',
        label: 'Show documents',
        icon: <FileText className="size-4" aria-hidden="true" />,
        onSelect: () => setShowing(folder),
      },
    ]
    if (!mayChange) return actions

    actions.push(
      {
        id: 'extend',
        label: 'Extend 90 days',
        icon: <CalendarPlus className="size-4" aria-hidden="true" />,
        disabled: !active,
        title: active ? undefined : 'Make it again instead',
        isLoading: extend.isPending && extend.variables === folder.id,
        onSelect: () => extend.mutate(folder.id),
      },
      {
        id: 'regenerate',
        label: active ? 'Copy again' : 'Make again',
        icon: <RefreshCw className="size-4" aria-hidden="true" />,
        isLoading: regenerate.isPending && regenerate.variables === folder.id,
        title: 'Copies the same documents again, with a new 90 days',
        onSelect: () => regenerate.mutate(folder.id),
      },
      {
        id: 'delete',
        label: 'Delete',
        separatorBefore: true,
        tone: 'danger',
        icon: <Trash2 className="size-4" aria-hidden="true" />,
        disabled: !active,
        title: active ? 'Removes the copy; the record stays' : `Already ${folder.status}`,
        onSelect: () => setDeleting(folder),
      }
    )
    return actions
  }

  const columns: Array<Column<AbstractionFolder>> = [
    {
      id: 'name',
      header: 'Folder',
      cell: (f) => (
        <div className="min-w-0">
          <span className="block truncate font-semibold">{f.name}</span>
          <span
            className="block truncate text-xs text-[rgb(var(--foreground-muted))]"
            title={f.purpose ?? undefined}
          >
            {f.purpose}
          </span>
        </div>
      ),
      sortValue: (f) => f.name.toLowerCase(),
    },
    ...(manageAll
      ? [
          {
            id: 'owner',
            header: 'Owner',
            cell: (f: AbstractionFolder) => f.owner_username ?? f.owner_id ?? '—',
            sortValue: (f: AbstractionFolder) => f.owner_username ?? '',
          },
        ]
      : []),
    {
      id: 'status',
      header: 'Status',
      cell: (f) => <Badge tone={folderTone(f.status)}>{f.status}</Badge>,
      sortValue: (f) => f.status,
    },
    {
      id: 'files',
      header: 'Documents',
      cell: (f) => <span className="tabular-nums">{f.file_count}</span>,
      sortValue: (f) => f.file_count,
    },
    {
      id: 'expires',
      header: 'Expires',
      cell: (f) => {
        if (f.status !== 'active') {
          return (
            <span className="text-xs text-[rgb(var(--foreground-muted))]">
              {f.deleted_at?.slice(0, 10) ?? '—'}
              {f.deleted_reason ? ` · ${f.deleted_reason}` : ''}
            </span>
          )
        }
        const left = daysLeft(f.expires_at)
        return (
          <span className="text-xs tabular-nums">
            {f.expires_at?.slice(0, 10)}
            {left !== null ? (
              <Badge tone={left <= 7 ? 'warning' : 'neutral'} className="ml-2">
                {left} day{left === 1 ? '' : 's'}
              </Badge>
            ) : null}
          </span>
        )
      },
      sortValue: (f) => f.expires_at ?? '',
    },
    {
      id: 'path',
      header: 'Location',
      cell: (f) =>
        f.status === 'active' ? (
          <span className="font-mono text-xs break-all">{f.folder_path}</span>
        ) : (
          <span className="text-xs text-[rgb(var(--foreground-muted))]">removed</span>
        ),
    },
  ]

  return (
    <div className="space-y-6">
      <PageHeader
        title="Abstraction folders"
        description={
          manageAll
            ? 'Everyone’s temporary copies of de-identified documents.'
            : 'Your temporary copies of de-identified documents.'
        }
        actions={
          creating ? null : (
            <Can permission="abstraction:create">
              <Button onClick={() => setCreating(true)}>
                <FolderPlus className="size-4" aria-hidden="true" />
                New folder
              </Button>
            </Can>
          )
        }
      />

      {creating ? <NewFolder onDone={() => setCreating(false)} /> : null}

      <DataTable
        data={folders.data ?? []}
        columns={columns}
        getRowId={(f) => f.id}
        isLoading={folders.isLoading}
        isFetching={folders.isFetching}
        error={folders.error}
        loadingLabel="Loading folders"
        emptyMessage="No abstraction folders yet."
        rowActions={(folder) => (
          <DropdownMenu
            actions={actionsFor(folder)}
            label={`Actions for ${folder.name}`}
          />
        )}
      />

      {showing ? (
        <FolderDocuments folder={showing} onClose={() => setShowing(null)} />
      ) : null}

      {deleting ? (
        <ReasonDialog
          title={`Delete ${deleting.name}?`}
          description="The copied documents are removed from disk. The record stays, so the folder can be made again."
          confirmLabel="Delete folder"
          placeholder="e.g. abstraction finished"
          isBusy={remove.isPending}
          onCancel={() => setDeleting(null)}
          onConfirm={(reason) =>
            void remove
              .mutateAsync({ id: deleting.id, reason })
              .then(() => setDeleting(null))
              .catch(() => undefined)
          }
        />
      ) : null}
    </div>
  )
}
