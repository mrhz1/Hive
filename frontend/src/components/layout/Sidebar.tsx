import { Link } from '@tanstack/react-router'
import { memo } from 'react'
import { Can } from '../PermissionGate'
import { NAV_ITEMS } from './navigation'

function SideBarLink(to: string, text: string, onNavigate?: () => void) {
  return (
    <Link
      to={to}
      onClick={onNavigate}
      activeProps={{
        className:
          'text-[rgb(var(--nav-active-text))] bg-[rgb(var(--nav-active-bg))] shadow-sm shadow-[rgb(var(--nav-shadow))]/50',
      }}
      activeOptions={{ exact: to === '/' }}
      className="flex items-center rounded-lg px-4 py-2.5 text-sm font-medium whitespace-nowrap text-[rgb(var(--nav-text))] transition hover:bg-[rgb(var(--nav-hover-bg))] hover:text-[rgb(var(--nav-active-text))]"
    >
      {text}
    </Link>
  )
}

export const Sidebar = memo(function Sidebar({
  isOpen,
  onNavigate,
}: {
  isOpen: boolean
  onNavigate?: () => void
}) {
  return (
    <aside
      role="navigation"
      aria-label="Main"
      aria-hidden={!isOpen}
      className={`fixed top-16 z-40 flex h-[calc(100vh-4rem)] flex-col overflow-hidden border-r border-[rgb(var(--border))] bg-[rgb(var(--sidebar))] transition-colors duration-300 md:sticky ${
        isOpen ? 'w-64' : 'pointer-events-none invisible w-0'
      }`}
    >
      <div className="grid w-64 space-y-2 p-4">
        {NAV_ITEMS.map(({ label, to, permission }) =>
          permission ? (
            <Can key={to} permission={permission}>
              {SideBarLink(to, label, onNavigate)}
            </Can>
          ) : (
            <div key={to}>{SideBarLink(to, label, onNavigate)}</div>
          )
        )}
      </div>
    </aside>
  )
})
