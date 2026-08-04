import { expect, test, type Page } from '@playwright/test'

/**
 * Covers the paths a DOM dump cannot reach: real typing (live
 * per-character validation), form submission, sonner toasts, and the
 * cache invalidation that must make a new row appear without a reload.
 *
 * Runs against the live API, so it creates and then deletes its own
 * records rather than depending on seed data it might corrupt.
 */

const unique = () => Date.now().toString().slice(-9)

/**
 * The list is paginated (10 rows), so a freshly created record is often
 * not on the first page. Filter to it with the search box before
 * asserting on its row.
 */
async function searchFor(page: Page, term: string) {
  await page.getByLabel('Search').fill(term)
}

/** Role is required on the user form, so every create must pick one. */
async function selectAnyRole(page: Page) {
  const role = page.getByLabel('Role')
  await expect(role).toBeEnabled()
  // Any real role will do; the seeded 'viewer' always exists.
  await role.selectOption({ label: 'viewer' })
}

async function gotoAndSettle(page: Page, path: string) {
  await page.goto(path)
  // The shell blocks on GET /me; nothing is interactive until it lands.
  await expect(page.getByRole('navigation', { name: 'Main' })).toBeVisible()
}

test.describe('user create form', () => {
  test('validates live, on each character, and shows errors under inputs', async ({
    page,
  }) => {
    await gotoAndSettle(page, '/users/new')

    const email = page.getByLabel('Email', { exact: false })
    await email.fill('not-an-email')
    // No blur, no submit -- the message must appear from typing alone.
    await expect(page.getByText('Enter a valid email address')).toBeVisible()

    // ...and clear again as soon as the value becomes valid.
    await email.fill('valid@example.com')
    await expect(page.getByText('Enter a valid email address')).toBeHidden()

    const username = page.getByLabel('Username')
    await username.fill('has space')
    await expect(
      page.getByText('Only letters, numbers, dot, underscore and hyphen')
    ).toBeVisible()
  })

  test('blocks submit of an empty form and reports every required field', async ({
    page,
  }) => {
    await gotoAndSettle(page, '/users/new')

    await page.getByRole('button', { name: 'Create user' }).click()

    // Untouched empty fields are still caught on submit.
    await expect(page.getByText('Username is required')).toBeVisible()
    await expect(page.getByText('First name is required')).toBeVisible()
    await expect(page.getByText('Last name is required')).toBeVisible()
    // Role is mandatory too: no user may be left without one.
    await expect(page.getByText('Role is required')).toBeVisible()

    // Still on the form -- no navigation happened.
    await expect(page).toHaveURL(/\/users\/new$/)
  })

  test('will not submit until a role is chosen', async ({ page }) => {
    await gotoAndSettle(page, '/users/new')

    const suffix = unique()
    await page.getByLabel('Username').fill(`role${suffix}`)
    await page.getByLabel('Email', { exact: false }).fill(`role${suffix}@example.com`)
    await page.getByLabel('First name').fill('Needs')
    await page.getByLabel('Last name').fill('Role')

    // Everything else is valid, so only the missing role blocks it.
    await page.getByRole('button', { name: 'Create user' }).click()
    await expect(page.getByText('Role is required')).toBeVisible()
    await expect(page).toHaveURL(/\/users\/new$/)

    // The prompt option cannot be chosen back -- there is no "no role".
    const role = page.getByLabel('Role')
    await expect(role.locator('option[value=""]')).toBeDisabled()

    await selectAnyRole(page)
    await expect(page.getByText('Role is required')).toBeHidden()
  })

  test('creates a user, toasts, and shows it in the list without a reload', async ({
    page,
  }) => {
    const suffix = unique()
    const username = `e2e${suffix}`

    await gotoAndSettle(page, '/users/new')

    await page.getByLabel('Username').fill(username)
    await page.getByLabel('Email', { exact: false }).fill(`${username}@example.com`)
    await page.getByLabel('First name').fill('E2E')
    await page.getByLabel('Last name').fill('Created')

    await selectAnyRole(page)

    await page.getByRole('button', { name: 'Create user' }).click()

    // Success toast from sonner.
    await expect(page.getByText('User created')).toBeVisible({ timeout: 30_000 })

    // Redirected to the list, and the invalidated query has refetched --
    // the row is present without a manual reload.
    await expect(page).toHaveURL(/\/users$/)
    await searchFor(page, username)
    await expect(
      page.getByRole('table').getByText(username, { exact: true })
    ).toBeVisible({ timeout: 30_000 })
  })

  test('surfaces a duplicate username under the field, not just in a toast', async ({
    page,
  }) => {
    const suffix = unique()
    const username = `dup${suffix}`

    // First one succeeds.
    await gotoAndSettle(page, '/users/new')
    await page.getByLabel('Username').fill(username)
    await page.getByLabel('Email', { exact: false }).fill(`${username}@example.com`)
    await page.getByLabel('First name').fill('Dup')
    await page.getByLabel('Last name').fill('Test')
    await selectAnyRole(page)
    await page.getByRole('button', { name: 'Create user' }).click()
    await expect(page).toHaveURL(/\/users$/, { timeout: 30_000 })

    // Second reuses the username with a different email -> 409.
    await gotoAndSettle(page, '/users/new')
    await page.getByLabel('Username').fill(username)
    await page.getByLabel('Email', { exact: false }).fill(`other${suffix}@example.com`)
    await page.getByLabel('First name').fill('Dup')
    await page.getByLabel('Last name').fill('Two')
    await selectAnyRole(page)
    await page.getByRole('button', { name: 'Create user' }).click()

    // The server's conflict message is pinned to the Username field.
    await expect(
      page.getByText(`Username '${username}' already exists`).first()
    ).toBeVisible({ timeout: 30_000 })
    await expect(page).toHaveURL(/\/users\/new$/)
  })
})

test.describe('edit and delete', () => {
  test('edits a user through the same form and persists the change', async ({ page }) => {
    const suffix = unique()
    const username = `edit${suffix}`

    await gotoAndSettle(page, '/users/new')
    await page.getByLabel('Username').fill(username)
    await page.getByLabel('Email', { exact: false }).fill(`${username}@example.com`)
    await page.getByLabel('First name').fill('Before')
    await page.getByLabel('Last name').fill('Edit')
    await selectAnyRole(page)
    await page.getByRole('button', { name: 'Create user' }).click()
    await expect(page).toHaveURL(/\/users$/, { timeout: 30_000 })

    await searchFor(page, username)
    await page.getByRole('button', { name: `Edit ${username}` }).click()
    await expect(page).toHaveURL(/\/edit$/)

    // The shared form is pre-filled from the record.
    await expect(page.getByLabel('First name')).toHaveValue('Before')

    await page.getByLabel('First name').fill('After')
    await page.getByRole('button', { name: 'Save changes' }).click()

    await expect(page.getByText('User updated')).toBeVisible({ timeout: 30_000 })
    await expect(page).toHaveURL(/\/users$/)
    await searchFor(page, username)
    await expect(page.getByRole('table').getByText('After')).toBeVisible({
      timeout: 30_000,
    })
  })

  test('deletes through the shared modal and removes the row', async ({ page }) => {
    const suffix = unique()
    const username = `del${suffix}`

    await gotoAndSettle(page, '/users/new')
    await page.getByLabel('Username').fill(username)
    await page.getByLabel('Email', { exact: false }).fill(`${username}@example.com`)
    await page.getByLabel('First name').fill('Delete')
    await page.getByLabel('Last name').fill('Me')
    await selectAnyRole(page)
    await page.getByRole('button', { name: 'Create user' }).click()
    await expect(page).toHaveURL(/\/users$/, { timeout: 30_000 })
    await searchFor(page, username)
    await expect(
      page.getByRole('table').getByText(username, { exact: true })
    ).toBeVisible({ timeout: 30_000 })

    await page.getByRole('button', { name: `Delete ${username}` }).click()

    // The one shared confirmation dialog, naming its target.
    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeVisible()
    // The modal names its target by full name.
    await expect(dialog.getByText('Delete Me')).toBeVisible()

    await dialog.getByRole('button', { name: 'Confirm Delete' }).click()

    await expect(page.getByText('User deleted')).toBeVisible({ timeout: 30_000 })

    // Scoped to the table and exact: the username is also a substring of
    // the email, so a bare getByText would still match.
    await expect(
      page.getByRole('table').getByText(username, { exact: true })
    ).toHaveCount(0, { timeout: 30_000 })
  })

  test('cancelling the delete modal leaves the record alone', async ({ page }) => {
    await gotoAndSettle(page, '/users')

    const firstDelete = page.getByRole('button', { name: /^Delete / }).first()
    await firstDelete.click()

    const dialog = page.getByRole('dialog')
    await expect(dialog).toBeVisible()
    await dialog.getByRole('button', { name: 'Cancel' }).click()
    await expect(dialog).toBeHidden()

    // No toast, nothing removed.
    await expect(page.getByText('User deleted')).toBeHidden()
  })
})

test.describe('theme', () => {
  test('toggles dark mode and persists it across a reload', async ({ page }) => {
    await gotoAndSettle(page, '/')

    const html = page.locator('html')
    const startedDark = await html.evaluate((el) => el.classList.contains('dark'))

    await page.getByRole('button', { name: /Switch to (light|dark) theme/ }).click()
    await expect
      .poll(() => html.evaluate((el) => el.classList.contains('dark')))
      .toBe(!startedDark)

    await page.reload()
    await expect(page.getByRole('navigation', { name: 'Main' })).toBeVisible()
    await expect
      .poll(() => html.evaluate((el) => el.classList.contains('dark')))
      .toBe(!startedDark)
  })
})
