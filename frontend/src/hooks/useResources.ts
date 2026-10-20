import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useRef, useState } from 'react'
import { toast } from 'sonner'
import { createCrudHooks, errorMessage } from './createCrudHooks'
import {
  securityApi,
  abstractionApi,
  accessLogsApi,
  applicationsApi,
  applicationFilesApi,
  intakeApi,
  deidentifiedFilesApi,
  fileMetadataApi,
  patientsApi,
  logsApi,
  consentsApi,
  projectsApi,
  rolesApi,
  usersApi,
  zone2Api,
  type ApplicationPayload,
} from '@/lib/api/resources'
import { queryKeys } from '@/lib/queryKeys'
import type { AccessLogFilters } from '@/schemas/accessLog'
import type { AuditLogFilters } from '@/schemas/log'
import type { ProblemList } from '@/schemas/intake'
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
import type { CohortCriteria, ConsentPayload, ProjectPayload } from '@/schemas/project'
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

export function useConfirmPatientDetails() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => patientsApi.confirmDetails(id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.patients.all })
      void queryClient.invalidateQueries({ queryKey: queryKeys.logs.all })
      toast.success('Patient details confirmed')
    },
    onError: (error) => {
      toast.error(errorMessage(error, 'Could not confirm the details'))
    },
  })
}

export function usePatientImport() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (variables: { file: File; apply: boolean }) =>
      patientsApi.importFile(variables.file, variables.apply),
    onSuccess: (result) => {
      if (!result.applied) return
      void queryClient.invalidateQueries({ queryKey: queryKeys.patients.all })
      void queryClient.invalidateQueries({ queryKey: queryKeys.logs.all })
      toast.success(
        `Imported: ${result.counts.create ?? 0} new, ${result.counts.update ?? 0} updated`
      )
    },
    onError: (error) => {
      toast.error(errorMessage(error, 'Could not read the file'))
    },
  })
}

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
    onSuccess: (summary) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.applications.all })
      void queryClient.invalidateQueries({ queryKey: queryKeys.applicationFiles.all })
      void queryClient.invalidateQueries({ queryKey: queryKeys.intake.all })
      void queryClient.invalidateQueries({ queryKey: queryKeys.logs.all })
      const parts = [
        `${summary.files_deleted} document${summary.files_deleted === 1 ? '' : 's'} deleted`,
      ]
      if (summary.excluded_deleted || summary.failed_deleted)
        parts.push(
          `${summary.excluded_deleted} excluded and ${summary.failed_deleted} failed De-Identifier files removed`
        )
      if (summary.excluded_and_failed_kept)
        parts.push(
          'excluded and failed files kept: the patient has another open application'
        )
      toast.success('Application deleted; the record is kept', {
        description: parts.join(' · '),
      })
    },
    onError: (error) => {
      toast.error(errorMessage(error, 'Could not delete the application'))
    },
  })
}

export function useRejectApplication() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (variables: { id: string; reason: string; failedChecks: string[] }) =>
      applicationsApi.reject(variables.id, variables.reason, variables.failedChecks),
    onSuccess: (application) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.applications.all })
      void queryClient.invalidateQueries({ queryKey: queryKeys.applicationFiles.all })
      void queryClient.invalidateQueries({ queryKey: queryKeys.logs.all })
      toast.success(
        application.status === 'deleted'
          ? 'Application rejected and its documents deleted'
          : 'Application rejected'
      )
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

export function useMarkLeaded(applicationId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (variables: { fileId: string; leaded: boolean }) =>
      applicationFilesApi.markLeaded(variables.fileId, variables.leaded),
    onSuccess: (_data, variables) => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.applicationFiles.list(applicationId),
      })
      toast.success(
        variables.leaded ? 'Marked as leaded; kept out of Zone 2' : 'Leaded mark cleared'
      )
    },
    onError: (error) => {
      toast.error(errorMessage(error, 'Could not change the leaded mark'))
    },
  })
}

export function useSetDocumentInfo(applicationId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (variables: { fileId: string; modality: string; documentDate: string }) =>
      applicationFilesApi.setDocumentInfo(
        variables.fileId,
        variables.modality,
        variables.documentDate
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.applicationFiles.list(applicationId),
      })
      toast.success('File renamed')
    },
    onError: (error) => {
      toast.error(errorMessage(error, 'Could not rename the file'))
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

export function useFileMetadata(fileId: string | undefined, deidentified = false) {
  return useQuery({
    queryKey: queryKeys.applicationFiles.metadata(fileId ?? '', deidentified),
    queryFn: () => applicationFilesApi.metadata(fileId as string, deidentified),
    enabled: Boolean(fileId),
    staleTime: Infinity,
    retry: false,
  })
}

export function usePurgeFile() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (variables: { fileId: string; reason: string }) =>
      applicationFilesApi.purge(variables.fileId, variables.reason),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.applicationFiles.all })
      void queryClient.invalidateQueries({ queryKey: queryKeys.logs.all })
      toast.success('File deleted; the record is kept')
    },
    onError: (error) => {
      toast.error(errorMessage(error, 'Could not delete the file'))
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

export function useIntakeStatus() {
  return useQuery({
    queryKey: queryKeys.intake.status(),
    queryFn: () => intakeApi.status(),
    refetchInterval: (query) =>
      query.state.data?.running || query.state.data?.starting ? 5_000 : 15_000,
  })
}

export function useIntakeRuns() {
  return useQuery({
    queryKey: queryKeys.intake.runs(),
    queryFn: () => intakeApi.runs(),
    refetchInterval: 30_000,
  })
}

export function useIntakeFinished(running: boolean) {
  return useQuery({
    queryKey: queryKeys.intake.finished(),
    queryFn: () => intakeApi.finished(),
    refetchInterval: running ? 5_000 : 30_000,
  })
}

export function useStartIntake() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => intakeApi.start(),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.intake.all })
      toast.success('De-identification requested', {
        description: 'It shows as running here once a worker picks it up.',
      })
    },
    onError: (error) => {
      toast.error(errorMessage(error, 'Could not start de-identification'))
    },
  })
}

export function useStopIntake() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => intakeApi.stop(),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.intake.all })
      toast.success('De-identification stopped', {
        description: 'Files not finished stay in the incoming folder for the next run.',
      })
    },
    onError: (error) => {
      toast.error(errorMessage(error, 'Could not stop de-identification'))
    },
  })
}

export function useCarbonFolder(path: string, enabled: boolean) {
  return useQuery({
    queryKey: queryKeys.intake.carbonFolder(path),
    queryFn: () => intakeApi.carbonBrowse(path),
    enabled,
    retry: false,
    staleTime: 30_000,
  })
}

export function useCarbonStatus(enabled: boolean) {
  return useQuery({
    queryKey: queryKeys.intake.carbonStatus(),
    queryFn: () => intakeApi.carbonStatus(),
    enabled,
    refetchInterval: (query) => (query.state.data?.running ? 2_000 : false),
  })
}

export function useCarbonCheck() {
  return useMutation({
    mutationFn: (paths: string[]) => intakeApi.carbonCheck(paths),
    onError: (error) => {
      toast.error(errorMessage(error, 'Could not check the selected folders'))
    },
  })
}

export function useCarbonCopy() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (paths: string[]) => intakeApi.carbonCopy(paths),
    onSuccess: (state) => {
      queryClient.setQueryData(queryKeys.intake.carbonStatus(), state)
      toast.success('Copy from Carbon started', {
        description: `${state.total.toLocaleString()} files are being copied to incoming.`,
      })
    },
    onError: (error) => {
      toast.error(errorMessage(error, 'Could not start the copy'))
    },
  })
}

export function useIntakeFiles(kind: ProblemList, limit: number, code = '') {
  return useQuery({
    queryKey: queryKeys.intake.files(kind, limit, code),
    queryFn: () => intakeApi.files(kind, limit, code || undefined),
    refetchInterval: 15_000,
  })
}

export function useIntakeFileCodes(kind: ProblemList) {
  return useQuery({
    queryKey: queryKeys.intake.fileCodes(kind),
    queryFn: () => intakeApi.fileCodes(kind),
    refetchInterval: 30_000,
  })
}

export function useRetryAllIntakeFiles() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ kind, code }: { kind: ProblemList; code?: string }) =>
      intakeApi.retryAll(kind, code),
    onSuccess: ({ moved }) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.intake.all })
      toast.success(
        `Moved ${moved} file${moved === 1 ? '' : 's'} back to the incoming folder`,
        { description: 'They will be done in the next run.' }
      )
    },
    onError: (error) => {
      toast.error(errorMessage(error, 'Could not retry the files'))
    },
  })
}

export function useRetryIntakeFile() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ kind, path }: { kind: ProblemList; path: string }) =>
      intakeApi.retry(kind, path),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.intake.all })
      toast.success('Moved back to the incoming folder, it will be done in the next run')
    },
    onError: (error) => {
      toast.error(errorMessage(error, 'Could not retry this file'))
    },
  })
}

export function useResolveIntakeConflict() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (variables: { path: string; code: string }) =>
      intakeApi.resolve(variables.path, variables.code),
    onSuccess: (_data, variables) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.intake.all })
      toast.success(`Will be filed under ${variables.code} in the next run`)
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

export function useCodeFiles(code: string | undefined) {
  return useQuery({
    queryKey: queryKeys.intake.codeFiles(code ?? ''),
    queryFn: () => intakeApi.codeFiles(code ?? ''),
    enabled: Boolean(code),
  })
}

export function useAttachIntakeFiles(applicationId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (fileIds: string[]) => intakeApi.attach(applicationId, fileIds),
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

export function useLockdown() {
  return useQuery({
    queryKey: queryKeys.security.lockdown(),
    queryFn: () => securityApi.lockdown(),
    refetchInterval: 30_000,
  })
}

export function useIncidents(enabled = true) {
  return useQuery({
    queryKey: queryKeys.security.incidents(),
    queryFn: () => securityApi.incidents(),
    enabled,
  })
}

function useSecurityMutation<TVariables, TResult>(
  mutationFn: (variables: TVariables) => Promise<TResult>,
  success: string,
  failure: string
) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn,
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.security.all })
      void queryClient.invalidateQueries({ queryKey: queryKeys.logs.all })
      toast.success(success)
    },
    onError: (error) => {
      toast.error(errorMessage(error, failure))
    },
  })
}

export function useLockApp() {
  return useSecurityMutation(
    (variables: { reason: string; level: 'low' | 'high' | 'critical' }) =>
      securityApi.lock(variables.reason, variables.level),
    'The app is locked',
    'Could not lock the app'
  )
}

export function useUnlockApp() {
  return useSecurityMutation(
    (reason: string) => securityApi.unlock(reason),
    'The app is unlocked',
    'Could not unlock the app'
  )
}

export function useCreateIncident() {
  return useSecurityMutation(
    securityApi.createIncident,
    'Incident recorded',
    'Could not record the incident'
  )
}

export function useUpdateIncident() {
  return useSecurityMutation(
    (variables: {
      id: string
      values: Parameters<typeof securityApi.updateIncident>[1]
    }) => securityApi.updateIncident(variables.id, variables.values),
    'Incident saved',
    'Could not save the incident'
  )
}

export function useMarkReportSent() {
  return useSecurityMutation(
    (variables: { id: string; report: 'preliminary' | 'full' }) =>
      securityApi.markSent(variables.id, variables.report),
    'Marked as sent',
    'Could not mark it as sent'
  )
}

export function useCloseIncident() {
  return useSecurityMutation(
    securityApi.close,
    'Incident closed',
    'Could not close the incident'
  )
}

export function useAbstractionFolders() {
  return useQuery({
    queryKey: queryKeys.abstraction.list(),
    queryFn: () => abstractionApi.list(),
  })
}

export function useAbstractionDocuments(id: string) {
  return useQuery({
    queryKey: queryKeys.abstraction.documents(id),
    queryFn: () => abstractionApi.documents(id),
  })
}

export function useAbstractionPreview() {
  return useMutation({
    mutationFn: abstractionApi.preview,
    onError: (error) => {
      toast.error(errorMessage(error, 'Could not find the documents'))
    },
  })
}

function useAbstractionMutation<TVariables, TResult>(
  mutationFn: (variables: TVariables) => Promise<TResult>,
  success: string | ((result: TResult) => string),
  failure: string
) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn,
    onSuccess: (result) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.abstraction.all })
      void queryClient.invalidateQueries({ queryKey: queryKeys.logs.all })
      toast.success(typeof success === 'string' ? success : success(result))
    },
    onError: (error) => {
      toast.error(errorMessage(error, failure))
    },
  })
}

export function useCreateAbstractionFolder() {
  return useAbstractionMutation(
    abstractionApi.create,
    (folder) => `Folder made with ${folder.file_count} document(s)`,
    'Could not make the folder'
  )
}

export function useExtendAbstractionFolder() {
  return useAbstractionMutation(
    abstractionApi.extend,
    'Folder extended',
    'Could not extend the folder'
  )
}

export function useRegenerateAbstractionFolder() {
  return useAbstractionMutation(
    abstractionApi.regenerate,
    (result) =>
      result.missing
        ? `Folder made again; ${result.missing} document(s) are no longer available`
        : 'Folder made again',
    'Could not make the folder again'
  )
}

export function useDeleteAbstractionFolder() {
  return useAbstractionMutation(
    (variables: { id: string; reason: string }) =>
      abstractionApi.remove(variables.id, variables.reason),
    'Folder deleted',
    'Could not delete the folder'
  )
}

export function useProjects() {
  return useQuery({
    queryKey: queryKeys.projects.list(),
    queryFn: () => projectsApi.list(),
  })
}

export function useProject(id: string) {
  return useQuery({
    queryKey: queryKeys.projects.detail(id),
    queryFn: () => projectsApi.get(id),
  })
}

export function useProjectCandidates(projectId: string, enabled = true) {
  return useQuery({
    queryKey: queryKeys.projects.candidates(projectId),
    queryFn: () => projectsApi.candidates(projectId),
    enabled,
  })
}

export function useCohortSearch(projectId: string) {
  return useMutation({
    mutationFn: (criteria: CohortCriteria) =>
      projectsApi.searchCohort(projectId, criteria),
    onError: (error) => {
      toast.error(errorMessage(error, 'Could not search'))
    },
  })
}

function useProjectMutation<TVariables, TResult>(
  mutationFn: (variables: TVariables) => Promise<TResult>,
  success: string | ((result: TResult) => string),
  failure: string
) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn,
    onSuccess: (result) => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.projects.all })
      void queryClient.invalidateQueries({ queryKey: queryKeys.zone2.all })
      void queryClient.invalidateQueries({ queryKey: queryKeys.logs.all })
      toast.success(typeof success === 'string' ? success : success(result))
    },
    onError: (error) => {
      toast.error(errorMessage(error, failure))
    },
  })
}

export function useCreateProject() {
  return useProjectMutation(
    (values: ProjectPayload) => projectsApi.create(values),
    'Project created',
    'Could not create the project'
  )
}

export function useUpdateProject(id: string) {
  return useProjectMutation(
    (values: ProjectPayload) => projectsApi.update(id, values),
    'Project saved',
    'Could not save the project'
  )
}

export function useSetCohort(id: string) {
  return useProjectMutation(
    (patientIds: string[]) => projectsApi.setCohort(id, patientIds),
    (project) =>
      `${project.cohort.length} patient${project.cohort.length === 1 ? '' : 's'} in the project`,
    'Could not change the patients'
  )
}

export function usePrepareProject(id: string) {
  return useProjectMutation(
    (_: void) => projectsApi.prepare(id),
    (release) =>
      `Safe copy prepared: ${release.patients} patients, ${release.applications} applications, ${release.documents} documents. It is in the Zone 2 inbox for review.`,
    'Could not prepare the safe copy'
  )
}

export function useDeleteProject() {
  return useProjectMutation(
    (id: string) => projectsApi.remove(id),
    'Project deleted',
    'Could not delete the project'
  )
}

export function useZone2Releases(status = 'in_review') {
  return useQuery({
    queryKey: queryKeys.zone2.releases(status),
    queryFn: () => zone2Api.releases(status),
  })
}

export function useZone2Release(id: string | null) {
  return useQuery({
    queryKey: queryKeys.zone2.release(id ?? ''),
    queryFn: () => zone2Api.release(id as string),
    enabled: Boolean(id),
  })
}

export function useApproveRelease() {
  return useProjectMutation(
    (id: string) => zone2Api.approve(id),
    'Released to Zone 2',
    'Could not release'
  )
}

export function useReleaseDocuments(id: string, enabled = true) {
  return useQuery({
    queryKey: queryKeys.zone2.documents(id),
    queryFn: () => zone2Api.documents(id),
    enabled,
  })
}

export function useFlagReleaseDocument() {
  const queryClient = useQueryClient()
  return useProjectMutation(
    (variables: { id: string; documentId: string; reason: string }) =>
      zone2Api
        .flag(variables.id, variables.documentId, variables.reason)
        .then((release) => {
          void queryClient.invalidateQueries({ queryKey: queryKeys.applicationFiles.all })
          return release
        }),
    'Release sent back; the document is in Rejections',
    'Could not flag the document'
  )
}

export function useBuildWorkspace(id: string) {
  return useProjectMutation(
    (includeDocuments: boolean) => projectsApi.buildWorkspace(id, includeDocuments),
    'Workspace built',
    'Could not build the workspace'
  )
}

export function useExtendWorkspace(id: string) {
  return useProjectMutation(
    (reason: string) => projectsApi.extendWorkspace(id, reason),
    (project) =>
      `Workspace kept until ${(project.workspace_expires_at ?? '').slice(0, 10)}`,
    'Could not extend the workspace'
  )
}

export function useDeleteWorkspace(id: string) {
  return useProjectMutation(
    (reason: string) => projectsApi.deleteWorkspace(id, reason),
    'Workspace deleted',
    'Could not delete the workspace'
  )
}

export function useConsents(patientId?: string) {
  return useQuery({
    queryKey: queryKeys.consents.list(patientId),
    queryFn: () => consentsApi.list(patientId),
  })
}

export function useRecordConsent() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (values: ConsentPayload) => consentsApi.record(values),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.consents.all })
      void queryClient.invalidateQueries({ queryKey: queryKeys.projects.all })
      toast.success('Consent recorded')
    },
    onError: (error) => {
      toast.error(errorMessage(error, 'Could not record the consent'))
    },
  })
}

export function useEndProject(id: string) {
  return useProjectMutation(
    (reason: string) => projectsApi.end(id, reason),
    'Project ended',
    'Could not end the project'
  )
}

export function useRejectRelease() {
  return useProjectMutation(
    (variables: { id: string; reason: string }) =>
      zone2Api.reject(variables.id, variables.reason),
    'Sent back for changes',
    'Could not reject the release'
  )
}

export function useUserDirectory(enabled = true) {
  return useQuery({
    queryKey: queryKeys.users.directory(),
    queryFn: () => usersApi.directory(),
    enabled,
    staleTime: 60_000,
  })
}

export function useMyOriginalGrants(enabled = true) {
  return useQuery({
    queryKey: queryKeys.applicationFiles.myGrants(),
    queryFn: () => applicationFilesApi.myOriginalGrants(),
    enabled,
  })
}

export function useOriginalGrants(fileId: string) {
  return useQuery({
    queryKey: queryKeys.applicationFiles.grants(fileId),
    queryFn: () => applicationFilesApi.originalGrants(fileId),
  })
}

function useOriginalGrantMutation<TVariables, TResult>(
  fileId: string,
  mutationFn: (variables: TVariables) => Promise<TResult>,
  success: string,
  failure: string
) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn,
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.applicationFiles.grants(fileId),
      })
      void queryClient.invalidateQueries({
        queryKey: queryKeys.applicationFiles.myGrants(),
      })
      void queryClient.invalidateQueries({ queryKey: queryKeys.logs.all })
      toast.success(success)
    },
    onError: (error) => {
      toast.error(errorMessage(error, failure))
    },
  })
}

export function useGrantOriginal(fileId: string) {
  return useOriginalGrantMutation(
    fileId,
    (variables: { userId: string; reason: string }) =>
      applicationFilesApi.grantOriginal(fileId, variables.userId, variables.reason),
    'Access to the original granted',
    'Could not grant access'
  )
}

export function useRevokeOriginal(fileId: string) {
  return useOriginalGrantMutation(
    fileId,
    (grantId: string) => applicationFilesApi.revokeOriginal(fileId, grantId),
    'Access taken back',
    'Could not take the access back'
  )
}

export function useAddProjectMember(id: string) {
  return useProjectMutation(
    (userId: string) => projectsApi.addMember(id, userId),
    'Member added',
    'Could not add the member'
  )
}

export function useRemoveProjectMember(id: string) {
  return useProjectMutation(
    (userId: string) => projectsApi.removeMember(id, userId),
    'Member removed',
    'Could not remove the member'
  )
}
