import { createFileRoute, Link, useNavigate } from '@tanstack/react-router'
import { Check, Download, Eye, FileStack, Trash2, Upload } from 'lucide-react'
import { useState } from 'react'
import { toast } from 'sonner'
import { DataTable, type Column } from '@/components/DataTable'
import { ReasonDialog } from '@/components/ReasonDialog'
import { RequirePermission } from '@/components/PermissionGate'
import { DropdownMenu, type MenuAction } from '@/components/ui/DropdownMenu'
import { TextField } from '@/components/ui/Field'
import { Badge, Card, PageHeader } from '@/components/ui/Misc'
import { ReplaceDeidentifiedDialog } from '@/features/files/ReplaceDeidentifiedDialog'
import { FileViewerModal } from '@/features/patients/FileViewerModal'
import { usePermissions } from '@/hooks/useCurrentUser'
import { useDocumentTitle } from '@/hooks/useDocumentTitle'
import {
  useApplications,
  useDeleteApplication,
  usePurgeFile,
  useRejectedFiles,
  useReviewRejectedFile,
} from '@/hooks/useResources'
import { ApiError } from '@/lib/api/client'
import { applicationFilesApi } from '@/lib/api/resources'
import { formatFileSize, previewKind } from '@/schemas/applicationFile'
import type { PatientApplication } from '@/schemas/patientApplication'
import { rejectionSearchText, type RejectedFile } from '@/schemas/rejection'

export const Route = createFileRoute('/rejections/')({
  component: RejectionsPage,
})

const MIME_BY_TYPE: Record<string, string> = {
  pdf: 'application/pdf',
  dcm: 'application/dicom',
  dicom: 'application/dicom',
  doc: 'application/msword',
  docx: 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
}

function formatDate(value: string | null | undefined): string {
  if (!value) return '--'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return value
  return date.toLocaleString()
}

function getErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiError) return error.message
  return fallback
}

function saveBlob(blob: Blob, name: string) {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = name
  document.body.append(link)
  link.click()
  link.remove()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

type ViewerState = {
  file: RejectedFile
  url: string | null
  isDeidentified: boolean
}

function RejectionsPage() {
  useDocumentTitle('Rejections')
  const { can } = usePermissions()
  const navigate = useNavigate()
  const canSeeOriginal = can('files:view_original')
  const canSeeDeidentified = can('files:view_deidentified')

  const filesQuery = useRejectedFiles()
  const applicationsQuery = useApplications(undefined, true, 'rejected')
  const review = useReviewRejectedFile()
  const deleteApplication = useDeleteApplication()
  const purgeFile = usePurgeFile()
  const [deletingApplication, setDeletingApplication] =
    useState<PatientApplication | null>(null)
  const [deletingFile, setDeletingFile] = useState<RejectedFile | null>(null)

  const [search, setSearch] = useState('')
  const [openingId, setOpeningId] = useState<string | null>(null)
  const [downloadingId, setDownloadingId] = useState<string | null>(null)
  const [replacing, setReplacing] = useState<RejectedFile | null>(null)
  const [viewing, setViewing] = useState<ViewerState | null>(null)

  const files = filesQuery.data ?? []
  const searchText = search.trim().toLowerCase()
  const visible = searchText
    ? files.filter((file) => rejectionSearchText(file).includes(searchText))
    : files

  async function open(file: RejectedFile) {
    const deidentified = file.has_deidentified && canSeeDeidentified
    let extension = file.file_extension
    if (deidentified && (extension === 'doc' || extension === 'docx')) {
      extension = 'docx'
    }

    if (previewKind(extension) !== 'pdf') {
      setViewing({ file, url: null, isDeidentified: deidentified })
      return
    }

    setOpeningId(file.id)
    try {
      const blob = await applicationFilesApi.fetchContent(file.id, deidentified)
      setViewing({ file, url: URL.createObjectURL(blob), isDeidentified: deidentified })
    } catch (err) {
      toast.error(getErrorMessage(err, 'Could not open this file'))
    } finally {
      setOpeningId(null)
    }
  }

  function closeViewer() {
    if (viewing?.url) URL.revokeObjectURL(viewing.url)
    setViewing(null)
  }

  async function download(file: RejectedFile, deidentified: boolean) {
    setDownloadingId(`${file.id}:${deidentified}`)
    try {
      const blob = await applicationFilesApi.fetchContent(file.id, deidentified, true)
      let name = file.original_file_name
      if (deidentified && file.deidentified_file_name) {
        name = file.deidentified_file_name
      }
      saveBlob(blob, name)
    } catch (err) {
      toast.error(getErrorMessage(err, 'Could not download this file'))
    } finally {
      setDownloadingId(null)
    }
  }

  function applicationActions(application: PatientApplication): MenuAction[] {
    const actions: MenuAction[] = [
      {
        id: 'open',
        label: 'Open application',
        icon: <FileStack className="size-4" aria-hidden="true" />,
        onSelect: () =>
          void navigate({
            to: '/applications/$applicationId',
            params: { applicationId: application.id },
          }),
      },
    ]
    if (can('application:delete')) {
      actions.push({
        id: 'delete',
        separatorBefore: true,
        label: 'Delete application',
        icon: <Trash2 className="size-4" aria-hidden="true" />,
        tone: 'danger',
        onSelect: () => setDeletingApplication(application),
      })
    }
    return actions
  }

  function fileActions(file: RejectedFile): MenuAction[] {
    const actions: MenuAction[] = []
    const canDownload = can('files:download')

    if (canSeeOriginal || canSeeDeidentified) {
      actions.push({
        id: 'view',
        label: 'View',
        icon: <Eye className="size-4" aria-hidden="true" />,
        isLoading: openingId === file.id,
        disabled:
          !(file.has_original && canSeeOriginal) &&
          !(file.has_deidentified && canSeeDeidentified),
        onSelect: () => void open(file),
      })
    }
    if (canSeeOriginal && canDownload) {
      actions.push({
        id: 'download-original',
        label: 'Download original',
        icon: <Download className="size-4" aria-hidden="true" />,
        disabled: !file.has_original,
        title: file.has_original
          ? 'The identified original'
          : 'No identified copy is on disk',
        isLoading: downloadingId === `${file.id}:false`,
        onSelect: () => void download(file, false),
      })
    }
    if (canSeeDeidentified && canDownload) {
      actions.push({
        id: 'download-deidentified',
        label: 'Download de-identified',
        icon: <Download className="size-4" aria-hidden="true" />,
        disabled: !file.has_deidentified,
        title: file.has_deidentified
          ? 'The redacted copy that was rejected'
          : 'No redacted copy has been produced',
        isLoading: downloadingId === `${file.id}:true`,
        onSelect: () => void download(file, true),
      })
    }

    const fixes: MenuAction[] = []
    if (can('files:upload')) {
      fixes.push({
        id: 'replace',
        label: 'Replace de-identified copy',
        icon: <Upload className="size-4" aria-hidden="true" />,
        onSelect: () => setReplacing(file),
      })
    }
    if (can('application:update')) {
      fixes.push({
        id: 'approve',
        label: 'Approve',
        icon: <Check className="size-4" aria-hidden="true" />,
        disabled: !file.has_deidentified,
        title: file.has_deidentified
          ? 'Clear the rejection without replacing the copy'
          : 'There is no redacted copy to approve',
        isLoading: review.isPending && review.variables?.fileId === file.id,
        onSelect: () => review.mutate({ fileId: file.id, reviewStatus: 'approved' }),
      })
    }
    if (fixes.length > 0) {
      fixes[0] = { ...fixes[0]!, separatorBefore: actions.length > 0 }
      actions.push(...fixes)
    }

    if (can('files:delete')) {
      actions.push({
        id: 'delete',
        separatorBefore: actions.length > 0,
        label: 'Delete file',
        icon: <Trash2 className="size-4" aria-hidden="true" />,
        tone: 'danger',
        onSelect: () => setDeletingFile(file),
      })
    }
    return actions
  }

  const fileColumns: Array<Column<RejectedFile>> = [
    {
      id: 'name',
      header: 'File',
      cell: (file) => (
        <div className="min-w-0">
          <span className="block truncate font-semibold">{file.original_file_name}</span>
          <span className="block truncate text-xs text-[rgb(var(--foreground-muted))]">
            {file.patient_id} · {formatFileSize(file.file_size)}
          </span>
        </div>
      ),
      sortValue: (file) => file.original_file_name.toLowerCase(),
    },
    {
      id: 'copies',
      header: 'Copies',
      cell: (file) => (
        <div className="flex flex-wrap gap-1">
          <Badge tone={file.has_original ? 'neutral' : 'warning'}>
            {file.has_original ? 'original' : 'no original'}
          </Badge>
          <Badge tone={file.has_deidentified ? 'success' : 'danger'}>
            {file.has_deidentified ? 'de-identified' : 'not redacted'}
          </Badge>
        </div>
      ),
      sortValue: (file) => Number(file.has_original),
    },
    {
      id: 'note',
      header: 'Why it was rejected',
      cell: (file) => (
        <span className="block max-w-sm text-sm text-[rgb(var(--foreground))]">
          {file.review_note || (
            <span className="text-[rgb(var(--foreground-muted))]">
              No reason recorded
            </span>
          )}
        </span>
      ),
      sortValue: (file) => (file.review_note ?? '').toLowerCase(),
    },
    {
      id: 'application',
      header: 'Application',
      cell: (file) => (
        <Link
          to="/applications/$applicationId"
          params={{ applicationId: file.application_id }}
          className="text-sm font-semibold text-[rgb(var(--primary))] hover:underline"
        >
          Open
        </Link>
      ),
    },
  ]

  const applicationColumns: Array<Column<PatientApplication>> = [
    {
      id: 'patient',
      header: 'Patient',
      cell: (application) => (
        <div className="min-w-0">
          <span className="block truncate font-semibold">{application.patient_id}</span>
          <span className="block truncate text-xs text-[rgb(var(--foreground-muted))]">
            {application.description || 'No description'}
          </span>
        </div>
      ),
      sortValue: (application) => application.patient_id,
    },
    {
      id: 'reason',
      header: 'Why it was rejected',
      cell: (application) => (
        <span className="block max-w-sm text-sm">
          {application.status_reason || (
            <span className="text-[rgb(var(--foreground-muted))]">
              No reason recorded
            </span>
          )}
        </span>
      ),
      sortValue: (application) => (application.status_reason ?? '').toLowerCase(),
    },
    {
      id: 'who',
      header: 'Rejected',
      cell: (application) => (
        <span className="text-sm whitespace-nowrap">
          {formatDate(application.reviewed_at ?? application.updated_at)}
          {application.reviewed_by_username && (
            <span className="block text-xs text-[rgb(var(--foreground-muted))]">
              by {application.reviewed_by_username}
            </span>
          )}
        </span>
      ),
      sortValue: (application) => application.reviewed_at ?? application.updated_at ?? '',
    },
  ]

  return (
    <RequirePermission permission="rejection:view">
      <div className="space-y-6">
        <PageHeader
          title="Rejections"
          description="Everything a reviewer turned down, in one place. Check both copies, attach a better redaction and approve it when it looks right."
        />

        <Card className="p-5">
          <h2 className="text-[11px] font-bold tracking-widest text-[rgb(var(--foreground-muted))] uppercase">
            Rejected applications
          </h2>
          <p className="mt-1 mb-4 text-xs text-[rgb(var(--foreground-muted))]">
            A whole submission turned down. Open it to see the documents and the reason.
          </p>

          <DataTable
            data={applicationsQuery.data ?? []}
            columns={applicationColumns}
            getRowId={(application) => application.id}
            isLoading={applicationsQuery.isLoading}
            isFetching={applicationsQuery.isFetching}
            error={applicationsQuery.error}
            loadingLabel="Loading rejected applications"
            emptyMessage="No rejected applications."
            rowActions={(application) => {
              const actions = applicationActions(application)
              return actions.length > 0 ? (
                <DropdownMenu
                  actions={actions}
                  label={`Actions for the application of ${application.patient_id}`}
                />
              ) : null
            }}
          />
        </Card>

        <Card className="p-5">
          <h2 className="text-[11px] font-bold tracking-widest text-[rgb(var(--foreground-muted))] uppercase">
            Rejected documents
          </h2>
          <p className="mt-1 mb-4 text-xs text-[rgb(var(--foreground-muted))]">
            One document whose redaction was not good enough. Its application cannot be
            submitted until this is resolved.
          </p>

          <div className="mb-4">
            <TextField
              label="Search"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
              placeholder="Search by file name, patient id or reason..."
              aria-label="Search rejected documents"
            />
          </div>

          <DataTable
            data={visible}
            columns={fileColumns}
            getRowId={(file) => file.id}
            isLoading={filesQuery.isLoading}
            isFetching={filesQuery.isFetching}
            error={filesQuery.error}
            loadingLabel="Loading rejected documents"
            emptyMessage="Nothing has been rejected."
            rowActions={(file) => {
              const actions = fileActions(file)
              return actions.length > 0 ? (
                <DropdownMenu
                  actions={actions}
                  label={`Actions for ${file.original_file_name}`}
                />
              ) : null
            }}
          />
        </Card>

        {deletingApplication ? (
          <ReasonDialog
            title={`Delete the rejected application for ${deletingApplication.patient_id}?`}
            description={
              'Every document of this application is removed from disk for good: the originals and the de-identified copies. ' +
              "The patient's excluded and failed De-Identifier files are removed too, unless the patient has another application still open. " +
              'The application stays as a record with your reason and can no longer be opened or changed. ' +
              "The patient's other applications are not affected."
            }
            confirmLabel="Delete application"
            placeholder="e.g. patient withdrew consent"
            isBusy={deleteApplication.isPending}
            onCancel={() => setDeletingApplication(null)}
            onConfirm={(reason) => {
              void deleteApplication
                .mutateAsync({ id: deletingApplication.id, reason })
                .then(() => setDeletingApplication(null))
                .catch(() => undefined)
            }}
          />
        ) : null}

        {deletingFile ? (
          <ReasonDialog
            title={`Delete ${deletingFile.original_file_name}?`}
            description={
              'The original and the de-identified copy are removed from disk for good. ' +
              'The file stays listed on its application as a record with your reason, and can no longer be opened. ' +
              'The rest of the application is not affected.'
            }
            confirmLabel="Delete file"
            placeholder="e.g. wrong patient's scan"
            isBusy={purgeFile.isPending}
            onCancel={() => setDeletingFile(null)}
            onConfirm={(reason) => {
              void purgeFile
                .mutateAsync({ fileId: deletingFile.id, reason })
                .then(() => setDeletingFile(null))
                .catch(() => undefined)
            }}
          />
        ) : null}

        {replacing && (
          <ReplaceDeidentifiedDialog
            file={replacing}
            onClose={() => setReplacing(null)}
          />
        )}

        {viewing && (
          <FileViewerModal
            file={{
              original_file_name: viewing.file.original_file_name,
              deidentified_file_name: viewing.file.deidentified_file_name ?? null,
              file_extension: viewing.file.file_extension,
              mime_type: MIME_BY_TYPE[viewing.file.file_extension] ?? 'application/pdf',
              file_size: viewing.file.file_size,
              de_identified_file_path: viewing.file.has_deidentified
                ? viewing.file.deidentified_file_name
                : null,
            }}
            fileId={viewing.file.id}
            blobUrl={viewing.url}
            isDeidentified={viewing.isDeidentified}
            canViewOriginal={viewing.file.has_original && canSeeOriginal}
            onClose={closeViewer}
          />
        )}
      </div>
    </RequirePermission>
  )
}
