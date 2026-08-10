import type { ReactNode } from 'react'
import { usePermissions } from '@/hooks/useCurrentUser'
import type { Permission } from '@/schemas/common'
import { ForbiddenPage } from './ErrorPages'

export function Can({
  permission,
  children,
  fallback = null,
}: {
  permission: Permission
  children: ReactNode
  fallback?: ReactNode
}) {
  const { can } = usePermissions()
  return can(permission) ? <>{children}</> : <>{fallback}</>
}

export function RequirePermission({
  permission,
  children,
}: {
  permission: Permission
  children: ReactNode
}) {
  const { can } = usePermissions()
  if (!can(permission)) {
    return <ForbiddenPage requiredPermission={permission} />
  }
  return <>{children}</>
}
