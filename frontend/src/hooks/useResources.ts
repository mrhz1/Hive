import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'
import { createCrudHooks, errorMessage } from './createCrudHooks'
import {
  accessLogsApi,
  applicationsApi,
  applicationFilesApi,
  deidentifiedFilesApi,
  fileMetadataApi,
  patientsApi,
  logsApi,
  rolesApi,
  usersApi,
  type ApplicationPayload,
} from '@/lib/api/resources'
import {
  DEID_LIST_REFRESH_MS,
  DEID_PROGRESS_POLL_MS,
  progressPollingEnabled,
} from '@/lib/deidProgress'
import { queryKeys } from '@/lib/queryKeys'
import type { AccessLogFilters } from '@/schemas/accessLog'
import type { AuditLogFilters } from '@/schemas/log'
import type { FileMetadataFilters } from '@/schemas/fileMetadata'
import {
  bulkSummary,
  isDeidInFlight,
  isUploadJobSettled,
  uploadJobSummary,
  type BulkResult,
  type DeidProgress,
  type UploadJob,
} from '@/schemas/applicationFile'
import type { ApplicationFile } from '@/schemas/applicationFile'
import type { PatientFormValues } from '@/schemas/patient'
import type { RoleFormValues } from '@/schemas/role'
import type { UserFormValues } from '@/schemas/user'
import type { Patient, Role, User } from '@/lib/api/resources'

export const userHooks = createCrudHooks<User, UserFormValues>({
  api: usersApi,
  keys: queryKeys.users,
  label: 'User',
  alsoInvalidate: [queryKeys.logs.all],
})

export const patientHooks = createCrudHooks<Patient, PatientFormValues>({
  api: patientsApi,
  keys: queryKeys.patients,
  label: 'Patient',
  alsoInvalidate: [queryKeys.logs.all],
})

export const roleHooks = createCrudHooks<Role, RoleFormValues>({
  api: rolesApi,
  keys: queryKeys.roles,
  label: 'Role',
  alsoInvalidate: [queryKeys.users.all, queryKeys.me],
})

export function useApplications(patientId?: string, enabled = true) {
  return useQuery({
    queryKey: queryKeys.applications.list(patientId),
    queryFn: () => applicationsApi.list(patientId),
    enabled,
  })
}

export function useApplication(id: string | undefined, enabled = true) {
  return useQuery({
    queryKey: queryKeys.applications.detail(id ?? ''),
    queryFn: () => applicationsApi.get(id as string),
    enabled: Boolean(id) && enabled,
  })
}

export function useCreateApplication() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (values: ApplicationPayload) => applicationsApi.create(values),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.applications.all })
      void queryClient.invalidateQueries({ queryKey: queryKeys.logs.all })
    },
    onError: (error) => {
      toast.error(errorMessage(error, 'Could not create the application'))
    },
  })
}

export function useUpdateApplication() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, values }: { id: string; values: ApplicationPayload }) =>
      applicationsApi.update(id, values),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.applications.all })
      void queryClient.invalidateQueries({ queryKey: queryKeys.logs.all })
    },
    onError: (error) => {
      toast.error(errorMessage(error, 'Could not update the application'))
    },
  })
}

export function useDeleteApplication() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (variables: { id: string; reason: string }) =>
      applicationsApi.remove(variables.id, variables.reason),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.applications.all })
      void queryClient.invalidateQueries({ queryKey: queryKeys.applicationFiles.all })
      void queryClient.invalidateQueries({ queryKey: queryKeys.logs.all })
      toast.success('Documents removed; the application is marked deleted')
    },
    onError: (error) => {
      toast.error(errorMessage(error, 'Could not delete the application'))
    },
  })
}

export function useRejectApplication() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (variables: { id: string; reason: string }) =>
      applicationsApi.reject(variables.id, variables.reason),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.applications.all })
      void queryClient.invalidateQueries({ queryKey: queryKeys.logs.all })
      toast.success('Application rejected')
    },
    onError: (error) => {
      toast.error(errorMessage(error, 'Could not reject the application'))
    },
  })
}

export function useReviewApplicationFile(applicationId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (variables: {
      fileId: string
      reviewStatus: 'approved' | 'rejected'
      note?: string
    }) =>
      applicationFilesApi.review(
        variables.fileId,
        variables.reviewStatus,
        variables.note
      ),
    onSuccess: (_data, variables) => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.applicationFiles.list(applicationId),
      })
      toast.success(
        variables.reviewStatus === 'approved' ? 'File approved' : 'File rejected'
      )
    },
    onError: (error) => {
      toast.error(errorMessage(error, 'Could not record the review'))
    },
  })
}

export function useApplicationFiles(
  applicationId: string | undefined,
  enabled = true
) {
  return useQuery({
    queryKey: queryKeys.applicationFiles.list(applicationId ?? ''),
    queryFn: () => applicationFilesApi.list(applicationId as string),
    enabled: Boolean(applicationId) && enabled,
    // While something is de-identifying, the row's own status has to
    // catch up on its own -- otherwise a finished file sits at
    // 'processing' until the page is reloaded by hand. Configurable
    // because it is a Hive query; VITE_DEID_LIST_REFRESH_MS=0 turns it
    // back into a manual refresh.
    refetchInterval: (query) =>
      DEID_LIST_REFRESH_MS !== false &&
      (query.state.data ?? []).some((file) => isDeidInFlight(file.deid_status))
        ? DEID_LIST_REFRESH_MS
        : false,
  })
}

export function useUploadApplicationFiles(applicationId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ files, description }: { files: File[]; description?: string }) =>
      applicationFilesApi.upload(applicationId, files, description),
    onSuccess: (created) => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.applicationFiles.list(applicationId),
      })
      toast.success(
        created.length === 1 ? '1 file uploaded' : `${created.length} files uploaded`
      )
    },
    onError: (error) => {
      toast.error(errorMessage(error, 'Could not upload files'))
    },
  })
}

/** How often to ask the API how a running batch is getting on. */
const UPLOAD_POLL_MS = 1500

/**
 * Hand a batch of files to the API and watch it from a distance.
 *
 * The upload itself returns as soon as the bytes are staged; the moving,
 * recording and metadata extraction happen after, and this polls the job
 * until they are over. The assigned user gets an email either way -- the
 * toasts here are for whoever is still sitting in front of the wizard.
 */
export function useBackgroundUpload(
  applicationId: string,
  onFinished?: (job: UploadJob) => void
) {
  const queryClient = useQueryClient()
  const [jobId, setJobId] = useState<string | null>(null)
  // Terminal state arrives on a poll, which can repeat; announce it once.
  const announced = useRef<string | null>(null)

  const start = useMutation({
    mutationFn: ({ files, description }: { files: File[]; description?: string }) =>
      applicationFilesApi.uploadInBackground(applicationId, files, description),
    onSuccess: (job) => {
      announced.current = null
      queryClient.setQueryData(queryKeys.applicationFiles.uploadJob(job.id), job)
      setJobId(job.id)
      toast.info(
        job.total === 1
          ? 'Upload started -- moving 1 file'
          : `Upload started -- moving ${job.total} files`,
        { description: 'You can carry on; an email goes out when it is done.' }
      )
    },
    onError: (error) => {
      toast.error(errorMessage(error, 'Could not upload files'))
    },
  })

  const job = useQuery({
    queryKey: queryKeys.applicationFiles.uploadJob(jobId ?? ''),
    queryFn: () => applicationFilesApi.uploadJob(jobId as string),
    enabled: Boolean(jobId),
    // Stop the moment the batch is settled, rather than polling forever.
    refetchInterval: (query) =>
      isUploadJobSettled(query.state.data) ? false : UPLOAD_POLL_MS,
    staleTime: 0,
    retry: false,
  })

  const finished = job.data
  useEffect(() => {
    if (!finished || !isUploadJobSettled(finished)) return
    if (announced.current === finished.id) return
    announced.current = finished.id

    void queryClient.invalidateQueries({
      queryKey: queryKeys.applicationFiles.list(applicationId),
    })

    const summary = uploadJobSummary(finished)
    if (finished.status === 'done') {
      toast.success('Upload finished', { description: summary })
    } else if (finished.status === 'partial') {
      toast.warning('Upload finished with errors', { description: summary })
    } else {
      toast.error('Upload failed', { description: summary })
    }

    onFinished?.(finished)
  }, [finished, applicationId, queryClient, onFinished])

  const isRunning = Boolean(jobId) && !isUploadJobSettled(job.data)

  const dismiss = useCallback(() => setJobId(null), [])

  return {
    start: start.mutateAsync,
    /** True from the click until the batch has settled. */
    isUploading: start.isPending || isRunning,
    /** True only while the bytes are still going up. */
    isSending: start.isPending,
    job: job.data,
    dismiss,
  }
}

export function useUploadFilesForApplication() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({
      applicationId,
      files,
      description,
    }: {
      applicationId: string
      files: File[]
      description?: string
    }) => applicationFilesApi.upload(applicationId, files, description),
    onSuccess: (created, variables) => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.applicationFiles.list(variables.applicationId),
      })
      toast.success(
        created.length === 1 ? '1 file uploaded' : `${created.length} files uploaded`
      )
    },
    onError: (error) => {
      toast.error(errorMessage(error, 'Could not upload files'))
    },
  })
}

/**
 * Live per-page progress for the files currently being de-identified.
 *
 * Polls only while at least one file on the application is actually
 * running: a table of finished documents makes no requests at all. The
 * caller passes the statuses it already has rather than this fetching
 * them again.
 *
 * Off entirely when VITE_DEID_PROGRESS_ENABLED is false, in which case
 * the badge falls back to the plain status and nothing is requested.
 */
export function useDeidProgress(applicationId: string, statuses: string[]) {
  const polling = progressPollingEnabled() && statuses.some(isDeidInFlight)

  const query = useQuery({
    queryKey: queryKeys.applicationFiles.deidProgress(applicationId),
    queryFn: () => applicationFilesApi.deidProgress(applicationId),
    enabled: Boolean(applicationId) && polling,
    refetchInterval: polling ? DEID_PROGRESS_POLL_MS : false,
    staleTime: 0,
    // A progress read is decoration; failing it must not surface an error
    // over a run that is otherwise fine.
    retry: false,
  })

  const byFile = new Map<string, DeidProgress>()
  for (const item of query.data?.items ?? []) byFile.set(item.file_id, item)
  return byFile
}

export function useDeidentifyFile(applicationId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (fileId: string) => applicationFilesApi.deidentify(fileId),
    onSuccess: (file) => {
      queryClient.setQueryData<ApplicationFile[]>(
        queryKeys.applicationFiles.list(applicationId),
        (current) => current?.map((f) => (f.id === file.id ? file : f))
      )
      void queryClient.invalidateQueries({
        queryKey: queryKeys.applicationFiles.list(applicationId),
      })
      toast.success('De-identification started', {
        // No longer "refresh in a moment": the row reports its own page
        // count as it goes and flips to done by itself. A large document
        // is tens of minutes, so saying so sets the expectation.
        description: 'The row shows its progress; a long document can take a while.',
      })
    },
    onError: (error) => {
      toast.error(errorMessage(error, 'Could not start de-identification'))
    },
  })
}

/** De-identify, or approve, every file on the application at once. */
function useBulkFileAction(
  applicationId: string,
  action: (id: string) => Promise<BulkResult>,
  verb: 'approve' | 'de-identify',
  failure: string
) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => action(applicationId),
    onSuccess: (result) => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.applicationFiles.list(applicationId),
      })
      const description = bulkSummary(result, verb)
      if (result.changed === 0) {
        toast.info(description)
      } else {
        toast.success(
          verb === 'approve' ? 'Documents approved' : 'De-identification started',
          { description }
        )
      }
    },
    onError: (error) => {
      toast.error(errorMessage(error, failure))
    },
  })
}

export function useDeidentifyAllFiles(applicationId: string) {
  return useBulkFileAction(
    applicationId,
    applicationFilesApi.deidentifyAll,
    'de-identify',
    'Could not start de-identification'
  )
}

export function useApproveAllFiles(applicationId: string) {
  return useBulkFileAction(
    applicationId,
    applicationFilesApi.approveAll,
    'approve',
    'Could not approve the documents'
  )
}

export function useFileMetadata(
  fileId: string | undefined,
  deidentified = false
) {
  return useQuery({
    queryKey: queryKeys.applicationFiles.metadata(fileId ?? '', deidentified),
    queryFn: () => applicationFilesApi.metadata(fileId as string, deidentified),
    enabled: Boolean(fileId),
    staleTime: Infinity,
    retry: false,
  })
}

/**
 * Attach a document that is already redacted.
 *
 * Nothing to de-identify and nothing to review against: it lands done,
 * named as the pipeline would have named its own output.
 */
export function useUploadDeidentifiedApplicationFile(applicationId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ file, description }: { file: File; description?: string }) =>
      applicationFilesApi.uploadDeidentified(applicationId, file, description),
    onSuccess: (created) => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.applicationFiles.list(applicationId),
      })
      void queryClient.invalidateQueries({
        queryKey: queryKeys.deidentifiedFiles.all,
      })
      toast.success('De-identified file attached', {
        description: `Stored as ${created.deidentified_file_name}`,
      })
    },
    onError: (error) => {
      toast.error(errorMessage(error, 'Could not attach the file'))
    },
  })
}

export function useDeleteApplicationFile(applicationId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (fileId: string) => applicationFilesApi.remove(fileId),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.applicationFiles.list(applicationId),
      })
      toast.success('File deleted')
    },
    onError: (error) => {
      toast.error(errorMessage(error, 'Could not delete file'))
    },
  })
}

/** Extracted metadata across every document, filtered by the API. */
export function useFileMetadataRows(
  filters: FileMetadataFilters = {},
  enabled = true
) {
  return useQuery({
    queryKey: queryKeys.fileMetadata.list(filters),
    queryFn: () => fileMetadataApi.list(filters),
    enabled,
    // The search box drives this key; keep the previous rows on screen
    // while the next term is fetched rather than blanking the table.
    placeholderData: (previous) => previous,
  })
}

export function useExportFileMetadata() {
  return useMutation({
    mutationFn: (filters: FileMetadataFilters) => fileMetadataApi.export(filters),
    onSuccess: (blob) => {
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `file-metadata-${new Date().toISOString().slice(0, 10)}.xlsx`
      document.body.appendChild(link)
      link.click()
      link.remove()
      URL.revokeObjectURL(url)
      toast.success('Metadata exported')
    },
    onError: (error) => {
      toast.error(errorMessage(error, 'Could not export the metadata'))
    },
  })
}

/** Audit logs are append-only; no create/update/delete hooks needed. */
export function useAuditLogs(filters: AuditLogFilters = {}, enabled = true) {
  return useQuery({
    queryKey: queryKeys.logs.list(filters),
    queryFn: () => logsApi.list(filters),
    enabled,
  })
}

/** Who saw what. Bound the dates: they select Hive partitions. */
export function useAccessLogs(filters: AccessLogFilters = {}, enabled = true) {
  return useQuery({
    queryKey: queryKeys.accessLogs.list(filters),
    queryFn: () => accessLogsApi.list(filters),
    enabled,
    placeholderData: (previous) => previous,
  })
}

export function useAuditLog(id: string | undefined, enabled = true) {
  return useQuery({
    queryKey: queryKeys.logs.detail(id ?? ''),
    queryFn: () => logsApi.get(id as string),
    enabled: Boolean(id) && enabled,
  })
}

export function useDeidentifiedFiles(patientId?: string, enabled = true) {
  return useQuery({
    queryKey: queryKeys.deidentifiedFiles.list(patientId),
    queryFn: () => deidentifiedFilesApi.list(patientId),
    enabled,
  })
}

function useLibraryInvalidation() {
  const queryClient = useQueryClient()
  return () => {
    void queryClient.invalidateQueries({
      queryKey: queryKeys.deidentifiedFiles.all,
    })
    void queryClient.invalidateQueries({
      queryKey: queryKeys.applicationFiles.all,
    })
  }
}

export function useUploadDeidentifiedFile() {
  const invalidate = useLibraryInvalidation()
  return useMutation({
    mutationFn: (variables: {
      patientId: string
      file: File
      replacesFileId?: string
    }) =>
      deidentifiedFilesApi.upload(
        variables.patientId,
        variables.file,
        variables.replacesFileId
      ),
    onSuccess: (_data, variables) => {
      invalidate()
      toast.success(
        variables.replacesFileId
          ? 'De-identified file replaced'
          : 'De-identified file uploaded'
      )
    },
    onError: (error) => {
      toast.error(errorMessage(error, 'Could not upload the file'))
    },
  })
}

export function useDeleteDeidentifiedFile() {
  const invalidate = useLibraryInvalidation()
  return useMutation({
    mutationFn: (fileId: string) => deidentifiedFilesApi.remove(fileId),
    onSuccess: () => {
      invalidate()
      toast.success('De-identified copy deleted')
    },
    onError: (error) => {
      toast.error(errorMessage(error, 'Could not delete the file'))
    },
  })
}
