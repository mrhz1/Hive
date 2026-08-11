import { createFileRoute } from '@tanstack/react-router'
import { FileJson, FileSpreadsheet } from 'lucide-react'
import { useMemo, useState } from 'react'
import { DataTable, type Column } from '@/components/DataTable'
import { RequirePermission } from '@/components/PermissionGate'
import { Button } from '@/components/ui/Button'
import { SelectField, TextField } from '@/components/ui/Field'
import { Badge, PageHeader } from '@/components/ui/Misc'
import { FileMetadataDetailModal } from '@/features/metadata/FileMetadataDetailModal'
import { useExportFileMetadata, useFileMetadataRows } from '@/hooks/useResources'
import { useDebounced } from '@/hooks/useDebounced'
import { METADATA_STATUSES, metadataTone } from '@/schemas/applicationFile'
import {
  metadataFieldCount,
  metadataPreview,
  type FileMetadataFilters,
  type FileMetadataRow,
} from '@/schemas/fileMetadata'

export const Route = createFileRoute('/metadata/')({
  component: MetadataPage,
})

/** The formats app/file_metadata.py knows how to read. */
const FILE_TYPES = ['pdf', 'dicom', 'word'] as const

function formatDate(value: string): string {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}

function MetadataPage() {
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState('')
  const [fileType, setFileType] = useState('')
  const [showing, setShowing] = useState<FileMetadataRow | null>(null)

  // The search hits Hive, so it waits for a pause in the typing.
  const debouncedSearch = useDebounced(search, 300)

  const filters: FileMetadataFilters = useMemo(
    () => ({ search: debouncedSearch, status, file_type: fileType }),
    [debouncedSearch, status, fileType]
  )

  const { data, isLoading, isFetching, error } = useFileMetadataRows(filters)
  const exportRows = useExportFileMetadata()

  const rows = data ?? []

  const columns: Array<Column<FileMetadataRow>> = [
    {
      id: 'file',
      header: 'Document',
      cell: (row) => (
        <div className="min-w-0">
          <span className="block truncate font-semibold">
            {row.file_name ?? row.file_id}
          </span>
          <span className="block truncate text-xs text-[rgb(var(--foreground-muted))]">
            {row.patient_id ? `${row.patient_id} · ` : ''}
            {metadataFieldCount(row)} field
            {metadataFieldCount(row) === 1 ? '' : 's'}
          </span>
        </div>
      ),
      sortValue: (row) => (row.file_name ?? row.file_id).toLowerCase(),
    },
    {
      id: 'type',
      header: 'Type',
      cell: (row) => <Badge tone="neutral">{row.file_type || 'file'}</Badge>,
      sortValue: (row) => row.file_type,
    },
    {
      id: 'status',
      header: 'Status',
      cell: (row) => (
        <div className="min-w-0">
          <Badge tone={metadataTone(row.status)}>{row.status}</Badge>
          {row.error ? (
            <span
              className="mt-1 block truncate text-xs text-[rgb(var(--foreground-muted))]"
              title={row.error}
            >
              {row.error}
            </span>
          ) : null}
        </div>
      ),
      sortValue: (row) => row.status,
    },
    {
      id: 'metadata',
      header: 'Extracted',
      cell: (row) => (
        <span
          className="block max-w-md truncate text-xs text-[rgb(var(--foreground-muted))]"
          title={metadataPreview(row, 12)}
        >
          {metadataPreview(row)}
        </span>
      ),
    },
    {
      id: 'created',
      header: 'Extracted at',
      cell: (row) => (
        <span className="whitespace-nowrap text-sm">
          {formatDate(row.created_at)}
        </span>
      ),
      sortValue: (row) => row.created_at,
    },
  ]

  return (
    <RequirePermission permission="application:view">
      <div className="space-y-6">
        <PageHeader
          title="Metadata"
          description="Everything extracted from uploaded documents, across every patient."
          actions={
            <Button
              isLoading={exportRows.isPending}
              disabled={rows.length === 0}
              title={
                rows.length === 0 ? 'There is nothing to export' : undefined
              }
              leadingIcon={
                <FileSpreadsheet className="size-4" aria-hidden="true" />
              }
              onClick={() => exportRows.mutate(filters)}
            >
              Export to Excel
            </Button>
          }
        />

        <div className="grid gap-4 rounded-lg border border-[rgb(var(--border))] bg-[rgb(var(--surface))] p-4 sm:grid-cols-2 lg:grid-cols-4">
          <div className="sm:col-span-2">
            <TextField
              label="Search"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search file names and everything extracted..."
              aria-label="Search metadata"
              hint="Matches extracted field names and values, as well as the document."
            />
          </div>

          <SelectField
            label="Status"
            value={status}
            onChange={(event) => setStatus(event.target.value)}
            placeholder="Any status"
            options={METADATA_STATUSES.map((value) => ({
              value,
              label: value,
            }))}
          />

          <SelectField
            label="Type"
            value={fileType}
            onChange={(event) => setFileType(event.target.value)}
            placeholder="Any type"
            options={FILE_TYPES.map((value) => ({ value, label: value }))}
          />
        </div>

        <DataTable
          data={rows}
          columns={columns}
          getRowId={(row) => row.id}
          isLoading={isLoading}
          isFetching={isFetching}
          error={error}
          loadingLabel="Loading metadata"
          emptyMessage={
            search || status || fileType
              ? 'No metadata matches those filters.'
              : 'No metadata has been extracted yet.'
          }
          rowActions={(row) => (
            <Button
              size="sm"
              variant="outline"
              aria-label={`Show all metadata for ${row.file_name ?? row.file_id}`}
              leadingIcon={<FileJson className="size-3.5" aria-hidden="true" />}
              onClick={() => setShowing(row)}
            >
              View all
            </Button>
          )}
        />

        {showing ? (
          <FileMetadataDetailModal
            row={showing}
            onClose={() => setShowing(null)}
          />
        ) : null}
      </div>
    </RequirePermission>
  )
}
