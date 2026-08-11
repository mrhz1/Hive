import {
  Check,
  CheckCheck,
  Eye,
  FileJson,
  ShieldCheck,
  ShieldOff,
  Trash2,
  X,
} from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { toast } from 'sonner'
import { ConfirmDeleteModal } from '@/components/ConfirmDeleteModal'
import { DataTable, type Column } from '@/components/DataTable'
import { ReasonDialog } from '@/components/ReasonDialog'
import { Button } from '@/components/ui/Button'
import { TextField } from '@/components/ui/Field'
import { Badge } from '@/components/ui/Misc'
import { Spinner } from '@/components/ui/Spinner'
import { DropdownMenu, type MenuAction } from '@/components/ui/DropdownMenu'
import { FileMetadataModal } from '@/features/applications/FileMetadataModal'
import { FileViewerModal } from '@/features/patients/FileViewerModal'
import { FolderUpload } from '@/features/patients/FolderUpload'
import {
  useApplicationFiles,
  useApproveAllFiles,
  useBackgroundUpload,
  useDeidentifyAllFiles,
  useDeidentifyFile,
  useDeleteApplicationFile,
  useReviewApplicationFile,
} from '@/hooks/useResources'
import { ApiError } from '@/lib/api/client'
import { applicationFilesApi } from '@/lib/api/resources'
import {
  canDeidentify,
  deidTone,
  fileHaystack,
  formatFileSize,
  hasExtractableMetadata,
  isDeidInFlight,
  previewKind,
  reviewTone,
  undecidedCount,
  type ApplicationFile,
  type UploadJob,
} from '@/schemas/applicationFile'
import { UploadProgress } from './UploadProgress'

export function FileReviewPanel({
  applicationId,
  onUploaded,
  initialFiles,
  onInitialFilesTaken,
}: {
  applicationId: string
  /** Where the batch landed. The wizard records it on the patient. */
  onUploaded?: (folder: string) => void
  /**
   * Picked in step 1, before there was an application to attach them to.
   * Uploaded once on arrival here rather than making the user choose the
   * same folder a second time.
   */
  initialFiles?: File[]
  onInitialFilesTaken?: () => void
}) {
  const filesQuery = useApplicationFiles(applicationId)
  const deidentify = useDeidentifyFile(applicationId)
  const review = useReviewApplicationFile(applicationId)
  const remove = useDeleteApplicationFile(applicationId)

  // The batch reports where it put the files once the first one lands,
  // which is what the wizard records against the patient.
  const onJobFinished = useCallback(
    (job: UploadJob) => {
      if (job.folder && onUploaded) onUploaded(job.folder)
    },
    [onUploaded]
  )

  const upload = useBackgroundUpload(applicationId, onJobFinished)

  // Once per application: the effect re-runs whenever the parent
  // re-renders with the same array, and a second upload would duplicate
  // every document.
  const takenFor = useRef<string | null>(null)
  const { start: startUpload } = upload

  useEffect(() => {
    if (!applicationId || takenFor.current === applicationId) return
    if (!initialFiles || initialFiles.length === 0) return

    takenFor.current = applicationId
    void startUpload({ files: initialFiles })
      .then(() => onInitialFilesTaken?.())
      .catch(() => undefined)
  }, [applicationId, initialFiles, startUpload, onInitialFilesTaken])

  const [openingId, setOpeningId] = useState<string | null>(null)
  const [viewing, setViewing] = useState<{
    file: ApplicationFile
    url: string | null
    isDeidentified: boolean
  } | null>(null)

  const [showingMetadataFor, setShowingMetadataFor] =
    useState<ApplicationFile | null>(null)
  const [rejecting, setRejecting] = useState<ApplicationFile | null>(null)
  const [deleting, setDeleting] = useState<ApplicationFile | null>(null)
  const [search, setSearch] = useState('')

  const approveAll = useApproveAllFiles(applicationId)
  const deidentifyAll = useDeidentifyAllFiles(applicationId)

  const files = useMemo(() => filesQuery.data ?? [], [filesQuery.data])

  // Filtered here rather than server-side: the list is already loaded,
  // and a round trip per keystroke would be slower than the filter.
  const visible = useMemo(() => {
    const term = search.trim().toLowerCase()
    if (!term) return files
    return files.filter((file) => fileHaystack(file).includes(term))
  }, [files, search])

  const undecided = undecidedCount(files)

  /**
   * Only a PDF needs its bytes up front -- the modal renders it in an
   * iframe. DICOM and Word are fetched as rendered previews by the
   * viewer itself, so pulling a 200MB study here would be for nothing.
   */
  async function showFile(file: ApplicationFile, deidentified = false) {
    const extension =
      deidentified && ['doc', 'docx'].includes(file.file_extension)
        ? 'docx'
        : file.file_extension

    if (previewKind(extension) !== 'pdf') {
      setViewing({ file, url: null, isDeidentified: deidentified })
      return
    }

    setOpeningId(file.id)
    try {
      const blob = await applicationFilesApi.fetchContent(file.id, deidentified)
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
    if (viewing?.url) URL.revokeObjectURL(viewing.url)
    setViewing(null)
  }

  function actionsFor(file: ApplicationFile): MenuAction[] {
    const deidentifying = deidentify.isPending && deidentify.variables === file.id
    const reviewing = review.isPending && review.variables?.fileId === file.id

    return [
      {
        id: 'original',
        label: 'View original',
        icon: <Eye className="size-4" aria-hidden="true" />,
        isLoading: openingId === file.id,
        onSelect: () => void showFile(file),
      },
      {
        id: 'deidentified',
        label: 'View de-identified',
        icon: <ShieldCheck className="size-4" aria-hidden="true" />,
        disabled: !file.de_identified_file_path,
        title: file.de_identified_file_path
          ? undefined
          : 'No redacted copy has been produced yet',
        onSelect: () => void showFile(file, true),
      },
      {
        id: 'metadata',
        label: 'Show metadata',
        icon: <FileJson className="size-4" aria-hidden="true" />,
        disabled: !hasExtractableMetadata(file.file_extension),
        title: hasExtractableMetadata(file.file_extension)
          ? undefined
          : 'Metadata is only read from PDF, DICOM and Word files',
        onSelect: () => setShowingMetadataFor(file),
      },
      {
        id: 'deidentify',
        separatorBefore: true,
        label: file.deid_status === 'done' ? 'Re-run de-identification' : 'De-identify',
        icon: canDeidentify(file.file_extension) ? (
          <ShieldCheck className="size-4" aria-hidden="true" />
        ) : (
          <ShieldOff className="size-4" aria-hidden="true" />
        ),
        disabled:
          !canDeidentify(file.file_extension) || isDeidInFlight(file.deid_status),
        title: !canDeidentify(file.file_extension)
          ? 'Only PDF, DICOM and Word files can be de-identified'
          : isDeidInFlight(file.deid_status)
            ? 'Already running'
            : undefined,
        isLoading: deidentifying,
        onSelect: () => deidentify.mutate(file.id),
      },
      {
        id: 'approve',
        separatorBefore: true,
        label: 'Approve',
        icon: <Check className="size-4" aria-hidden="true" />,
        disabled: file.review_status === 'approved',
        title:
          file.review_status === 'approved' ? 'Already approved' : undefined,
        isLoading: reviewing && review.variables?.reviewStatus === 'approved',
        onSelect: () =>
          review.mutate({ fileId: file.id, reviewStatus: 'approved' }),
      },
      {
        id: 'reject',
        label: 'Reject',
        icon: <X className="size-4" aria-hidden="true" />,
        tone: 'danger',
        onSelect: () => setRejecting(file),
      },
      {
        id: 'delete',
        separatorBefore: true,
        label: 'Delete file',
        icon: <Trash2 className="size-4" aria-hidden="true" />,
        tone: 'danger',
        isLoading: remove.isPending && remove.variables === file.id,
        onSelect: () => setDeleting(file),
      },
    ]
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
      sortValue: (file) => file.original_file_name.toLowerCase(),
    },
    {
      id: 'type',
      header: 'Type',
      cell: (file) => (
        <Badge tone="neutral">{file.file_extension || 'file'}</Badge>
      ),
      sortValue: (file) => file.file_extension,
    },
    {
      id: 'review',
      header: 'Review',
      cell: (file) => (
        <div className="min-w-0">
          {/* The menu closes the moment an action is chosen, taking its
              own spinner with it. Without this the row sits unchanged
              for a few seconds and nothing says anything happened. */}
          {review.isPending && review.variables?.fileId === file.id ? (
            <span className="inline-flex items-center gap-2 text-xs font-semibold text-[rgb(var(--foreground-muted))]">
              <Spinner size="sm" label="" />
              {review.variables.reviewStatus === 'approved'
                ? 'Approving…'
                : 'Rejecting…'}
            </span>
          ) : (
            <>
              <Badge tone={reviewTone(file.review_status)}>
                {file.review_status}
              </Badge>
              {file.review_note ? (
                <span
                  className="mt-1 block truncate text-xs text-[rgb(var(--foreground-muted))]"
                  title={file.review_note}
                >
                  {file.review_note}
                </span>
              ) : null}
            </>
          )}
        </div>
      ),
      sortValue: (file) => file.review_status,
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
        isUploading={upload.isSending}
        onUpload={async (files, description) => {
          await upload.start({
            files,
            ...(description ? { description } : {}),
          })
        }}
      />

      {upload.job ? (
        <UploadProgress job={upload.job} onDismiss={upload.dismiss} />
      ) : null}

      <div className="flex flex-wrap items-end justify-between gap-4 rounded-lg border border-[rgb(var(--border))] bg-[rgb(var(--surface))] p-4">
        <div className="min-w-64 flex-1">
          <TextField
            label="Search"
            value={search}
            onChange={(event) => setSearch(event.target.value)}
            placeholder="Find a document by name, type or description..."
            aria-label="Search documents"
          />
        </div>

        <div className="flex flex-wrap items-center gap-2">
          <Button
            variant="outline"
            disabled={undecided === 0}
            title={
              undecided === 0
                ? 'Every document has been decided'
                : `Approve the ${undecided} document${undecided === 1 ? '' : 's'} still waiting`
            }
            isLoading={approveAll.isPending}
            leadingIcon={<CheckCheck className="size-4" aria-hidden="true" />}
            onClick={() => approveAll.mutate()}
          >
            Approve all
          </Button>
          <Button
            variant="outline"
            disabled={files.length === 0}
            isLoading={deidentifyAll.isPending}
            leadingIcon={<ShieldCheck className="size-4" aria-hidden="true" />}
            onClick={() => deidentifyAll.mutate()}
          >
            De-identify all
          </Button>
        </div>
      </div>

      <DataTable
        data={visible}
        columns={columns}
        getRowId={(file) => file.id}
        isLoading={filesQuery.isLoading}
        isFetching={filesQuery.isFetching}
        error={filesQuery.error}
        loadingLabel="Loading files"
        emptyMessage={
          search.trim()
            ? `No document matches "${search.trim()}".`
            : 'No documents yet. Choose a folder above to add them.'
        }
        rowActions={(file) => (
          <DropdownMenu
            actions={actionsFor(file)}
            label={`Actions for ${file.original_file_name}`}
          />
        )}
      />

      {showingMetadataFor ? (
        <FileMetadataModal
          file={showingMetadataFor}
          onClose={() => setShowingMetadataFor(null)}
        />
      ) : null}

      {rejecting ? (
        <ReasonDialog
          title={`Reject ${rejecting.original_file_name}?`}
          description="The reason is shown against the document, so whoever has to fix it knows what was wrong."
          confirmLabel="Reject file"
          placeholder="e.g. illegible, needs rescanning"
          isBusy={review.isPending}
          onCancel={() => setRejecting(null)}
          onConfirm={(note) => {
            void review
              .mutateAsync({
                fileId: rejecting.id,
                reviewStatus: 'rejected',
                note,
              })
              .then(() => setRejecting(null))
              .catch(() => undefined)
          }}
        />
      ) : null}

      <ConfirmDeleteModal
        open={Boolean(deleting)}
        entityLabel="Document"
        targetName={deleting?.original_file_name}
        isDeleting={remove.isPending}
        onCancel={() => setDeleting(null)}
        onConfirm={() => {
          if (!deleting) return
          void remove
            .mutateAsync(deleting.id)
            .then(() => setDeleting(null))
            .catch(() => undefined)
        }}
      />

      {viewing ? (
        <FileViewerModal
          file={viewing.file}
          fileId={viewing.file.id}
          blobUrl={viewing.url}
          isDeidentified={viewing.isDeidentified}
          onClose={closeViewer}
        />
      ) : null}
    </div>
  )
}
