const STORAGE_KEY = 'hive-admin-dev-username'

const configuredUsername = import.meta.env.VITE_DEV_USERNAME

// A built bundle that still carries a dev identity sends REMOTE-USER
// from the browser. Two things then go wrong quietly: the header is not
// CORS-safelisted, so every request is preflighted and anything
// authenticating in front of the API answers that preflight instead of
// the API -- a CORS error for a request the API never saw; and the API
// trusts REMOTE-USER, so whoever holds the page can name any user in it.
// The platform sets that header itself, which is why DEPLOYMENT.md says
// to leave VITE_DEV_USERNAME unset. Said out loud because a build-time
// variable is invisible afterwards.
if (import.meta.env.PROD && configuredUsername) {
  console.warn(
    `[hive] This build was compiled with VITE_DEV_USERNAME=${configuredUsername}, ` +
      'so it sends REMOTE-USER itself. Rebuild without it: the platform ' +
      'supplies the identity, and sending it here forces a CORS preflight ' +
      'on every request. See DEPLOYMENT.md.'
  )
}

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
