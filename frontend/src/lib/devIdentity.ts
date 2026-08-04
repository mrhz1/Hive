/**
 * Local identity switching.
 *
 * There is no login. On Cloudera AI the platform authenticates the caller
 * and the API resolves them, so VITE_DEV_USER_ID is left unset there and
 * nothing below is active -- the switcher does not render and no
 * X-User-Id header is sent.
 *
 * Locally VITE_DEV_USER_ID provides a default identity, and this module
 * lets it be overridden at runtime so RBAC can be tested by switching
 * users without restarting Vite (which bakes env vars at startup).
 *
 * The override is availability-gated on configuration, not on an
 * environment check: no VITE_DEV_USER_ID means no switching, full stop.
 */
const STORAGE_KEY = 'hive-admin-dev-user-id'

const configuredUserId = import.meta.env.VITE_DEV_USER_ID

/** True when this build was given a dev identity to start from. */
export function isIdentitySwitchable(): boolean {
  return Boolean(configuredUserId)
}

/** The id to send as X-User-Id, override first, else the configured one. */
export function getActiveUserId(): string | undefined {
  if (!configuredUserId) return undefined
  if (typeof window === 'undefined') return configuredUserId
  return window.localStorage.getItem(STORAGE_KEY) || configuredUserId
}

/** True when the active identity came from a switch rather than config. */
export function hasIdentityOverride(): boolean {
  if (typeof window === 'undefined') return false
  return Boolean(window.localStorage.getItem(STORAGE_KEY))
}

/**
 * Switches identity and reloads.
 *
 * A reload rather than a cache invalidation: every query, and the
 * permission-gated shell around them, was resolved for the previous user.
 * Starting clean is both simpler and a more honest simulation of arriving
 * as a different person.
 */
export function switchUser(userId: string): void {
  window.localStorage.setItem(STORAGE_KEY, userId)
  window.location.reload()
}

/** Drops the override and returns to the configured VITE_DEV_USER_ID. */
export function resetUser(): void {
  window.localStorage.removeItem(STORAGE_KEY)
  window.location.reload()
}
