import { expect, test, type Page } from '@playwright/test'


const ALL_PERMISSIONS = [
  'user:view',
  'user:create',
  'user:update',
  'user:delete',
  'patient:view',
  'patient:create',
  'patient:update',
  'patient:delete',
  'role:view',
  'role:create',
  'role:update',
  'role:delete',
  'log:view',
  'log:create',
  'log:update',
  'log:delete',
  'application:view',
  'application:create',
  'application:update',
  'application:delete',
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
    permissions: ['user:view'],
  })),
]

const PATIENTS = Array.from({ length: 5 }, (_, i) => ({
  id: `pat-${i}`,
  instcode: `INST${String(i + 1).padStart(3, '0')}`,
  pname: `Springfield Clinic ${i + 1}`,
  pemail: `clinic${i + 1}@example.com`,
  phone1: `+1555100${String(i).padStart(4, '0')}`,
  phone2: null,
  wphone1: null,
  wphone2: null,
  street: `${i + 1} Medical Plaza`,
  street2: null,
  street3: null,
  city: 'Springfield',
  state: 'IL',
  zip: `627${String(i).padStart(2, '0')}`,
  country: 'US',
  fstname: `Pat${i + 1}`,
  lstname: `Last${i + 1}`,
  ptemail: `patient${i + 1}@example.com`,
  ptphone: `+1555300${String(i).padStart(4, '0')}`,
  ptphone2: null,
  ptwphone: null,
  ptwphone2: null,
  ptstreet: `${i + 1} Elm St`,
  ptstreet2: null,
  ptstreet3: null,
  ptcity: 'Springfield',
  ptstate: 'IL',
  ptzip: `627${String(i).padStart(2, '0')}`,
  ptcountry: 'US',
  dt_reg: '2026-07-03',
  dt_b: `19${60 + i}-01-02`,
  dt_d: null,
  original_file_path: `/data/patient-${i + 1}`,
  de_identified_file_path: null,
  status: i % 3 === 0 ? 'discharged' : 'active',
  is_active: true,
  created_at: '2026-07-03T12:00:00',
}))

const ROLES = [
  { id: 'role-admin', name: 'admin', permissions: ALL_PERMISSIONS },
  {
    id: 'role-viewer',
    name: 'viewer',
    permissions: ['user:view', 'patient:view', 'role:view', 'log:view'],
  },
]

const LOGS = Array.from({ length: 4 }, (_, i) => ({
  id: `log-${i}`,
  action: (['CREATE', 'UPDATE', 'DELETE'] as const)[i % 3],
  entity_type: i % 2 === 0 ? 'user' : 'patient',
  entity_id: `entity-${i}`,
  old_values: i % 3 === 0 ? null : { status: 'active' },
  new_values: i % 3 === 2 ? null : { status: 'suspended' },
  created_at: '2026-08-01T10:00:00',
}))

const APPLICATIONS = Array.from({ length: 3 }, (_, i) => ({
  id: `application-${i}`,
  patient_id: `patient-${i}`,
  submitted_by_id: i === 0 ? null : 'admin-id',
  reviewed_by_id: i === 2 ? 'admin-id' : null,
  status: (['draft', 'submitted', 'approved'] as const)[i],
  description: i === 2 ? 'Looks good' : null,
  created_by_id: 'admin-id',
  updated_by_id: 'admin-id',
  submitted_at: i === 0 ? null : '2026-08-02T09:00:00',
  created_at: '2026-08-01T09:00:00',
  updated_at: '2026-08-02T09:00:00',
  reviewed_at: i === 2 ? '2026-08-03T09:00:00' : null,
}))

const API = 'http://localhost:8100'

async function mockApi(page: Page) {
  const json = (body: unknown) => ({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(body),
  })

  await page.route(`${API}/me*`, (route) => route.fulfill(json(ADMIN)))
  await page.route(`${API}/users*`, (route) => route.fulfill(json(USERS)))
  await page.route(`${API}/patients*`, (route) => route.fulfill(json(PATIENTS)))
  await page.route(`${API}/roles*`, (route) => route.fulfill(json(ROLES)))
  await page.route(`${API}/logs*`, (route) => route.fulfill(json(LOGS)))
  await page.route(`${API}/applications*`, (route) =>
    route.fulfill(json(APPLICATIONS))
  )
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
  { path: '/patients', name: 'patients' },
  { path: '/applications', name: 'applications' },
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
