import { Eye, FileJson, ShieldCheck } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { DataTable, type Column } from '@/components/DataTable'
import { Button } from '@/components/ui/Button'
import { Badge } from '@/components/ui/Misc'
import { FileMetadataModal } from '@/features/applications/FileMetadataModal'
import { FileViewerModal } from '@/features/patients/FileViewerModal'
import { FolderUpload } from '@/features/patients/FolderUpload'
import {
  useApplicationFiles,
  useDeidentifyFile,
  useUploadApplicationFiles,
} from '@/hooks/useResources'
import { ApiError } from '@/lib/api/client'
import { applicationFilesApi } from '@/lib/api/resources'
import {
  canDeidentify,
  deidTone,
  formatFileSize,
  hasExtractableMetadata,
  isDeidInFlight,
  type ApplicationFile,
} from '@/schemas/applicationFile'

export function FileReviewPanel({ applicationId }: { applicationId: string }) {
  const filesQuery = useApplicationFiles(applicationId)
  const upload = useUploadApplicationFiles(applicationId)
  const deidentify = useDeidentifyFile(applicationId)

  const [openingId, setOpeningId] = useState<string | null>(null)
  const [viewing, setViewing] = useState<{
    file: ApplicationFile
    url: string
    isDeidentified: boolean
  } | null>(null)

  const [showingMetadataFor, setShowingMetadataFor] =
    useState<ApplicationFile | null>(null)

  async function showFile(file: ApplicationFile, deidentified = false) {
    setOpeningId(file.id)
    try {
      const blob = await applicationFilesApi.fetchContent(file.id, deidentified)
      setViewing({ file, url: URL.createObjectURL(blob), isDeidentified: deidentified })
    } catch (error) {
      toast.error(error instanceof ApiError ? error.message : 'Could not open this file')
    } finally {
      setOpeningId(null)
    }
  }

  function closeViewer() {
    if (viewing) URL.revokeObjectURL(viewing.url)
    setViewing(null)
  }

  const columns: Array<Column<ApplicationFile>> = [
    {
      id: 'name',
      header: 'File',
      cell: (file) => (
        <div className="min-w-0">
          <span className="block truncate font-semibold">{file.original_file_name}</span>
          <span className="block truncate text-xs text-[rgb(var(--foreground-muted))]">
            {formatFileSize(file.file_size)}
            {file.description ? ` · ${file.description}` : ''}
          </span>
        </div>
      ),
      sortValue: (file) => file.original_file_name,
    },
    {
      id: 'deid',
      header: 'De-identified',
      cell: (file) => (
        <div className="flex flex-wrap items-center gap-1.5">
          <Badge tone={deidTone(file.deid_status)}>{file.deid_status}</Badge>
          {file.is_deidentified ? (
            <Badge tone="success">redacted</Badge>
          ) : (
            <Badge tone="warning">contains PII</Badge>
          )}
        </div>
      ),
      sortValue: (file) => file.deid_status,
    },
  ]

  return (
    <div className="space-y-6">
      <FolderUpload
        isUploading={upload.isPending}
        onUpload={(files, description) =>
          upload.mutateAsync({ files, ...(description ? { description } : {}) })
        }
      />

      <DataTable
        data={filesQuery.data}
        columns={columns}
        getRowId={(file) => file.id}
        isLoading={filesQuery.isLoading}
        isFetching={filesQuery.isFetching}
        error={filesQuery.error}
        loadingLabel="Loading files"
        emptyMessage="No documents yet. Choose a folder above to add them."
        rowActions={(file) => (
          <>
            <Button
              size="sm"
              aria-label={`View original ${file.original_file_name}`}
              isLoading={openingId === file.id}
              leadingIcon={<Eye className="size-3.5" aria-hidden="true" />}
              onClick={() => void showFile(file)}
            >
              Original
            </Button>
            <Button
              size="sm"
              variant="secondary"
              aria-label={`View de-identified ${file.original_file_name}`}
              // Nothing to show until the job has produced a redacted copy.
              disabled={!file.de_identified_file_path}
              onClick={() => void showFile(file, true)}
            >
              De-identified
            </Button>
            <Button
              size="sm"
              variant="outline"
              aria-label={`De-identify ${file.original_file_name}`}
              disabled={
                !canDeidentify(file.file_extension) ||
                isDeidInFlight(file.deid_status)
              }
              isLoading={deidentify.isPending && deidentify.variables === file.id}
              leadingIcon={<ShieldCheck className="size-3.5" aria-hidden="true" />}
              onClick={() => deidentify.mutate(file.id)}
            >
              {file.deid_status === 'done' ? 'Re-run' : 'De-identify'}
            </Button>
            <Button
              size="sm"
              variant="outline"
              aria-label={`Show metadata for ${file.original_file_name}`}
              disabled={!hasExtractableMetadata(file.file_extension)}
              leadingIcon={<FileJson className="size-3.5" aria-hidden="true" />}
              onClick={() => setShowingMetadataFor(file)}
            >
              Show metadata
            </Button>
          </>
        )}
      />

      {showingMetadataFor ? (
        <FileMetadataModal
          file={showingMetadataFor}
          onClose={() => setShowingMetadataFor(null)}
        />
      ) : null}

      {viewing ? (
        <FileViewerModal
          file={viewing.file}
          blobUrl={viewing.url}
          isDeidentified={viewing.isDeidentified}
          onClose={closeViewer}
        />
      ) : null}
    </div>
  )
}
