const STORAGE_KEY = 'hive-admin-dev-username'

const configuredUsername = import.meta.env.VITE_DEV_USERNAME

if (import.meta.env.PROD && configuredUsername) {
  console.warn(
    `[hive] This build was compiled with VITE_DEV_USERNAME=${configuredUsername}, ` +
      'so it sends REMOTE-USER itself. Rebuild without it: the platform ' +
      'supplies the identity, and sending it here forces a CORS preflight ' +
      'on every request. See DEPLOYMENT.md.'
  )
}

export function isIdentitySwitchable(): boolean {
  return Boolean(configuredUsername)
}

export function getActiveUsername(): string | undefined {
  if (!configuredUsername) return undefined
  if (typeof window === 'undefined') return configuredUsername
  return window.localStorage.getItem(STORAGE_KEY) || configuredUsername
}

export function hasIdentityOverride(): boolean {
  if (typeof window === 'undefined') return false
  return Boolean(window.localStorage.getItem(STORAGE_KEY))
}

export function switchUser(username: string): void {
  window.localStorage.setItem(STORAGE_KEY, username)
  window.location.reload()
}

export function resetUser(): void {
  window.localStorage.removeItem(STORAGE_KEY)
  window.location.reload()
}
