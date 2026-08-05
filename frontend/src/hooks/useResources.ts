import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { createCrudHooks, errorMessage } from './createCrudHooks'
import {
  patientFilesApi,
  patientsApi,
  logsApi,
  rolesApi,
  usersApi,
} from '@/lib/api/resources'
import { queryKeys } from '@/lib/queryKeys'
import type { AuditLogFilters } from '@/schemas/log'
import type { PatientFormValues } from '@/schemas/patient'
import type { RoleFormValues } from '@/schemas/role'
import type { UserFormValues } from '@/schemas/user'
import type { Patient, Role, User } from '@/lib/api/resources'

/**
 * Writes to users and patients produce audit rows in the background, so
 * those mutations also invalidate the logs cache -- otherwise the audit
 * page would keep showing a stale list after a change made elsewhere in
 * the app.
 */
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

/**
 * Changing a role changes what users are allowed to do, and user reads
 * embed role_name/permissions from a join -- so role writes invalidate
 * users and the current user's own permissions too.
 */
export const roleHooks = createCrudHooks<Role, RoleFormValues>({
  api: rolesApi,
  keys: queryKeys.roles,
  label: 'Role',
  alsoInvalidate: [queryKeys.users.all, queryKeys.me],
})

/**
 * Patient documents. Not built on createCrudHooks: uploads are
 * multipart and produce many records from one request, which does not
 * fit the single-entity create/update shape.
 */
export function usePatientFiles(patientId: string | undefined, enabled = true) {
  return useQuery({
    queryKey: queryKeys.patientFiles.list(patientId ?? ''),
    queryFn: () => patientFilesApi.list(patientId as string),
    enabled: Boolean(patientId) && enabled,
  })
}

export function useUploadPatientFiles(patientId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ files, description }: { files: File[]; description?: string }) =>
      patientFilesApi.upload(patientId, files, description),
    onSuccess: (created) => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.patientFiles.list(patientId),
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
 * Upload where the patient id is only known at call time.
 *
 * The patient form needs this: on create there is no id until the record
 * has been saved, so the files are staged in the form and sent once the
 * patient exists.
 */
export function useUploadFilesForPatient() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({
      patientId,
      files,
      description,
    }: {
      patientId: string
      files: File[]
      description?: string
    }) => patientFilesApi.upload(patientId, files, description),
    onSuccess: (created, variables) => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.patientFiles.list(variables.patientId),
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
 * Queues de-identification. The result lands on the row asynchronously,
 * so the list is invalidated to pick up 'processing' immediately; the
 * finished state appears on the next refresh.
 */
export function useDeidentifyFile(patientId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (fileId: string) => patientFilesApi.deidentify(fileId),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.patientFiles.list(patientId),
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

export function useDeletePatientFile(patientId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (fileId: string) => patientFilesApi.remove(fileId),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.patientFiles.list(patientId),
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
