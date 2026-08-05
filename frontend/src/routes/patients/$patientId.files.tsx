import { createFileRoute, Link } from '@tanstack/react-router'
import { Eye, ShieldCheck, Trash2 } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { ConfirmDeleteModal } from '@/components/ConfirmDeleteModal'
import { DataTable, type Column } from '@/components/DataTable'
import { NotFoundPage } from '@/components/ErrorPages'
import { Can, RequirePermission } from '@/components/PermissionGate'
import { Button } from '@/components/ui/Button'
import { Badge, PageHeader } from '@/components/ui/Misc'
import { LoadingBlock } from '@/components/ui/Spinner'
import { FileViewerModal } from '@/features/patients/FileViewerModal'
import { FolderUpload } from '@/features/patients/FolderUpload'
import { usePermissions } from '@/hooks/useCurrentUser'
import { useDeleteDialog } from '@/hooks/useDeleteDialog'
import { useDocumentTitle } from '@/hooks/useDocumentTitle'
import {
  patientHooks,
  usePatientFiles,
  useDeidentifyFile,
  useDeletePatientFile,
  useUploadPatientFiles,
} from '@/hooks/useResources'
import { ApiError } from '@/lib/api/client'
import { patientFilesApi } from '@/lib/api/resources'
import { patientName } from '@/schemas/patient'
import { formatFileSize, type PatientFile } from '@/schemas/patientFile'

/** Colour the de-identification state so progress is scannable. */
function deidTone(status: string): 'success' | 'warning' | 'danger' | 'neutral' {
  if (status === 'done') return 'success'
  if (status === 'processing') return 'warning'
  if (status === 'failed') return 'danger'
  return 'neutral'
}

function PatientFilesPage() {
  const { patientId } = Route.useParams()
  const { can } = usePermissions()

  const patientQuery = patientHooks.useDetail(patientId)
  const filesQuery = usePatientFiles(patientId)
  const upload = useUploadPatientFiles(patientId)
  const remove = useDeletePatientFile(patientId)
  const deidentify = useDeidentifyFile(patientId)

  const patient = patientQuery.data
  useDocumentTitle(
    patient ? `Files · ${patientName(patient)}` : 'Patient files'
  )

  const deleteDialog = useDeleteDialog<PatientFile>((file) =>
    remove.mutateAsync(file.id)
  )

  const [openingId, setOpeningId] = useState<string | null>(null)
  const [viewing, setViewing] = useState<{
    file: PatientFile
    url: string
    isDeidentified: boolean
  } | null>(null)

  /**
   * The endpoint requires an identity header, so the browser cannot just
   * navigate to it -- the bytes have to come through the API client and
   * are then shown from a blob URL.
   */
  async function showFile(file: PatientFile, deidentified = false) {
    setOpeningId(file.id)
    try {
      const blob = await patientFilesApi.fetchContent(file.id, deidentified)
      setViewing({
        file,
        url: URL.createObjectURL(blob),
        isDeidentified: deidentified,
      })
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

  if (patientQuery.isLoading) return <LoadingBlock label="Loading patient" />
  if (patientQuery.error instanceof ApiError && patientQuery.error.isNotFound) {
    return <NotFoundPage />
  }
  if (!patient) return <NotFoundPage />

  const columns: Array<Column<PatientFile>> = [
    {
      id: 'name',
      header: 'File',
      cell: (file) => (
        <div className="min-w-0">
          <span className="block truncate font-semibold">{file.original_file_name}</span>
          {file.description ? (
            <span className="block truncate text-xs text-[rgb(var(--foreground-muted))]">
              {file.description}
            </span>
          ) : null}
        </div>
      ),
      sortValue: (file) => file.original_file_name,
    },
    {
      id: 'type',
      header: 'Type',
      cell: (file) => (
        <span className="text-[rgb(var(--foreground-muted))] uppercase">
          {file.file_extension || '—'}
        </span>
      ),
      sortValue: (file) => file.file_extension,
    },
    {
      id: 'size',
      header: 'Size',
      isNumeric: true,
      cell: (file) => formatFileSize(file.file_size),
      sortValue: (file) => file.file_size,
    },
    {
      id: 'deid',
      header: 'De-identified',
      cell: (file) => (
        <div className="flex flex-wrap items-center gap-1.5">
          <Badge tone={deidTone(file.deid_status)}>{file.deid_status}</Badge>
          {file.is_identified ? (
            <Badge tone="warning">contains PII</Badge>
          ) : (
            <Badge tone="success">redacted</Badge>
          )}
        </div>
      ),
      sortValue: (file) => file.deid_status,
    },
    {
      id: 'created',
      header: 'Uploaded',
      cell: (file) => (
        <span className="text-[rgb(var(--foreground-muted))]">
          {file.created_at.slice(0, 16).replace('T', ' ')}
        </span>
      ),
      sortValue: (file) => file.created_at,
    },
  ]

  const canModify = can('patients:update')
  const canDelete = canModify

  return (
    <div className="space-y-6">
      <PageHeader
        title={`Files · ${patientName(patient)}`}
        description={patient.ptemail ?? undefined}
        actions={
          <Link to="/patients">
            <Button variant="outline">Back to patients</Button>
          </Link>
        }
      />

      <Can permission="patients:update">
        <FolderUpload
          isUploading={upload.isPending}
          onUpload={(files, description) =>
            upload.mutateAsync({ files, ...(description ? { description } : {}) })
          }
        />
      </Can>

      <DataTable
        data={filesQuery.data}
        columns={columns}
        getRowId={(file) => file.id}
        isLoading={filesQuery.isLoading}
        isFetching={filesQuery.isFetching}
        error={filesQuery.error}
        loadingLabel="Loading files"
        emptyMessage="No files uploaded for this patient yet."
        rowActions={(file) => (
          <>
            <Button
              size="sm"
              aria-label={`Show ${file.original_file_name}`}
              isLoading={openingId === file.id}
              leadingIcon={<Eye className="size-3.5" aria-hidden="true" />}
              onClick={() => void showFile(file)}
            >
              Show
            </Button>
            {file.deidentified_file_path ? (
              <Button
                size="sm"
                variant="secondary"
                aria-label={`Show de-identified ${file.original_file_name}`}
                onClick={() => void showFile(file, true)}
              >
                Redacted
              </Button>
            ) : null}
            {canModify ? (
              <Button
                size="sm"
                variant="outline"
                aria-label={`De-identify ${file.original_file_name}`}
                // Only PDFs can be processed, and a run already underway
                // must not be started twice.
                disabled={
                  file.file_extension.toLowerCase() !== 'pdf' ||
                  file.deid_status === 'processing'
                }
                isLoading={deidentify.isPending && deidentify.variables === file.id}
                leadingIcon={<ShieldCheck className="size-3.5" aria-hidden="true" />}
                onClick={() => deidentify.mutate(file.id)}
              >
                {file.deid_status === 'done' ? 'Re-run' : 'De-identify'}
              </Button>
            ) : null}
            {canDelete ? (
              <Button
                size="sm"
                variant="danger"
                aria-label={`Delete ${file.original_file_name}`}
                onClick={() => deleteDialog.request(file)}
              >
                <Trash2 className="size-3.5" aria-hidden="true" />
              </Button>
            ) : null}
          </>
        )}
      />

      {viewing ? (
        <FileViewerModal
          file={viewing.file}
          blobUrl={viewing.url}
          isDeidentified={viewing.isDeidentified}
          onClose={closeViewer}
        />
      ) : null}

      <ConfirmDeleteModal
        open={deleteDialog.isOpen}
        entityLabel="File"
        targetName={deleteDialog.target?.original_file_name}
        isDeleting={deleteDialog.isDeleting}
        onCancel={deleteDialog.cancel}
        onConfirm={() => void deleteDialog.confirm()}
      />
    </div>
  )
}

export const Route = createFileRoute('/patients/$patientId/files')({
  component: () => (
    <RequirePermission permission="patients:read">
      <PatientFilesPage />
    </RequirePermission>
  ),
})
