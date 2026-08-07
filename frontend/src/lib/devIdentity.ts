/**
 * Local identity switching.
 *
 * There is no login. On Cloudera AI the platform authenticates the caller
 * and passes the username down in REMOTE-USER, so VITE_DEV_USERNAME is
 * left unset there and nothing below is active -- the switcher does not
 * render and the app sets no identity header of its own.
 *
 * Locally VITE_DEV_USERNAME provides a default identity, and this module
 * lets it be overridden at runtime so RBAC can be tested by switching
 * users without restarting Vite (which bakes env vars at startup).
 *
 * The override is availability-gated on configuration, not on an
 * environment check: no VITE_DEV_USERNAME means no switching, full stop.
 */
const STORAGE_KEY = 'hive-admin-dev-username'

const configuredUsername = import.meta.env.VITE_DEV_USERNAME

/** True when this build was given a dev identity to start from. */
export function isIdentitySwitchable(): boolean {
  return Boolean(configuredUsername)
}

/** The name to send as REMOTE-USER, override first, else the configured one. */
export function getActiveUsername(): string | undefined {
  if (!configuredUsername) return undefined
  if (typeof window === 'undefined') return configuredUsername
  return window.localStorage.getItem(STORAGE_KEY) || configuredUsername
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
export function switchUser(username: string): void {
  window.localStorage.setItem(STORAGE_KEY, username)
  window.location.reload()
}

/** Drops the override and returns to the configured VITE_DEV_USERNAME. */
export function resetUser(): void {
  window.localStorage.removeItem(STORAGE_KEY)
  window.location.reload()
}
