import { describe, expect, it } from 'vitest'
import {
  isUploadJobSettled,
  uploadJobSummary,
  uploadJobTone,
  uploadJobSchema,
} from '@/schemas/applicationFile'
import {
  activeFilters,
  fileMetadataRowSchema,
  metadataEntries,
  metadataFieldCount,
  metadataPreview,
} from '@/schemas/fileMetadata'

function row(overrides: Record<string, unknown> = {}) {
  return fileMetadataRowSchema.parse({
    id: 'meta-1',
    file_id: 'file-1',
    file_type: 'pdf',
    metadata: { Author: 'Ada', Title: 'Scan', Producer: '' },
    status: 'ok',
    created_at: '2026-08-01T10:00:00Z',
    file_name: 'scan.pdf',
    ...overrides,
  })
}

function job(overrides: Record<string, unknown> = {}) {
  return uploadJobSchema.parse({
    id: 'job-1',
    application_id: 'app-1',
    status: 'running',
    total: 3,
    stored: 1,
    failed: 0,
    created_at: '2026-08-01T10:00:00Z',
    files: [],
    ...overrides,
  })
}

describe('file metadata rows', () => {
  it('reads a row that carries no metadata at all', () => {
    const parsed = fileMetadataRowSchema.parse({
      id: 'meta-1',
      file_id: 'file-1',
      file_type: 'pdf',
      status: 'unsupported',
      created_at: '2026-08-01T10:00:00Z',
    })

    expect(parsed.metadata).toEqual({})
    expect(metadataFieldCount(parsed)).toBe(0)
    expect(metadataPreview(parsed)).toBe('No fields extracted')
  })

  it('sorts entries by field name', () => {
    expect(metadataEntries(row()).map(([name]) => name)).toEqual([
      'Author',
      'Producer',
      'Title',
    ])
  })

  it('leaves empty fields out of the preview', () => {
    // Producer is blank; showing 'Producer: ' would waste the one line.
    expect(metadataPreview(row())).toBe('Author: Ada · Title: Scan')
  })

  it('says how many fields the preview left out', () => {
    const preview = metadataPreview(
      row({ metadata: { a: '1', b: '2', c: '3', d: '4', e: '5' } })
    )

    expect(preview).toContain('+2 more')
  })

  it('keeps only the filters that were actually filled in', () => {
    expect(
      activeFilters({ search: ' siemens ', status: '', file_type: undefined })
    ).toEqual({ search: ' siemens ' })
  })
})

describe('upload jobs', () => {
  it('keeps polling while a batch is pending or running', () => {
    expect(isUploadJobSettled(job({ status: 'pending' }))).toBe(false)
    expect(isUploadJobSettled(job({ status: 'running' }))).toBe(false)
    expect(isUploadJobSettled(undefined)).toBe(false)
  })

  it('stops polling once the batch has settled, however it ended', () => {
    for (const status of ['done', 'partial', 'failed']) {
      expect(isUploadJobSettled(job({ status }))).toBe(true)
    }
  })

  it('reports a partial batch as neither success nor failure', () => {
    const partial = job({ status: 'partial', stored: 2, failed: 1, total: 3 })

    expect(uploadJobTone(partial.status)).toBe('warning')
    expect(uploadJobSummary(partial)).toBe('2 of 3 files stored; 1 failed.')
  })

  it('surfaces the reason a whole batch failed', () => {
    const failed = job({ status: 'failed', stored: 0, failed: 3, error: 'Hive is down' })

    expect(uploadJobSummary(failed)).toContain('Hive is down')
  })

  it('counts a single stored file in the singular', () => {
    expect(uploadJobSummary(job({ status: 'done', stored: 1, total: 1 }))).toBe(
      '1 file stored.'
    )
  })
})
