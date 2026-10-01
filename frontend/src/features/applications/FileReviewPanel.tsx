import { Eye, FileJson, FileSearch, ShieldCheck, X } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'
import { DataTable, type Column } from '@/components/DataTable'
import { ReasonDialog } from '@/components/ReasonDialog'
import { TextField } from '@/components/ui/Field'
import { Badge, Card } from '@/components/ui/Misc'
import { Spinner } from '@/components/ui/Spinner'
import { DropdownMenu, type MenuAction } from '@/components/ui/DropdownMenu'
import { FileMetadataModal } from '@/features/applications/FileMetadataModal'
import { FileViewerModal } from '@/features/patients/FileViewerModal'
import { usePermissions } from '@/hooks/useCurrentUser'
import {
  useApplicationFiles,
  useBackgroundUpload,
  useReviewApplicationFile,
} from '@/hooks/useResources'
import { ApiError } from '@/lib/api/client'
import { applicationFilesApi } from '@/lib/api/resources'
import {
  deidTone,
  fileTally,
  fileSearchText,
  formatFileSize,
  hasExtractableMetadata,
  isDeletedFile,
  previewKind,
  reviewTone,
  type ApplicationFile,
  type UploadJob,
} from '@/schemas/applicationFile'
import { FileTallyBar } from './FileTallyBar'
import { UploadProgress } from './UploadProgress'

const NOT_REVIEWABLE = 'There is no de-identified copy of this document to review'

export function FileReviewPanel({
  applicationId,
  onUploaded,
  initialFiles,
  onInitialFilesTaken,
  readOnly = false,
  deleted = false,
}: {
  applicationId: string

  onUploaded?: (folder: string) => void

  initialFiles?: File[]
  onInitialFilesTaken?: () => void

  readOnly?: boolean

  /** The application's documents were deleted; only the records remain. */
  deleted?: boolean
}) {
  const { can } = usePermissions()
  const filesQuery = useApplicationFiles(applicationId)
  const review = useReviewApplicationFile(applicationId)

  const onJobFinished = useCallback(
    (job: UploadJob) => {
      if (job.folder && onUploaded) onUploaded(job.folder)
    },
    [onUploaded]
  )

  const upload = useBackgroundUpload(applicationId, onJobFinished)

  const takenFor = useRef<string | null>(null)
  const { start: startUpload } = upload

  useEffect(() => {
    if (readOnly) return
    if (!applicationId || takenFor.current === applicationId) return
    if (!initialFiles || initialFiles.length === 0) return

    takenFor.current = applicationId
    void startUpload({ files: initialFiles })
      .then(() => onInitialFilesTaken?.())
      .catch(() => undefined)
  }, [applicationId, initialFiles, startUpload, onInitialFilesTaken, readOnly])

  const [openingId, setOpeningId] = useState<string | null>(null)
  const [viewing, setViewing] = useState<{
    file: ApplicationFile
    url: string | null
    isDeidentified: boolean
  } | null>(null)

  const [showingMetadata, setShowingMetadata] = useState<{
    file: ApplicationFile
    deidentified: boolean
  } | null>(null)
  const [rejecting, setRejecting] = useState<ApplicationFile | null>(null)
  const [search, setSearch] = useState('')

  const files = filesQuery.data ?? []
  const searchText = search.trim().toLowerCase()
  const visible = searchText
    ? files.filter((file) => fileSearchText(file).includes(searchText))
    : files

  const tally = fileTally(files)

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
    // Its documents were deleted from Rejections: nothing left to open or change.
    if (isDeletedFile(file)) return []
    const hasCopy = Boolean(file.de_identified_file_path)
    const noCopy = 'No redacted copy has been produced yet'
    const actions: MenuAction[] = []

    if (!readOnly && can('files:view_original')) {
      actions.push({
        id: 'original',
        label: 'View original',
        icon: <Eye className="size-4" aria-hidden="true" />,
        isLoading: openingId === file.id,
        onSelect: () => void showFile(file),
      })
    }
    if (can('files:view_deidentified')) {
      actions.push({
        id: 'deidentified',
        label: 'View de-identified',
        icon: <ShieldCheck className="size-4" aria-hidden="true" />,
        isLoading: readOnly && openingId === file.id,
        disabled: !hasCopy,
        title: hasCopy ? undefined : noCopy,
        onSelect: () => void showFile(file, true),
      })
    }
    if (!readOnly && can('files:metadata')) {
      actions.push({
        id: 'metadata',
        label: 'Show metadata',
        icon: <FileJson className="size-4" aria-hidden="true" />,
        disabled: !hasExtractableMetadata(file.file_extension),
        title: hasExtractableMetadata(file.file_extension)
          ? undefined
          : 'Metadata is only read from PDF, DICOM and Word files',
        onSelect: () => setShowingMetadata({ file, deidentified: false }),
      })
    }
    if (can('files:deid_metadata')) {
      actions.push({
        id: 'deid-metadata',
        label: 'De-identified metadata',
        icon: <FileSearch className="size-4" aria-hidden="true" />,
        disabled: !hasCopy,
        title: hasCopy ? 'What the redacted copy still carries' : noCopy,
        onSelect: () => setShowingMetadata({ file, deidentified: true }),
      })
    }
    if (readOnly) return actions

    if (can('files:reject')) {
      actions.push({
        id: 'reject',
        separatorBefore: actions.length > 0,
        label: 'Reject',
        icon: <X className="size-4" aria-hidden="true" />,
        tone: 'danger',
        disabled: !file.is_deidentified || file.review_status === 'rejected',
        title: !file.is_deidentified
          ? NOT_REVIEWABLE
          : file.review_status === 'rejected'
            ? 'Already rejected'
            : undefined,
        onSelect: () => setRejecting(file),
      })
    }
    return actions
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
      cell: (file) => <Badge tone="neutral">{file.file_extension || 'file'}</Badge>,
      sortValue: (file) => file.file_extension,
    },
    {
      id: 'review',
      header: 'Review',
      cell: (file) => (
        <div className="min-w-0">
          {}
          {review.isPending && review.variables?.fileId === file.id ? (
            <span className="inline-flex items-center gap-2 text-xs font-semibold text-[rgb(var(--foreground-muted))]">
              <Spinner size="sm" label="" />
              Rejecting…
            </span>
          ) : (
            <>
              <Badge tone={reviewTone(file.review_status)}>{file.review_status}</Badge>
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
      {deleted ? (
        <Card className="border-[rgb(var(--border))] p-4 text-sm text-[rgb(var(--foreground-muted))]">
          These documents were deleted. The list below is the record of what was attached;
          none of them can be opened.
        </Card>
      ) : readOnly ? (
        <Card className="border-[rgb(var(--border))] p-4 text-sm text-[rgb(var(--foreground-muted))]">
          This application has been submitted. Its documents are shown as they were sent
          -- the de-identified copy and what it carries.
        </Card>
      ) : upload.job ? (
        <UploadProgress job={upload.job} onDismiss={upload.dismiss} />
      ) : null}

      <FileTallyBar tally={tally} />

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
            : readOnly
              ? 'No documents were attached to this application.'
              : "No documents yet. Pick this application's source folder in step 1 to add them."
        }
        rowActions={(file) => {
          const actions = actionsFor(file)
          return actions.length > 0 ? (
            <DropdownMenu
              actions={actions}
              label={`Actions for ${file.original_file_name}`}
            />
          ) : null
        }}
      />

      {showingMetadata ? (
        <FileMetadataModal
          file={showingMetadata.file}
          deidentified={showingMetadata.deidentified}
          onClose={() => setShowingMetadata(null)}
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

      {viewing ? (
        <FileViewerModal
          file={viewing.file}
          fileId={viewing.file.id}
          blobUrl={viewing.url}
          isDeidentified={viewing.isDeidentified}
          canViewOriginal={!readOnly && can('files:view_original')}
          onClose={closeViewer}
        />
      ) : null}
    </div>
  )
}
