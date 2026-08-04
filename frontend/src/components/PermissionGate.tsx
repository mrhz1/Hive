import type { ReactNode } from 'react'
import { usePermissions } from '@/hooks/useCurrentUser'
import type { Permission } from '@/schemas/common'
import { ForbiddenPage } from './ErrorPages'

/**
 * Hides children unless the current user holds the permission.
 *
 * Presentation only -- it stops users being offered actions that would
 * 403, but the API enforces the same rule on every request. Never treat
 * this as the security boundary.
 */
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

/**
 * Page-level guard: renders the 403 page instead of the route body when
 * the user lacks the permission, so a deep link to a forbidden page
 * explains itself rather than erroring on the first request.
 */
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
