import { describe, expect, it } from 'vitest'
import {
  bulkSummary,
  fileHaystack,
  isUploadJobSettled,
  previewKind,
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

describe('preview kinds', () => {
  it('lets the browser render a PDF itself', () => {
    expect(previewKind('pdf')).toBe('pdf')
    expect(previewKind('PDF')).toBe('pdf')
  })

  it('routes DICOM to the image viewer, whichever way it is spelt', () => {
    // The reported bug: these downloaded instead of opening.
    expect(previewKind('dcm')).toBe('image')
    expect(previewKind('dicom')).toBe('image')
  })

  it('routes Word to the text viewer, both generations', () => {
    expect(previewKind('doc')).toBe('text')
    expect(previewKind('docx')).toBe('text')
  })

  it('leaves anything else as a download', () => {
    expect(previewKind('txt')).toBe('download')
    expect(previewKind('')).toBe('download')
  })
})

describe('finding a document in a long list', () => {
  const file = {
    original_file_name: 'Consent-Form.PDF',
    file_extension: 'pdf',
    description: 'signed by the patient',
    review_status: 'pending',
    deid_status: 'done',
  }

  it('matches on name, case-insensitively', () => {
    expect(fileHaystack(file)).toContain('consent-form.pdf')
  })

  it('matches on type and description too', () => {
    const hay = fileHaystack(file)
    expect(hay).toContain('pdf')
    expect(hay).toContain('signed by the patient')
  })

  it('copes with no description', () => {
    expect(() => fileHaystack({ ...file, description: null })).not.toThrow()
  })
})

describe('bulk action summaries', () => {
  const result = (over = {}) => ({
    total: 10,
    changed: 7,
    skipped: 3,
    reasons: {},
    ...over,
  })

  it('says nothing happened when nothing could', () => {
    expect(bulkSummary(result({ changed: 0 }), 'approve')).toBe(
      'Nothing to approve.'
    )
  })

  it('says so when there is nothing there at all', () => {
    expect(bulkSummary(result({ total: 0, changed: 0 }), 'approve')).toBe(
      'There are no documents yet.'
    )
  })

  it('reports what it did and what it left behind', () => {
    expect(
      bulkSummary(
        result({ reasons: { 'rejected, left alone': 3 } }),
        'approve'
      )
    ).toBe('7 of 10 approved; 3 rejected, left alone.')
  })

  it('uses the right verb for de-identification', () => {
    expect(bulkSummary(result({ reasons: {} }), 'de-identify')).toBe(
      '7 of 10 queued.'
    )
  })
})
