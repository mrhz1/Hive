import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import { errorMessage } from './createCrudHooks'
import { meApi } from '@/lib/api/resources'
import { queryKeys } from '@/lib/queryKeys'
import type { Permission } from '@/schemas/common'
import type { ProfileFormValues } from '@/schemas/user'

/**
 * The app has no login. It asks the API who the caller is and renders
 * from the permissions that come back, so this query gates the entire
 * shell -- nothing else renders until it resolves.
 *
 * staleTime is long because identity rarely changes mid-session; role
 * edits explicitly invalidate this key (see useResources.ts).
 */
export function useCurrentUser() {
  return useQuery({
    queryKey: queryKeys.me,
    queryFn: meApi.get,
    staleTime: 5 * 60_000,
    retry: false,
  })
}

export function useUpdateProfile() {
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (values: ProfileFormValues) => meApi.update(values),
    onSuccess: () => {
      // The user's own row also appears in the users list/detail caches.
      void queryClient.invalidateQueries({ queryKey: queryKeys.me })
      void queryClient.invalidateQueries({ queryKey: queryKeys.users.all })
      toast.success('Profile updated')
    },
    onError: (error) => {
      toast.error(errorMessage(error, 'Could not update profile'))
    },
  })
}

export type PermissionCheck = {
  permissions: Permission[]
  can: (permission: Permission) => boolean
  canAny: (...permissions: Permission[]) => boolean
  canAll: (...permissions: Permission[]) => boolean
}

/**
 * Permission checks for the current user.
 *
 * This is presentation only. Hiding a button prevents a pointless
 * request and a confusing 403, but the API enforces the same rule
 * server-side on every call -- the UI is never the security boundary.
 */
export function usePermissions(): PermissionCheck {
  const { data } = useCurrentUser()
  const permissions = data?.permissions ?? []

  return {
    permissions,
    can: (permission) => permissions.includes(permission),
    canAny: (...required) => required.some((p) => permissions.includes(p)),
    canAll: (...required) => required.every((p) => permissions.includes(p)),
  }
}
