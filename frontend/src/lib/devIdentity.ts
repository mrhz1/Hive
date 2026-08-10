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

export function switchUser(username: string): void {
  window.localStorage.setItem(STORAGE_KEY, username)
  window.location.reload()
}

/** Drops the override and returns to the configured VITE_DEV_USERNAME. */
export function resetUser(): void {
  window.localStorage.removeItem(STORAGE_KEY)
  window.location.reload()
}
