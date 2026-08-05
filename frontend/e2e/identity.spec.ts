import { expect, test, type Page } from '@playwright/test'

/**
 * The local user switcher: proves that picking a different user actually
 * changes the X-User-Id sent to the API, and that the shell re-renders
 * with that user's permissions.
 */

const API = 'http://localhost:8100'

const ADMIN = {
  id: 'admin-id',
  username: 'admin',
  email: 'admin@example.com',
  first_name: 'Ada',
  last_name: 'Admin',
  status: 'active',
  is_active: true,
  role_id: 'role-admin',
  created_at: '2026-07-01T12:00:00',
  role_name: 'admin',
  permissions: [
    'user:view',
    'user:create',
    'user:update',
    'user:delete',
    'role:view',
  ],
}

const VIEWER = {
  ...ADMIN,
  id: 'viewer-id',
  username: 'viewer',
  first_name: 'Vic',
  last_name: 'Viewer',
  email: 'viewer@example.com',
  role_id: 'role-viewer',
  role_name: 'viewer',
  permissions: ['user:view'],
}

const BY_ID: Record<string, typeof ADMIN> = {
  'admin-id': ADMIN,
  'viewer-id': VIEWER,
}

/** Records every X-User-Id the app sent, in order. */
async function mockApi(page: Page, seen: string[]) {
  const json = (body: unknown) => ({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(body),
  })

  await page.route(`${API}/me*`, (route) => {
    // /me resolves whoever the header names -- exactly what the real API
    // does, which is what makes the switch observable.
    const id = route.request().headers()['x-user-id'] ?? ''
    seen.push(id)
    route.fulfill(json(BY_ID[id] ?? ADMIN))
  })
  await page.route(`${API}/roles*`, (route) => route.fulfill(json([])))
  await page.route(`${API}/users*`, (route) => route.fulfill(json([ADMIN, VIEWER])))
}

test.describe('user switcher', () => {
  test('switching user changes the identity sent to the API', async ({ page }) => {
    const seen: string[] = []
    await mockApi(page, seen)

    await page.goto('/users')
    await expect(page.getByRole('navigation', { name: 'Main' })).toBeVisible()

    // Starts as whoever VITE_DEV_USER_ID names; the switcher is available
    // because that variable is configured.
    await expect(page.getByRole('button', { name: 'Switch user' })).toBeVisible()
    const firstIdentity = seen[0]
    expect(firstIdentity).toBeTruthy()

    await page.getByRole('button', { name: 'Switch user' }).click()
    await expect(page.getByText('Act as')).toBeVisible()

    await page.getByRole('button', { name: /^viewer/ }).click()

    // The page reloads as the new user.
    await expect(page.getByRole('navigation', { name: 'Main' })).toBeVisible()
    await expect(page.getByRole('banner').getByText('Vic Viewer')).toBeVisible()

    // A later request carried the switched id, not the configured one.
    expect(seen[seen.length - 1]).toBe('viewer-id')
  })

  test('acting as a read-only user hides the write actions', async ({ page }) => {
    await mockApi(page, [])
    await page.goto('/users')
    await expect(page.getByRole('navigation', { name: 'Main' })).toBeVisible()

    await page.getByRole('button', { name: 'Switch user' }).click()
    await page.getByRole('button', { name: /^viewer/ }).click()
    await expect(page.getByRole('banner').getByText('Vic Viewer')).toBeVisible()

    // viewer holds only user:view.
    await expect(page.getByRole('button', { name: 'Add User' })).toBeHidden()
    await expect(page.getByRole('button', { name: /^Edit / })).toHaveCount(0)
    await expect(page.getByRole('button', { name: /^Delete / })).toHaveCount(0)

    // And a create route it cannot reach renders the 403 page.
    await page.goto('/users/new')
    await expect(page.getByText('You do not have access')).toBeVisible()
  })

  test('resetting returns to the configured user', async ({ page }) => {
    const seen: string[] = []
    await mockApi(page, seen)

    await page.goto('/users')
    await expect(page.getByRole('navigation', { name: 'Main' })).toBeVisible()
    const configured = seen[0]

    await page.getByRole('button', { name: 'Switch user' }).click()
    await page.getByRole('button', { name: /^viewer/ }).click()
    await expect(page.getByRole('banner').getByText('Vic Viewer')).toBeVisible()

    await page.getByRole('button', { name: 'Switch user' }).click()
    await page.getByRole('button', { name: 'Reset to .env.local user' }).click()

    await expect(page.getByRole('navigation', { name: 'Main' })).toBeVisible()
    expect(seen[seen.length - 1]).toBe(configured)
  })
})
