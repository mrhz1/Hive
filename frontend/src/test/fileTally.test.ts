import { describe, expect, it } from 'vitest'
import {
  fileTally,
  isFullyDeidentified,
  isFullyReviewed,
  type ApplicationFile,
} from '@/schemas/applicationFile'

function file(overrides: Partial<ApplicationFile> = {}): ApplicationFile {
  return {
    id: 'file-1',
    application_id: 'app-1',
    original_file_name: 'scan.pdf',
    sanitized_file_name: 'scan.pdf',
    file_extension: 'pdf',
    mime_type: 'application/pdf',
    file_size: 1024,
    deid_status: 'pending',
    is_deidentified: false,
    created_at: new Date('2026-01-01T00:00:00Z'),
    file_path: '/storage/scan.pdf',
    review_status: 'pending',
    ...overrides,
  } as ApplicationFile
}

describe('fileTally', () => {
  it('counts an empty application without dividing by zero', () => {
    const tally = fileTally([])
    expect(tally.total).toBe(0)
    // An application with no documents is not "fully de-identified".
    expect(isFullyDeidentified(tally)).toBe(false)
    expect(isFullyReviewed(tally)).toBe(false)
  })

  it('puts every document in exactly one de-identification bucket', () => {
    const tally = fileTally([
      file({ is_deidentified: true, deid_status: 'done' }),
      file({ deid_status: 'processing' }),
      file({ deid_status: 'queued' }),
      file({ deid_status: 'failed' }),
      file({ deid_status: 'pending' }),
    ])

    expect(tally.total).toBe(5)
    expect(tally.deidentified).toBe(1)
    expect(tally.deidRunning).toBe(2)
    expect(tally.deidFailed).toBe(1)
    expect(tally.deidPending).toBe(1)

    // The buckets must partition the set, or the header would claim a
    // batch was finished while something sat unaccounted for.
    expect(
      tally.deidentified + tally.deidRunning + tally.deidFailed + tally.deidPending
    ).toBe(tally.total)
  })

  it('partitions the review states too', () => {
    const tally = fileTally([
      file({ review_status: 'approved' }),
      file({ review_status: 'approved' }),
      file({ review_status: 'rejected' }),
      file({ review_status: 'pending' }),
    ])

    expect(tally.approved).toBe(2)
    expect(tally.rejected).toBe(1)
    expect(tally.undecided).toBe(1)
    expect(tally.approved + tally.rejected + tally.undecided).toBe(tally.total)
  })

  it('only calls a batch fully de-identified when nothing is outstanding', () => {
    const done = fileTally([
      file({ is_deidentified: true, deid_status: 'done' }),
      file({ is_deidentified: true, deid_status: 'done' }),
    ])
    expect(isFullyDeidentified(done)).toBe(true)

    // The case this whole thing exists for: 999 done, one failed hours
    // ago, invisible in a list that long.
    const nearlyDone = fileTally([
      file({ is_deidentified: true, deid_status: 'done' }),
      file({ deid_status: 'failed' }),
    ])
    expect(isFullyDeidentified(nearlyDone)).toBe(false)
    expect(nearlyDone.deidFailed).toBe(1)
  })

  it('does not count a rejected document as undecided', () => {
    // Rejected IS a decision; treating it as outstanding would leave the
    // header permanently claiming work remained.
    const tally = fileTally([file({ review_status: 'rejected' })])
    expect(isFullyReviewed(tally)).toBe(true)
    expect(tally.undecided).toBe(0)
  })

  it('scales to a production-sized application', () => {
    const many = [
      ...Array.from({ length: 998 }, () =>
        file({ is_deidentified: true, deid_status: 'done', review_status: 'approved' })
      ),
      file({ deid_status: 'failed', review_status: 'pending' }),
      file({ is_deidentified: true, deid_status: 'done', review_status: 'rejected' }),
    ]

    const tally = fileTally(many)
    expect(tally.total).toBe(1000)
    expect(tally.deidentified).toBe(999)
    expect(tally.deidFailed).toBe(1)
    expect(tally.approved).toBe(998)
    expect(tally.rejected).toBe(1)
    expect(tally.undecided).toBe(1)
    expect(isFullyDeidentified(tally)).toBe(false)
  })
})
