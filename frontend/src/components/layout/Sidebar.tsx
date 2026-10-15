import { Link, useRouterState } from '@tanstack/react-router'
import { ChevronRight } from 'lucide-react'
import { memo, useCallback, useState } from 'react'
import { usePermissions } from '@/hooks/useCurrentUser'
import { cn } from '@/lib/cn'
import { NAV_GROUPS, groupForPath } from './navigation'
import type { NavGroup, NavItem } from './navigation'

const COLLAPSED_KEY = 'hive.nav.collapsed'

function readCollapsed(): Record<string, boolean> {
  try {
    const saved = JSON.parse(localStorage.getItem(COLLAPSED_KEY) ?? '{}')
    return saved && typeof saved === 'object' ? saved : {}
  } catch {
    return {}
  }
}

function writeCollapsed(value: Record<string, boolean>) {
  try {
    localStorage.setItem(COLLAPSED_KEY, JSON.stringify(value))
  } catch {
    return
  }
}

function useCollapsedGroups() {
  const pathname = useRouterState({ select: (state) => state.location.pathname })
  const [collapsed, setCollapsed] = useState(() => {
    const saved = readCollapsed()
    const active = groupForPath(pathname)
    return active ? { ...saved, [active.id]: false } : saved
  })
  const [seenPath, setSeenPath] = useState(pathname)

  if (pathname !== seenPath) {
    setSeenPath(pathname)
    const active = groupForPath(pathname)
    if (active && collapsed[active.id]) {
      setCollapsed({ ...collapsed, [active.id]: false })
    }
  }

  const toggle = useCallback((id: string) => {
    setCollapsed((prev) => {
      const next = { ...prev, [id]: !prev[id] }
      writeCollapsed(next)
      return next
    })
  }, [])

  return { collapsed, toggle }
}

function SideBarLink({ item, onNavigate }: { item: NavItem; onNavigate?: () => void }) {
  const Icon = item.icon
  return (
    <Link
      to={item.to}
      onClick={onNavigate}
      activeProps={{
        className:
          'text-[rgb(var(--nav-active-text))] bg-[rgb(var(--nav-active-bg))] shadow-sm shadow-[rgb(var(--nav-shadow))]/50',
      }}
      activeOptions={{ exact: item.to === '/' }}
      className="flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium whitespace-nowrap text-[rgb(var(--nav-text))] transition hover:bg-[rgb(var(--nav-hover-bg))] hover:text-[rgb(var(--nav-active-text))]"
    >
      <Icon className="size-4 shrink-0" aria-hidden="true" />
      {item.label}
    </Link>
  )
}

function SideBarGroup({
  group,
  items,
  open,
  onToggle,
  onNavigate,
}: {
  group: NavGroup
  items: NavItem[]
  open: boolean
  onToggle: (id: string) => void
  onNavigate?: () => void
}) {
  const listId = `nav-${group.id}`
  const links = (
    <div id={listId} className="grid gap-0.5">
      {items.map((item) => (
        <SideBarLink key={item.to} item={item} onNavigate={onNavigate} />
      ))}
    </div>
  )

  if (!group.label) return links

  return (
    <section>
      <h2>
        <button
          type="button"
          onClick={() => onToggle(group.id)}
          aria-expanded={open}
          aria-controls={listId}
          className="flex w-full items-center gap-2 rounded-md px-3 py-1.5 text-xs whitespace-nowrap text-[rgb(var(--foreground-muted))] transition hover:bg-[rgb(var(--nav-hover-bg))] focus:ring-2 focus:ring-teal-500 focus:outline-none"
        >
          {group.tag ? (
            <span className="text-[11px] font-bold tracking-wider text-[rgb(var(--foreground))] uppercase">
              {group.tag}
            </span>
          ) : null}
          <span className="truncate font-medium">{group.label}</span>
          <ChevronRight
            className={cn(
              'ml-auto size-4 shrink-0 transition-transform',
              open && 'rotate-90'
            )}
            aria-hidden="true"
          />
        </button>
      </h2>
      {open ? <div className="mt-1">{links}</div> : null}
    </section>
  )
}

export const Sidebar = memo(function Sidebar({
  isOpen,
  onNavigate,
}: {
  isOpen: boolean
  onNavigate?: () => void
}) {
  const { can } = usePermissions()
  const { collapsed, toggle } = useCollapsedGroups()

  return (
    <aside
      role="navigation"
      aria-label="Main"
      aria-hidden={!isOpen}
      className={`fixed top-16 z-40 flex h-[calc(100vh-4rem)] flex-col overflow-hidden border-r border-[rgb(var(--border))] bg-[rgb(var(--sidebar))] transition-colors duration-300 md:sticky ${
        isOpen ? 'w-64' : 'pointer-events-none invisible w-0'
      }`}
    >
      <div className="flex w-64 flex-col gap-3 overflow-y-auto p-4">
        {NAV_GROUPS.map((group) => {
          const items = group.items.filter(
            (item) => !item.permission || can(item.permission)
          )
          if (items.length === 0) return null
          return (
            <SideBarGroup
              key={group.id}
              group={group}
              items={items}
              open={!collapsed[group.id]}
              onToggle={toggle}
              onNavigate={onNavigate}
            />
          )
        })}
      </div>
    </aside>
  )
})
