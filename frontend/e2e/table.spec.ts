import { expect, test, type Page } from '@playwright/test'

/**
 * Column sorting and the refetch overlay, driven through the real UI with
 * the API mocked so the timings are controllable.
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
    'users:read',
    'users:create',
    'users:update',
    'users:delete',
    'roles:read',
  ],
}

// Deliberately out of alphabetical order so a sort visibly changes it.
const USERS = [
  { username: 'charlie', first: 'Carol', last: 'Cole', status: 'active' },
  { username: 'alice', first: 'Alice', last: 'Adams', status: 'suspended' },
  { username: 'bob', first: 'Bob', last: 'Brown', status: 'inactive' },
].map((u, i) => ({
  id: `user-${i}`,
  username: u.username,
  email: `${u.username}@example.com`,
  first_name: u.first,
  last_name: u.last,
  status: u.status,
  is_active: u.status === 'active',
  role_id: 'role-viewer',
  created_at: `2026-07-0${i + 1}T12:00:00`,
  role_name: 'viewer',
  permissions: [],
}))

async function mockApi(page: Page, options: { refetchDelayMs?: number } = {}) {
  const json = (body: unknown, status = 200) => ({
    status,
    contentType: 'application/json',
    body: JSON.stringify(body),
  })

  await page.route(`${API}/me*`, (route) => route.fulfill(json(ADMIN)))
  await page.route(`${API}/roles*`, (route) =>
    route.fulfill(
      json([{ id: 'role-viewer', name: 'viewer', permissions: ['users:read'] }])
    )
  )

  let reads = 0
  await page.route(`${API}/users*`, async (route) => {
    // Writes succeed immediately; only the read is slowed, which is what
    // the overlay covers.
    if (route.request().method() !== 'GET') {
      await route.fulfill(json({ ...USERS[0], id: 'new-user', username: 'created' }, 201))
      return
    }
    reads += 1
    // The FIRST read must be fast so the list has cached data. Delaying
    // it instead means the initial fetch is still in flight when the test
    // returns, React Query reuses it, and the component is in `isLoading`
    // (first load) rather than `isRefreshing` -- a different state.
    if (reads > 1 && options.refetchDelayMs) {
      await new Promise((resolve) => setTimeout(resolve, options.refetchDelayMs))
    }
    await route.fulfill(json(USERS))
  })
}

/** Usernames in the order they currently appear in the table. */
async function usernameColumn(page: Page) {
  const cells = page.locator('tbody tr td:first-child')
  return (await cells.allInnerTexts()).map((t) => t.trim())
}

test.describe('column sorting', () => {
  test('sorts ascending, then descending, then clears', async ({ page }) => {
    await mockApi(page)
    await page.goto('/users')
    await expect(page.getByRole('table')).toBeVisible()

    const original = await usernameColumn(page)
    expect(original).toEqual(['charlie', 'alice', 'bob'])

    const usernameHeader = page.getByRole('button', { name: 'Sort by Username' })

    await usernameHeader.click()
    await expect.poll(() => usernameColumn(page)).toEqual(['alice', 'bob', 'charlie'])

    await usernameHeader.click()
    await expect.poll(() => usernameColumn(page)).toEqual(['charlie', 'bob', 'alice'])

    // Third click restores the API's own order.
    await usernameHeader.click()
    await expect.poll(() => usernameColumn(page)).toEqual(original)
  })

  test('exposes sort direction to assistive tech', async ({ page }) => {
    await mockApi(page)
    await page.goto('/users')

    const header = page.getByRole('columnheader', { name: /Username/ })
    await expect(header).toHaveAttribute('aria-sort', 'none')

    await page.getByRole('button', { name: 'Sort by Username' }).click()
    await expect(header).toHaveAttribute('aria-sort', 'ascending')

    await page.getByRole('button', { name: 'Sort by Username' }).click()
    await expect(header).toHaveAttribute('aria-sort', 'descending')
  })

  test('sorts on the underlying value, not the rendered badge', async ({ page }) => {
    await mockApi(page)
    await page.goto('/users')
    await expect(page.getByRole('table')).toBeVisible()

    // Status renders as a Badge; sorting must use the status string.
    await page.getByRole('button', { name: 'Sort by Status' }).click()
    await expect.poll(() => usernameColumn(page)).toEqual(['charlie', 'bob', 'alice']) // active, inactive, suspended
  })

  test('sorting a numeric column orders numerically', async ({ page }) => {
    await page.route(`${API}/me*`, (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(ADMIN),
      })
    )
    await page.route(`${API}/roles*`, (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([
          { id: 'r1', name: 'ten', permissions: Array(10).fill('users:read') },
          { id: 'r2', name: 'two', permissions: ['users:read', 'roles:read'] },
          { id: 'r3', name: 'none', permissions: [] },
        ]),
      })
    )

    await page.goto('/roles')
    await expect(page.getByRole('table')).toBeVisible()

    await page.getByRole('button', { name: 'Sort by Grants' }).click()
    const grants = await page.locator('tbody tr td:nth-child(2)').allInnerTexts()
    // Numeric, not lexicographic ("10" must not sort before "2").
    expect(grants.map((g) => Number(g.trim()))).toEqual([0, 2, 10])
  })
})

test.describe('refetch overlay', () => {
  test('shows an updating indicator after a create refetches the list', async ({
    page,
  }) => {
    // Refetch slow enough to observe, as it is on Hive.
    await mockApi(page, { refetchDelayMs: 4000 })

    await page.goto('/users')
    // Wait for real rows, not just the table shell -- the list must have
    // cached data for the refetch to be a *refresh* rather than a load.
    await expect(page.getByRole('cell', { name: 'charlie', exact: true })).toBeVisible()
    await expect(page.getByText('Updating…')).toBeHidden()

    // The reported scenario: create a user, land back on the list while
    // the invalidated query is still refetching.
    await page.getByRole('button', { name: 'Add User' }).click()
    await expect(page).toHaveURL(/\/users\/new$/)

    // The router swaps the URL before the lazily-loaded route mounts, so
    // wait for the form itself. Without this the old table is still in
    // the DOM and getByLabel('Username') resolves to its sort button.
    const submit = page.getByRole('button', { name: 'Create user' })
    await expect(submit).toBeVisible()

    // Scoped to the form: on the list page the sort buttons are labelled
    // "Sort by Username", which getByLabel would otherwise match.
    const form = page.locator('form')
    await form.getByLabel('Username').fill('created')
    await form.getByLabel('Email').fill('created@example.com')
    await form.getByLabel('First name').fill('Cre')
    await form.getByLabel('Last name').fill('Ated')
    // Role is required on the user form.
    await form.getByLabel('Role').selectOption({ label: 'viewer' })
    await submit.click()

    await expect(page).toHaveURL(/\/users$/)

    // Rows stay on screen (from cache) while the overlay reports the
    // refresh -- the point of the change.
    await expect(page.getByText('Updating…')).toBeVisible()
    await expect(page.locator('tbody tr')).not.toHaveCount(0)
    await expect(page.getByText('Updating…')).toBeHidden({ timeout: 20_000 })
  })
})
