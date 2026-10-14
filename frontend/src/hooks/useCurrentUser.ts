import { useQuery } from '@tanstack/react-query'
import { meApi } from '@/lib/api/resources'
import { queryKeys } from '@/lib/queryKeys'
import type { Permission } from '@/schemas/common'

export function useCurrentUser() {
  return useQuery({
    queryKey: queryKeys.me,
    queryFn: meApi.get,
    staleTime: 5 * 60_000,
    retry: false,
  })
}

export type PermissionCheck = {
  permissions: Permission[]
  can: (permission: Permission) => boolean
  canAny: (...permissions: Permission[]) => boolean
  canAll: (...permissions: Permission[]) => boolean
}

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
