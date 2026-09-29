import { expect, test, type Page } from '@playwright/test'

/**
 * The intake path through a real browser: pick a code, create the patient
 * from it, attach its de-identified documents, and read both copies.
 *
 * Needs a code with redacted files waiting, which only a real sweep and a
 * real OCR run produce -- so set one up first (see README "Intake") and name
 * it in E2E_INTAKE_CODE. Without it the test skips rather than failing.
 */
const CODE = process.env.E2E_INTAKE_CODE ?? ''

async function gotoAndSettle(page: Page, path: string) {
  await page.goto(path)
  await expect(page.getByRole('navigation', { name: 'Main' })).toBeVisible()
}

test.describe('an application put together from intake', () => {
  test.skip(!CODE, 'set E2E_INTAKE_CODE to a code with de-identified files waiting')

  test('pick a code, create the patient, attach, read both copies', async ({ page }) => {
    await gotoAndSettle(page, '/applications/new')

    // Step 1: the code comes from the documents.
    await page.getByRole('option', { name: new RegExp(CODE) }).click()
    await expect(page.getByText(`No patient has code ${CODE} yet`)).toBeVisible()

    const code = page.getByRole('textbox', { name: 'Patient code', exact: true })
    await expect(code).toHaveValue(CODE)
    await expect(code).toHaveAttribute('readonly', '')

    await page.getByLabel('First name').fill('Intake E2E')
    await page.getByRole('button', { name: 'Create and continue' }).click()

    // Step 2: its de-identified documents, ready to take.
    await expect(page.getByText(`De-identified documents for`)).toBeVisible()
    await page.getByRole('button', { name: 'Select all' }).click()
    await page.getByRole('button', { name: /^Attach/ }).click()
    await expect(page.getByText(/Attached \d+ documents?/)).toBeVisible()
    await expect(page.getByText(`Nothing left to attach for ${CODE}`)).toBeVisible()

    // De-identification happened in intake; the application offers none.
    await expect(page.getByRole('button', { name: 'De-identify all' })).toHaveCount(0)
    await page.getByRole('button', { name: 'Actions for image.pdf' }).click()
    await expect(page.getByRole('menuitem', { name: /de-identif(y|ication)$/i })).toHaveCount(0)
    await page.keyboard.press('Escape')

    // Both copies, one click apart -- the viewer's toggle.
    await page.getByRole('button', { name: 'Actions for image.pdf' }).click()
    await page.getByRole('menuitem', { name: 'View de-identified' }).click()

    const viewer = page.getByRole('dialog')
    await expect(viewer.getByText('de-identified copy')).toBeVisible()
    await expect(viewer.locator('iframe')).toBeVisible()

    await viewer.getByRole('button', { name: 'Original' }).click()
    await expect(viewer.getByText('de-identified copy')).toBeHidden()
    await expect(viewer.locator('iframe[title="Preview of image.pdf"]')).toBeVisible()

    await viewer.getByRole('button', { name: 'De-identified' }).click()
    await expect(viewer.getByText('de-identified copy')).toBeVisible()
  })
})
