import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { createCrudHooks, errorMessage } from './createCrudHooks'
import {
  applicationsApi,
  applicationFilesApi,
  patientsApi,
  logsApi,
  rolesApi,
  usersApi,
  type ApplicationPayload,
} from '@/lib/api/resources'
import { queryKeys } from '@/lib/queryKeys'
import type { AuditLogFilters } from '@/schemas/log'
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
    mutationFn: (id: string) => applicationsApi.remove(id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: queryKeys.applications.all })
      void queryClient.invalidateQueries({ queryKey: queryKeys.logs.all })
      toast.success('Application deleted')
    },
    onError: (error) => {
      toast.error(errorMessage(error, 'Could not delete the application'))
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

export function useFileMetadata(fileId: string | undefined) {
  return useQuery({
    queryKey: queryKeys.applicationFiles.metadata(fileId ?? ''),
    queryFn: () => applicationFilesApi.metadata(fileId as string),
    enabled: Boolean(fileId),
    staleTime: Infinity,
    retry: false,
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

/** Audit logs are append-only; no create/update/delete hooks needed. */
export function useAuditLogs(filters: AuditLogFilters = {}, enabled = true) {
  return useQuery({
    queryKey: queryKeys.logs.list(filters),
    queryFn: () => logsApi.list(filters),
    enabled,
  })
}

export function useAuditLog(id: string | undefined, enabled = true) {
  return useQuery({
    queryKey: queryKeys.logs.detail(id ?? ''),
    queryFn: () => logsApi.get(id as string),
    enabled: Boolean(id) && enabled,
  })
}
