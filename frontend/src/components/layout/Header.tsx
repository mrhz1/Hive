import { Moon, Sun } from 'lucide-react'
import { useCallback } from 'react'
import { useCurrentUser } from '@/hooks/useCurrentUser'
import { useTheme } from '@/hooks/useTheme'
import { UserSwitcher } from './UserSwitcher'

function ThemeToggle() {
  const { theme, toggle } = useTheme()
  const label = theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'

  return (
    <button
      type="button"
      onClick={toggle}
      aria-label={label}
      title={label}
      className="rounded-md border border-[rgb(var(--border))] p-2 text-[rgb(var(--foreground))] transition hover:bg-[rgb(var(--nav-hover-bg))] hover:text-teal-700 focus:ring-2 focus:ring-teal-500 focus:ring-offset-2 focus:outline-none dark:hover:text-teal-300"
    >
      {theme === 'dark' ? (
        <Sun className="size-5" aria-hidden="true" />
      ) : (
        <Moon className="size-5" aria-hidden="true" />
      )}
    </button>
  )
}

/** Initials fallback for the avatar, from the user's name or email. */
function getInitials(first?: string, last?: string, email?: string) {
  const fromName = `${first?.[0] ?? ''}${last?.[0] ?? ''}`.trim()
  if (fromName) return fromName.toUpperCase()
  return (email?.slice(0, 2) ?? 'U').toUpperCase()
}

export function Header({
  onToggleSidebar,
  isSidebarOpen,
}: {
  onToggleSidebar: () => void
  isSidebarOpen: boolean
}) {
  const { data: user } = useCurrentUser()

  const handleToggle = useCallback(
    (event: React.MouseEvent<HTMLButtonElement>) => {
      event.preventDefault()
      event.stopPropagation()
      onToggleSidebar()
    },
    [onToggleSidebar]
  )

  return (
    <header
      role="banner"
      className="sticky top-0 z-50 flex h-16 items-center justify-between border-b border-[rgb(var(--border))] bg-[rgb(var(--background))] px-4 shadow-sm sm:px-6"
    >
      <div className="flex items-center gap-4">
        <button
          onClick={handleToggle}
          aria-label={
            isSidebarOpen ? 'Collapse navigation menu' : 'Expand navigation menu'
          }
          aria-expanded={isSidebarOpen}
          type="button"
          className="rounded-md border border-[rgb(var(--border))] p-2 text-[rgb(var(--foreground))] transition hover:bg-[rgb(var(--nav-hover-bg))] hover:text-teal-700 focus:ring-2 focus:ring-teal-500 focus:ring-offset-2 focus:outline-none dark:hover:text-teal-300"
        >
          <svg
            className="pointer-events-none h-5 w-5"
            fill="none"
            stroke="currentColor"
            viewBox="0 0 24 24"
            xmlns="http://www.w3.org/2000/svg"
          >
            <path
              strokeLinecap="round"
              strokeLinejoin="round"
              strokeWidth="2"
              d="M4 6h16M4 12h16M4 18h16"
            />
          </svg>
        </button>

        <div className="flex items-center gap-2">
          <span className="text-lg font-bold tracking-tight text-[rgb(var(--brand))] sm:text-xl">
            Hive Admin
          </span>
        </div>
      </div>

      <div
        className="flex items-center gap-3 text-sm font-medium"
        aria-label="User Profile"
      >
        <UserSwitcher />
        <ThemeToggle />
        {user ? (
          <div className="flex items-center gap-2">
            <span className="flex h-8 w-8 items-center justify-center rounded-full border border-teal-300 bg-teal-100 font-bold text-teal-700 dark:border-teal-700 dark:bg-teal-900 dark:text-teal-200">
              {getInitials(user.first_name, user.last_name, user.email)}
            </span>
            <span className="hidden font-medium text-[rgb(var(--foreground))] sm:inline-block">
              {user.first_name} {user.last_name}
            </span>
          </div>
        ) : null}
      </div>
    </header>
  )
}
