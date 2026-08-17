import { afterEach, describe, expect, it, vi } from 'vitest'
import {
  deidProgressLabel,
  deidProgressSchema,
  deidProgressListSchema,
} from '@/schemas/applicationFile'

function progress(overrides: Record<string, unknown> = {}) {
  return deidProgressSchema.parse({
    file_id: 'file-1',
    stage: 'ocr',
    page: 41,
    page_total: 100,
    percent: 39.8,
    ...overrides,
  })
}

describe('deidProgressLabel', () => {
  it('shows the page counter while OCR runs', () => {
    // The percentage alone looks frozen for the 20-30s a page takes;
    // the counter is what shows the run is alive.
    expect(deidProgressLabel('processing', progress())).toBe(
      '40% · page 41 of 100'
    )
  })

  it('says what the last few percent are doing', () => {
    expect(
      deidProgressLabel('processing', progress({ stage: 'redacting' }))
    ).toBe('redacting…')
  })

  it('falls back to the plain status before any progress arrives', () => {
    // Queued, dispatched, but the Job has not written anything yet.
    expect(deidProgressLabel('queued', undefined)).toBe('queued')
  })

  it('does not dress up a status that is not running', () => {
    // A stale progress record must never make a finished file look busy.
    expect(deidProgressLabel('done', progress())).toBe('done')
    expect(deidProgressLabel('failed', progress())).toBe('failed')
  })

  it('handles a document whose length is not known yet', () => {
    expect(
      deidProgressLabel(
        'processing',
        progress({ stage: 'starting', page: 0, page_total: 0, percent: 0 })
      )
    ).toBe('starting…')
  })
})

describe('deidProgressSchema', () => {
  it('accepts the payload the API sends', () => {
    const parsed = deidProgressListSchema.parse({
      items: [
        {
          file_id: 'file-1',
          stage: 'ocr',
          page: 7,
          page_total: 20,
          percent: 33.9,
          file_index: 0,
          file_total: 1,
          updated_at: 1786983111.97,
          error: null,
        },
      ],
    })

    expect(parsed.items[0]?.page).toBe(7)
    expect(parsed.items[0]?.percent).toBeCloseTo(33.9)
  })

  it('treats an application with nothing running as empty', () => {
    expect(deidProgressListSchema.parse({}).items).toEqual([])
  })
})

describe('poll interval configuration', () => {
  // The parser is what stands between a typo in .env and an API being
  // polled twenty times a second, so its edges are worth pinning.
  async function config(env: Record<string, string | undefined>) {
    vi.resetModules()
    vi.stubEnv('VITE_DEID_PROGRESS_ENABLED', env.enabled ?? '')
    vi.stubEnv('VITE_DEID_PROGRESS_POLL_MS', env.poll ?? '')
    vi.stubEnv('VITE_DEID_LIST_REFRESH_MS', env.list ?? '')
    return await import('@/lib/deidProgress')
  }

  afterEach(() => {
    vi.unstubAllEnvs()
    vi.resetModules()
  })

  it('polls on sensible defaults when nothing is set', async () => {
    const c = await config({})
    expect(c.progressPollingEnabled()).toBe(true)
    expect(c.DEID_PROGRESS_POLL_MS).toBe(5000)
    expect(c.DEID_LIST_REFRESH_MS).toBe(15000)
  })

  it('honours an explicit interval', async () => {
    const c = await config({ poll: '30000', list: '60000' })
    expect(c.DEID_PROGRESS_POLL_MS).toBe(30000)
    expect(c.DEID_LIST_REFRESH_MS).toBe(60000)
  })

  it('turns a poller off with 0', async () => {
    const c = await config({ poll: '0', list: '0' })
    expect(c.DEID_PROGRESS_POLL_MS).toBe(false)
    expect(c.DEID_LIST_REFRESH_MS).toBe(false)
    expect(c.progressPollingEnabled()).toBe(false)
  })

  it('disables the feature by flag without touching the intervals', async () => {
    const c = await config({ enabled: 'false' })
    expect(c.progressPollingEnabled()).toBe(false)
    // The list refresh is a separate concern and stays on.
    expect(c.DEID_LIST_REFRESH_MS).toBe(15000)
  })

  it('refuses to poll faster than the floor', async () => {
    // A typo'd '50' would hammer the API; clamped rather than honoured.
    const c = await config({ poll: '50' })
    expect(c.DEID_PROGRESS_POLL_MS).toBe(1000)
  })

  it('falls back rather than polling on nonsense', async () => {
    const c = await config({ poll: 'soon' })
    expect(c.DEID_PROGRESS_POLL_MS).toBe(5000)
  })
})
