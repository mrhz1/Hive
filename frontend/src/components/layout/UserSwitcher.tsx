import { useQuery } from '@tanstack/react-query'
import { RotateCcw, UserCog } from 'lucide-react'
import { useState } from 'react'
import { Button } from '../ui/Button'
import { usersApi } from '@/lib/api/resources'
import {
  getActiveUserId,
  hasIdentityOverride,
  isIdentitySwitchable,
  resetUser,
  switchUser,
} from '@/lib/devIdentity'

/**
 * Switches which user the dashboard is acting as, so RBAC can be checked
 * without restarting the dev server.
 *
 * Only rendered when VITE_DEV_USER_ID is configured. On Cloudera AI that
 * is unset, the platform supplies the identity, and this never appears.
 *
 * Impersonation is not a privilege escalation here: the API already
 * trusts the X-User-Id header locally, so this exposes nothing that was
 * not already available by editing .env.local.
 */
export function UserSwitcher() {
  const [open, setOpen] = useState(false)
  const activeId = getActiveUserId()

  // Only fetched once opened -- a user without user:view gets a 403,
  // which is why the manual id field below is always available.
  const { data: users, error } = useQuery({
    queryKey: ['dev-user-switcher'],
    queryFn: usersApi.list,
    enabled: open,
    retry: false,
    staleTime: 30_000,
  })

  const [manualId, setManualId] = useState('')

  if (!isIdentitySwitchable()) return null

  return (
    <div className="relative">
      <Button
        variant="outline"
        size="sm"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        aria-haspopup="true"
        title="Switch user (local only)"
        leadingIcon={<UserCog className="size-4" aria-hidden="true" />}
      >
        <span className="hidden sm:inline">Switch user</span>
      </Button>

      {open ? (
        <>
          {/* Click-away layer. */}
          <button
            type="button"
            aria-label="Close user switcher"
            className="fixed inset-0 z-40 cursor-default"
            onClick={() => setOpen(false)}
          />

          <div className="absolute right-0 z-50 mt-2 w-80 rounded-xl border border-[rgb(var(--border))] bg-[rgb(var(--surface))] p-4 shadow-xl">
            <p className="text-[11px] font-bold tracking-widest text-[rgb(var(--foreground-muted))] uppercase">
              Act as
            </p>
            <p className="mt-1 text-xs text-[rgb(var(--foreground-muted))]">
              Local testing only. Reloads the page as the chosen user.
            </p>

            {error ? (
              <p className="mt-3 text-xs text-[rgb(var(--foreground-muted))]">
                Your current role cannot list users, so pick by id below.
              </p>
            ) : (
              <ul className="mt-3 max-h-64 space-y-1 overflow-y-auto">
                {(users ?? []).map((user) => {
                  const isActive = user.id === activeId
                  return (
                    <li key={user.id}>
                      <button
                        type="button"
                        onClick={() => switchUser(user.id)}
                        disabled={isActive}
                        className="flex w-full items-center justify-between gap-2 rounded-lg px-3 py-2 text-left text-sm transition hover:bg-[rgb(var(--nav-hover-bg))] disabled:cursor-default disabled:opacity-60"
                      >
                        <span className="min-w-0">
                          <span className="block truncate font-semibold">
                            {user.username}
                          </span>
                          <span className="block truncate text-xs text-[rgb(var(--foreground-muted))]">
                            {user.role_name ?? 'no role'}
                            {user.is_active ? '' : ' · inactive'}
                          </span>
                        </span>
                        {isActive ? (
                          <span className="shrink-0 text-[10px] font-bold tracking-widest text-teal-600 uppercase dark:text-teal-400">
                            current
                          </span>
                        ) : null}
                      </button>
                    </li>
                  )
                })}
              </ul>
            )}

            <div className="mt-3 border-t border-[rgb(var(--border))] pt-3">
              <label
                htmlFor="dev-user-id"
                className="block text-[11px] font-bold tracking-widest text-[rgb(var(--foreground-muted))] uppercase"
              >
                Or paste a user id
              </label>
              <div className="mt-1.5 flex gap-2">
                <input
                  id="dev-user-id"
                  value={manualId}
                  onChange={(event) => setManualId(event.target.value)}
                  placeholder="uuid"
                  className="w-full rounded-lg border border-[rgb(var(--border))] bg-[rgb(var(--input-bg))] px-3 py-1.5 text-xs text-[rgb(var(--input-text))] outline-none focus:border-[rgb(var(--input-ring))]"
                />
                <Button
                  size="sm"
                  disabled={!manualId.trim()}
                  onClick={() => switchUser(manualId.trim())}
                >
                  Go
                </Button>
              </div>

              {hasIdentityOverride() ? (
                <Button
                  variant="ghost"
                  size="sm"
                  className="mt-2 w-full"
                  onClick={resetUser}
                  leadingIcon={<RotateCcw className="size-3.5" aria-hidden="true" />}
                >
                  Reset to .env.local user
                </Button>
              ) : null}
            </div>
          </div>
        </>
      ) : null}
    </div>
  )
}
