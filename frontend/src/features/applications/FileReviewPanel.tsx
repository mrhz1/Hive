import { Check, Eye, ShieldCheck, X } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { DataTable, type Column } from '@/components/DataTable'
import { Button } from '@/components/ui/Button'
import { Badge } from '@/components/ui/Misc'
import { FileViewerModal } from '@/features/patients/FileViewerModal'
import { FolderUpload } from '@/features/patients/FolderUpload'
import {
  usePatientFiles,
  useDeidentifyFile,
  useReviewPatientFile,
  useUploadPatientFiles,
} from '@/hooks/useResources'
import { ApiError } from '@/lib/api/client'
import { patientFilesApi } from '@/lib/api/resources'
import {
  deidTone,
  formatFileSize,
  reviewTone,
  type PatientFile,
} from '@/schemas/patientFile'

/**
 * Step 2 of the application wizard: the documents attached to the
 * patient, each with the actions a reviewer needs.
 *
 * Files land here from step 1's folder pick, and more can be added --
 * the same upload panel the standalone files page uses, so there is one
 * upload path rather than two that can drift.
 */
export function FileReviewPanel({ patientId }: { patientId: string }) {
  const filesQuery = usePatientFiles(patientId)
  const upload = useUploadPatientFiles(patientId)
  const deidentify = useDeidentifyFile(patientId)
  const review = useReviewPatientFile(patientId)

  const [openingId, setOpeningId] = useState<string | null>(null)
  const [viewing, setViewing] = useState<{
    file: PatientFile
    url: string
    isDeidentified: boolean
  } | null>(null)

  // A rejection must carry a reason, so the row expands into a prompt
  // rather than firing the mutation straight away.
  const [rejecting, setRejecting] = useState<PatientFile | null>(null)
  const [reason, setReason] = useState('')

  /**
   * The endpoint requires an identity header, so the browser cannot just
   * navigate to it -- the bytes come through the API client and are then
   * shown from a blob URL.
   */
  async function showFile(file: PatientFile, deidentified = false) {
    setOpeningId(file.id)
    try {
      const blob = await patientFilesApi.fetchContent(file.id, deidentified)
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

  const columns: Array<Column<PatientFile>> = [
    {
      id: 'name',
      header: 'File',
      cell: (file) => (
        <div className="min-w-0">
          <span className="block truncate font-semibold">{file.original_file_name}</span>
          <span className="block truncate text-xs text-[rgb(var(--foreground-muted))]">
            {formatFileSize(file.file_size)}
            {file.review_description ? ` · ${file.review_description}` : ''}
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
    {
      id: 'review',
      header: 'Review',
      cell: (file) => (
        <Badge tone={reviewTone(file.review_status)}>{file.review_status}</Badge>
      ),
      sortValue: (file) => file.review_status,
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
            <Button
              size="sm"
              variant="secondary"
              aria-label={`Approve ${file.original_file_name}`}
              disabled={file.review_status === 'approved'}
              leadingIcon={<Check className="size-3.5" aria-hidden="true" />}
              onClick={() =>
                review.mutate({ fileId: file.id, reviewStatus: 'approved' })
              }
            >
              Approve
            </Button>
            <Button
              size="sm"
              variant="danger"
              aria-label={`Reject ${file.original_file_name}`}
              leadingIcon={<X className="size-3.5" aria-hidden="true" />}
              onClick={() => {
                setRejecting(file)
                setReason(file.review_description ?? '')
              }}
            >
              Reject
            </Button>
          </>
        )}
      />

      {rejecting ? (
        <div
          role="dialog"
          aria-label={`Reject ${rejecting.original_file_name}`}
          className="space-y-3 rounded-xl border border-[rgb(var(--border))] bg-[rgb(var(--surface))] p-5 shadow-sm"
        >
          <h3 className="text-sm font-semibold">
            Reject {rejecting.original_file_name}
          </h3>
          <p className="text-xs text-[rgb(var(--foreground-muted))]">
            A reason is required — without one the uploader has no idea what to fix.
          </p>
          <textarea
            value={reason}
            onChange={(event) => setReason(event.target.value)}
            rows={3}
            aria-label="Rejection reason"
            placeholder="What is wrong with this document?"
            className="w-full rounded-lg border border-[rgb(var(--border))] bg-[rgb(var(--input-bg))] px-4 py-2.5 text-sm text-[rgb(var(--input-text))] transition-all outline-none focus:border-[rgb(var(--input-ring))] focus:ring-4 focus:ring-[rgb(var(--input-ring))]/15"
          />
          <div className="flex flex-wrap gap-3">
            <Button
              variant="danger"
              disabled={reason.trim() === ''}
              isLoading={review.isPending}
              onClick={async () => {
                await review.mutateAsync({
                  fileId: rejecting.id,
                  reviewStatus: 'rejected',
                  description: reason.trim(),
                })
                setRejecting(null)
                setReason('')
              }}
            >
              Confirm rejection
            </Button>
            <Button variant="outline" onClick={() => setRejecting(null)}>
              Cancel
            </Button>
          </div>
        </div>
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
