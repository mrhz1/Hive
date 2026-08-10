import { createFileRoute } from '@tanstack/react-router'
import { Download, FileJson, Trash2 } from 'lucide-react'
import { useMemo, useState } from 'react'
import { toast } from 'sonner'
import { DataTable, type Column } from '@/components/DataTable'
import { Can, RequirePermission } from '@/components/PermissionGate'
import { Button } from '@/components/ui/Button'
import { TextField } from '@/components/ui/Field'
import { Badge, PageHeader } from '@/components/ui/Misc'
import { DeidentifiedFileMetadataModal } from '@/features/files/DeidentifiedFileMetadataModal'
import { DeidentifiedUpload } from '@/features/files/DeidentifiedUpload'
import { FileViewerModal } from '@/features/patients/FileViewerModal'
import {
  useDeidentifiedFiles,
  useDeleteDeidentifiedFile,
} from '@/hooks/useResources'
import { ApiError } from '@/lib/api/client'
import { deidentifiedFilesApi } from '@/lib/api/resources'
import { formatFileSize } from '@/schemas/applicationFile'
import {
  fileHaystack,
  type DeidentifiedFile,
} from '@/schemas/deidentifiedFile'

export const Route = createFileRoute('/files/')({
  component: FilesPage,
})

const MIME_BY_TYPE: Record<string, string> = {
  pdf: 'application/pdf',
  dcm: 'application/dicom',
  dicom: 'application/dicom',
  doc: 'application/msword',
  docx: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
}

function formatDate(value: string): string {
  const date = new Date(value)
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString()
}

function FilesPage() {
  const { data, isLoading, isFetching, error } = useDeidentifiedFiles()
  const remove = useDeleteDeidentifiedFile()

  const [search, setSearch] = useState('')
  const [openingId, setOpeningId] = useState<string | null>(null)
  const [viewing, setViewing] = useState<{
    file: DeidentifiedFile
    url: string
  } | null>(null)
  const [showingMetadataFor, setShowingMetadataFor] =
    useState<DeidentifiedFile | null>(null)

  const filtered = useMemo(() => {
    const term = search.trim().toLowerCase()
    if (!term) return data ?? []
    return (data ?? []).filter((file) => fileHaystack(file).includes(term))
  }, [data, search])

  async function open(file: DeidentifiedFile) {
    setOpeningId(file.id)
    try {
      const blob = await deidentifiedFilesApi.fetchContent(file.id)
      setViewing({ file, url: URL.createObjectURL(blob) })
    } catch (caught) {
      toast.error(
        caught instanceof ApiError ? caught.message : 'Could not open this file'
      )
    } finally {
      setOpeningId(null)
    }
  }

  function closeViewer() {
    if (viewing) URL.revokeObjectURL(viewing.url)
    setViewing(null)
  }

  const columns: Array<Column<DeidentifiedFile>> = [
    {
      id: 'name',
      header: 'Name',
      cell: (file) => (
        <div className="min-w-0">
          <span className="block truncate font-semibold">{file.name}</span>
          <span className="block truncate text-xs text-[rgb(var(--foreground-muted))]">
            {file.patient_id} · {formatFileSize(file.file_size)}
          </span>
        </div>
      ),
      sortValue: (file) => file.name.toLowerCase(),
    },
    {
      id: 'type',
      header: 'Type',
      cell: (file) => <Badge tone="neutral">{file.file_type || 'file'}</Badge>,
      sortValue: (file) => file.file_type,
    },
    {
      id: 'date',
      header: 'Date',
      cell: (file) => (
        <span className="whitespace-nowrap text-sm">
          {formatDate(file.created_at)}
        </span>
      ),
      sortValue: (file) => file.created_at,
    },
  ]

  return (
    <RequirePermission permission="files:read">
      <div className="space-y-6">
        <PageHeader
          title="Files"
          description="De-identified documents, across every patient."
        />

        <Can permission="files:upload">
          <DeidentifiedUpload files={data ?? []} />
        </Can>

        <div className="flex flex-wrap items-center justify-between gap-4 rounded-lg border border-[rgb(var(--border))] bg-[rgb(var(--surface))] p-4">
          <TextField
            label="Search"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Search by file name, patient id or type..."
            aria-label="Search files"
          />
        </div>

        <DataTable
          data={filtered}
          columns={columns}
          getRowId={(file) => file.id}
          isLoading={isLoading}
          isFetching={isFetching}
          error={error}
          loadingLabel="Loading files"
          emptyMessage="No de-identified files yet."
          rowActions={(file) => (
            <>
              <Can permission="files:download">
                <Button
                  size="sm"
                  aria-label={`Open ${file.name}`}
                  isLoading={openingId === file.id}
                  leadingIcon={<Download className="size-3.5" aria-hidden="true" />}
                  onClick={() => void open(file)}
                >
                  Open
                </Button>
              </Can>
              <Button
                size="sm"
                variant="outline"
                aria-label={`Show metadata for ${file.name}`}
                leadingIcon={<FileJson className="size-3.5" aria-hidden="true" />}
                onClick={() => setShowingMetadataFor(file)}
              >
                Metadata
              </Button>
              <Can permission="files:delete">
                <Button
                  size="sm"
                  variant="danger"
                  aria-label={`Delete ${file.name}`}
                  isLoading={remove.isPending && remove.variables === file.id}
                  leadingIcon={<Trash2 className="size-3.5" aria-hidden="true" />}
                  onClick={() => remove.mutate(file.id)}
                >
                  Delete
                </Button>
              </Can>
            </>
          )}
        />

        {showingMetadataFor ? (
          <DeidentifiedFileMetadataModal
            file={showingMetadataFor}
            onClose={() => setShowingMetadataFor(null)}
          />
        ) : null}

        {viewing ? (
          <FileViewerModal
            file={{
              original_file_name: viewing.file.name,
              deidentified_file_name: viewing.file.name,
              mime_type: MIME_BY_TYPE[viewing.file.file_type] ?? 'application/pdf',
              file_size: viewing.file.file_size,
            }}
            blobUrl={viewing.url}
            isDeidentified
            onClose={closeViewer}
          />
        ) : null}
      </div>
    </RequirePermission>
  )
}
