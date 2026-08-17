import { describe, expect, it } from 'vitest'
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
