import { expect, test, type Page } from '@playwright/test'

/**
 * Visual check of the design system with the API mocked, so the whole UI
 * can be exercised without Hive running. Writes screenshots to
 * screenshots/ for eyeballing light and dark side by side.
 */

const ALL_PERMISSIONS = [
  'users:read',
  'users:create',
  'users:update',
  'users:delete',
  'customers:read',
  'customers:create',
  'customers:update',
  'customers:delete',
  'roles:read',
  'roles:create',
  'roles:update',
  'roles:delete',
  'logs:read',
  'logs:create',
  'logs:update',
  'logs:delete',
]

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
  permissions: ALL_PERMISSIONS,
}

const USERS = [
  ADMIN,
  ...Array.from({ length: 6 }, (_, i) => ({
    id: `user-${i}`,
    username: `user${i + 1}`,
    email: `user${i + 1}@example.com`,
    first_name: `First${i + 1}`,
    last_name: `Last${i + 1}`,
    status: i % 4 === 0 ? 'inactive' : 'active',
    is_active: i % 4 !== 0,
    role_id: 'role-viewer',
    created_at: '2026-07-02T12:00:00',
    role_name: 'viewer',
    permissions: ['users:read'],
  })),
]

const CUSTOMERS = Array.from({ length: 5 }, (_, i) => ({
  id: `cust-${i}`,
  email: `customer${i + 1}@example.com`,
  first_name: `Cust${i + 1}`,
  last_name: `Last${i + 1}`,
  phone_number: `+1555000${String(i).padStart(4, '0')}`,
  address: `${i + 1} Main St`,
  status: i % 3 === 0 ? 'vip' : 'active',
  is_active: true,
  created_at: '2026-07-03T12:00:00',
}))

const ROLES = [
  { id: 'role-admin', name: 'admin', permissions: ALL_PERMISSIONS },
  {
    id: 'role-viewer',
    name: 'viewer',
    permissions: ['users:read', 'customers:read', 'roles:read', 'logs:read'],
  },
]

const LOGS = Array.from({ length: 4 }, (_, i) => ({
  id: `log-${i}`,
  action: (['CREATE', 'UPDATE', 'DELETE'] as const)[i % 3],
  entity_type: i % 2 === 0 ? 'user' : 'customer',
  entity_id: `entity-${i}`,
  old_values: i % 3 === 0 ? null : { status: 'active' },
  new_values: i % 3 === 2 ? null : { status: 'suspended' },
  created_at: '2026-08-01T10:00:00',
}))

const API = 'http://localhost:8100'

async function mockApi(page: Page) {
  const json = (body: unknown) => ({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(body),
  })

  // Scoped to the API origin. A bare '**/users**' would also swallow the
  // dev server's own navigation to /users and serve JSON as the document.
  await page.route(`${API}/me*`, (route) => route.fulfill(json(ADMIN)))
  await page.route(`${API}/users*`, (route) => route.fulfill(json(USERS)))
  await page.route(`${API}/customers*`, (route) => route.fulfill(json(CUSTOMERS)))
  await page.route(`${API}/roles*`, (route) => route.fulfill(json(ROLES)))
  await page.route(`${API}/logs*`, (route) => route.fulfill(json(LOGS)))
}

async function setTheme(page: Page, theme: 'light' | 'dark') {
  await page.addInitScript((value) => {
    window.localStorage.setItem('hive-admin-theme', value)
  }, theme)
}

const PAGES = [
  { path: '/', name: 'dashboard' },
  { path: '/users', name: 'users' },
  { path: '/users/new', name: 'user-form' },
  { path: '/customers', name: 'customers' },
  { path: '/roles', name: 'roles' },
  { path: '/roles/new', name: 'role-form' },
  { path: '/logs', name: 'logs' },
  { path: '/profile', name: 'profile' },
]

for (const theme of ['light', 'dark'] as const) {
  test.describe(`${theme} theme`, () => {
    for (const { path, name } of PAGES) {
      test(`${name} renders`, async ({ page }) => {
        await setTheme(page, theme)
        await mockApi(page)
        await page.goto(path)

        // The shell only renders once /me resolves.
        await expect(page.getByRole('navigation', { name: 'Main' })).toBeVisible()
        await expect(page.getByRole('banner')).toBeVisible()

        await page.waitForTimeout(400)
        await page.screenshot({
          path: `screenshots/${theme}-${name}.png`,
          fullPage: true,
        })
      })
    }
  })
}

test.describe('design system', () => {
  test('applies the theme tokens and brand colour', async ({ page }) => {
    await setTheme(page, 'light')
    await mockApi(page)
    await page.goto('/')
    await expect(page.getByRole('banner')).toBeVisible()

    // Tokens resolve to the sample's slate/teal palette.
    const background = await page
      .locator('body')
      .evaluate((el) => getComputedStyle(el).backgroundColor)
    expect(background).toBe('rgb(248, 250, 252)')

    const brand = await page
      .getByRole('banner')
      .getByText('Hive Admin')
      .evaluate((el) => getComputedStyle(el).color)
    expect(brand).toBe('rgb(13, 148, 136)')
  })

  test('table header uses uppercase tracked labels', async ({ page }) => {
    await setTheme(page, 'light')
    await mockApi(page)
    await page.goto('/users')

    const header = page.getByRole('columnheader', { name: 'Username' })
    await expect(header).toBeVisible()
    const transform = await header.evaluate((el) => getComputedStyle(el).textTransform)
    expect(transform).toBe('uppercase')
  })

  test('dark mode flips the surface tokens', async ({ page }) => {
    await setTheme(page, 'dark')
    await mockApi(page)
    await page.goto('/')
    await expect(page.getByRole('banner')).toBeVisible()

    const background = await page
      .locator('body')
      .evaluate((el) => getComputedStyle(el).backgroundColor)
    expect(background).toBe('rgb(2, 6, 23)')
  })

  test('sidebar collapses from the header toggle', async ({ page }) => {
    await setTheme(page, 'light')
    await mockApi(page)
    await page.goto('/')

    const sidebar = page.getByRole('navigation', { name: 'Main' })
    await expect(sidebar).toBeVisible()

    await page.getByRole('button', { name: 'Collapse navigation menu' }).click()
    await expect(sidebar).toBeHidden()

    await page.getByRole('button', { name: 'Expand navigation menu' }).click()
    await expect(sidebar).toBeVisible()
  })
})
