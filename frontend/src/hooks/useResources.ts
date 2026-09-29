import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'
import { createCrudHooks, errorMessage } from './createCrudHooks'
import {
  accessLogsApi,
  applicationsApi,
  applicationFilesApi,
  intakeApi,
  deidentifiedFilesApi,
  fileMetadataApi,
  patientsApi,
  logsApi,
  rolesApi,
  usersApi,
  type ApplicationPayload,
} from '@/lib/api/resources'
import { queryKeys } from '@/lib/queryKeys'
import type { AccessLogFilters } from '@/schemas/accessLog'
import type { AuditLogFilters } from '@/schemas/log'
import type { FileMetadataFilters } from '@/schemas/fileMetadata'
import {
  bulkSummary,
  isUploadJobSettled,
  uploadJobSummary,
  type BulkResult,
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

export function useApplications(patientId?: string, enabled = true, status?: string) {
  return useQuery({
    queryKey: queryKeys.applications.list(patientId, status),
    queryFn: () => applicationsApi.list(patientId, status),
    enabled,
  })
}

export function useRejectedFiles(enabled = true) {
  return useQuery({
    queryKey: queryKeys.applicationFiles.rejected(),
    queryFn: () => applicationFilesApi.listRejected(),
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

export function useReviewRejectedFile() {
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
        queryKey: queryKeys.applicationFiles.all,
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

export function useApplicationFiles(applicationId: string | undefined, enabled = true) {
  return useQuery({
    queryKey: queryKeys.applicationFiles.list(applicationId ?? ''),
    queryFn: () => applicationFilesApi.list(applicationId as string),
    enabled: Boolean(applicationId) && enabled,
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

const UPLOAD_POLL_MS = 1500

export function useBackgroundUpload(
  applicationId: string,
  onFinished?: (job: UploadJob) => void
) {
  const queryClient = useQueryClient()
  const [jobId, setJobId] = useState<string | null>(null)

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
          ? 'Upload started, moving 1 file'
          : `Upload started, moving ${job.total} files`,
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

    isUploading: start.isPending || isRunning,

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
        description: 'Refresh in a moment to see the redacted copy.',
      })
    },
    onError: (error) => {
      toast.error(errorMessage(error, 'Could not start de-identification'))
    },
  })
}

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

export function useFileMetadata(fileId: string | undefined, deidentified = false) {
  return useQuery({
    queryKey: queryKeys.applicationFiles.metadata(fileId ?? '', deidentified),
    queryFn: () => applicationFilesApi.metadata(fileId as string, deidentified),
    enabled: Boolean(fileId),
    staleTime: Infinity,
    retry: false,
  })
}

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

export function useFileMetadataRows(filters: FileMetadataFilters = {}, enabled = true) {
  return useQuery({
    queryKey: queryKeys.fileMetadata.list(filters),
    queryFn: () => fileMetadataApi.list(filters),
    enabled,

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

export function useAuditLogs(filters: AuditLogFilters = {}, enabled = true) {
  return useQuery({
    queryKey: queryKeys.logs.list(filters),
    queryFn: () => logsApi.list(filters),
    enabled,
  })
}

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
    mutationFn: (variables: { patientId: string; file: File; replacesFileId?: string }) =>
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

export function useIntakeCounts() {
  return useQuery({
    queryKey: queryKeys.intake.counts(),
    queryFn: () => intakeApi.counts(),
    refetchInterval: 15_000,
  })
}

export function useResolveIntakeConflict() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (variables: { fileId: string; code: string }) =>
      intakeApi.resolve(variables.fileId, variables.code),
    onSuccess: (_data, variables) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.intake.all })
      toast.success(`Filed under ${variables.code} and queued`)
    },
    onError: (error) => {
      toast.error(errorMessage(error, 'Could not resolve the conflict'))
    },
  })
}

export function useIntakeCodes(enabled = true) {
  return useQuery({
    queryKey: queryKeys.intake.codes(),
    queryFn: () => intakeApi.codes(),
    enabled,
  })
}

export function useAvailableIntakeFiles(patientCode: string | undefined) {
  return useQuery({
    queryKey: queryKeys.intake.files('done', patientCode),
    queryFn: () => intakeApi.files('done', patientCode),
    enabled: Boolean(patientCode),
  })
}

export function useAttachIntakeFiles(applicationId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (intakeFileIds: string[]) =>
      intakeApi.attach(applicationId, intakeFileIds),
    onSuccess: (attached) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.intake.all })
      void queryClient.invalidateQueries({
        queryKey: queryKeys.applicationFiles.all,
      })
      toast.success(
        `Attached ${attached.length} document${attached.length === 1 ? '' : 's'}`
      )
    },
    onError: (error) => {
      toast.error(errorMessage(error, 'Could not attach those files'))
    },
  })
}

export function useRetryIntakeFile() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (fileId: string) => intakeApi.retry(fileId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.intake.all })
      toast.success('Queued again, the next run will pick it up')
    },
    onError: (error) => {
      toast.error(errorMessage(error, 'Could not retry this file'))
    },
  })
}

export function useIntakeProgress() {
  return useQuery({
    queryKey: queryKeys.intake.progress(),
    queryFn: () => intakeApi.progress(),
    refetchInterval: 10_000,
  })
}

export function useIntakeBatchProgress() {
  return useQuery({
    queryKey: queryKeys.intake.batchProgress(),
    queryFn: () => intakeApi.batchProgress(),
    refetchInterval: 30_000,
  })
}

export function useIntakePage(status: string, limit: number) {
  return useQuery({
    queryKey: queryKeys.intake.page(status, limit),
    queryFn: () => intakeApi.page(status, limit, 0),
    refetchInterval: 15_000,
  })
}
