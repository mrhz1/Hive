import { useRouterState } from '@tanstack/react-router'
import { cn } from '@/lib/cn'
import { ZONE_STYLES, groupForPath } from './navigation'

export function ZoneBadge() {
  const pathname = useRouterState({ select: (state) => state.location.pathname })
  const group = groupForPath(pathname)
  if (!group?.tone || !group.label) return null

  return (
    <span
      className={cn(
        'mb-2 inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-semibold',
        ZONE_STYLES[group.tone].badge
      )}
    >
      {group.tag ? `${group.tag} · ${group.label}` : group.label}
    </span>
  )
}
