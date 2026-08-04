import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { createCrudHooks, errorMessage } from './createCrudHooks'
import {
  customerFilesApi,
  customersApi,
  logsApi,
  rolesApi,
  usersApi,
} from '@/lib/api/resources'
import { queryKeys } from '@/lib/queryKeys'
import type { AuditLogFilters } from '@/schemas/log'
import type { CustomerFormValues } from '@/schemas/customer'
import type { RoleFormValues } from '@/schemas/role'
import type { UserFormValues } from '@/schemas/user'
import type { Customer, Role, User } from '@/lib/api/resources'

/**
 * Writes to users and customers produce audit rows in the background, so
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

export const customerHooks = createCrudHooks<Customer, CustomerFormValues>({
  api: customersApi,
  keys: queryKeys.customers,
  label: 'Customer',
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
 * Customer documents. Not built on createCrudHooks: uploads are
 * multipart and produce many records from one request, which does not
 * fit the single-entity create/update shape.
 */
export function useCustomerFiles(customerId: string | undefined, enabled = true) {
  return useQuery({
    queryKey: queryKeys.customerFiles.list(customerId ?? ''),
    queryFn: () => customerFilesApi.list(customerId as string),
    enabled: Boolean(customerId) && enabled,
  })
}

export function useUploadCustomerFiles(customerId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ files, description }: { files: File[]; description?: string }) =>
      customerFilesApi.upload(customerId, files, description),
    onSuccess: (created) => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.customerFiles.list(customerId),
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
 * Upload where the customer id is only known at call time.
 *
 * The customer form needs this: on create there is no id until the record
 * has been saved, so the files are staged in the form and sent once the
 * customer exists.
 */
export function useUploadFilesForCustomer() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({
      customerId,
      files,
      description,
    }: {
      customerId: string
      files: File[]
      description?: string
    }) => customerFilesApi.upload(customerId, files, description),
    onSuccess: (created, variables) => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.customerFiles.list(variables.customerId),
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
export function useDeidentifyFile(customerId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (fileId: string) => customerFilesApi.deidentify(fileId),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.customerFiles.list(customerId),
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

export function useDeleteCustomerFile(customerId: string) {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (fileId: string) => customerFilesApi.remove(fileId),
    onSuccess: () => {
      void queryClient.invalidateQueries({
        queryKey: queryKeys.customerFiles.list(customerId),
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
