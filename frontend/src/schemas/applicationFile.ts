import { z } from 'zod'
import { idSchema, timestampSchema } from './common'

export const DEID_STATUSES = [
  'pending',
  'queued',
  'processing',
  'done',
  'failed',
] as const
export type DeidStatus = (typeof DEID_STATUSES)[number]

/** Whether a run is already underway, so it must not be started twice. */
export function isDeidInFlight(status: string): boolean {
  return status === 'queued' || status === 'processing'
}

export const applicationFileSchema = z.object({
  id: idSchema,
  application_id: idSchema,
  original_file_name: z.string(),
  sanitized_file_name: z.string(),
  deidentified_file_name: z.string().nullable().optional(),
  file_extension: z.string(),
  mime_type: z.string(),
  file_size: z.number(),
  deid_status: z.string(),
  is_deidentified: z.boolean(),
  created_at: timestampSchema,
  description: z.string().nullable().optional(),
  file_path: z.string(),
  de_identified_file_path: z.string().nullable().optional(),
  review_status: z.string().default('pending'),
  review_note: z.string().nullable().optional(),
})

export const REVIEW_STATUSES = ['pending', 'approved', 'rejected'] as const
export type ReviewStatus = (typeof REVIEW_STATUSES)[number]

export function reviewTone(status: string): 'success' | 'danger' | 'neutral' {
  if (status === 'approved') return 'success'
  if (status === 'rejected') return 'danger'
  return 'neutral'
}

/** Everything about a document a search term could plausibly mean. */
export function fileHaystack(file: {
  original_file_name: string
  file_extension: string
  description?: string | null
  review_status: string
  deid_status: string
}): string {
  return [
    file.original_file_name,
    file.file_extension,
    file.description ?? '',
    file.review_status,
    file.deid_status,
  ]
    .join(' ')
    .toLowerCase()
}

/** Nothing may be submitted while a document is still undecided. */
export function undecidedCount(files: Array<{ review_status: string }>): number {
  return files.filter((file) => file.review_status !== 'approved' &&
    file.review_status !== 'rejected').length
}

/**
 * How many documents were turned down.
 *
 * One is enough to stop the application being submitted: sending a
 * batch on for review with a document in it that has already been
 * rejected is asking the reviewer to find what was found here.
 */
export function rejectedCount(files: Array<{ review_status: string }>): number {
  return files.filter((file) => file.review_status === 'rejected').length
}

export type ApplicationFile = z.infer<typeof applicationFileSchema>

export const applicationFileListSchema = z.array(applicationFileSchema)

// ------------------------------------------------------------- tally

export type FileTally = {
  total: number
  /** Documents with a redacted copy on disk. */
  deidentified: number
  /** Queued or running right now. */
  deidRunning: number
  /** Tried and failed -- the ones that need somebody to look. */
  deidFailed: number
  /** Never attempted, and not running. */
  deidPending: number
  approved: number
  rejected: number
  undecided: number
}

/**
 * One pass over the documents for the counts the header shows.
 *
 * An application can hold a thousand files, at which point "is every one
 * of these redacted?" is not answerable by scrolling. The failed and
 * pending counts matter most: a single file that failed hours ago is
 * invisible in a list that long, and it is the one thing that stops the
 * batch being finished.
 */
export function fileTally(files: ApplicationFile[]): FileTally {
  const tally: FileTally = {
    total: files.length,
    deidentified: 0,
    deidRunning: 0,
    deidFailed: 0,
    deidPending: 0,
    approved: 0,
    rejected: 0,
    undecided: 0,
  }

  for (const file of files) {
    // is_deidentified, not deid_status: the question is whether a
    // redacted copy exists, and that flag is what says one does.
    if (file.is_deidentified) tally.deidentified += 1
    else if (isDeidInFlight(file.deid_status)) tally.deidRunning += 1
    else if (file.deid_status === 'failed') tally.deidFailed += 1
    else tally.deidPending += 1

    if (file.review_status === 'approved') tally.approved += 1
    else if (file.review_status === 'rejected') tally.rejected += 1
    else tally.undecided += 1
  }

  return tally
}

/** Every document redacted, with nothing still running or failed. */
export function isFullyDeidentified(tally: FileTally): boolean {
  return tally.total > 0 && tally.deidentified === tally.total
}

/** Every document decided, one way or the other. */
export function isFullyReviewed(tally: FileTally): boolean {
  return tally.total > 0 && tally.undecided === 0
}

/** Colour the de-identification state so progress is scannable. */
export function deidTone(
  status: string
): 'success' | 'warning' | 'danger' | 'neutral' {
  if (status === 'done') return 'success'
  if (isDeidInFlight(status)) return 'warning'
  if (status === 'failed') return 'danger'
  return 'neutral'
}

/** Human-readable size for the table. */
export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

// -------------------------------------------------------------- metadata

export const METADATA_STATUSES = ['ok', 'unsupported', 'failed'] as const
export type MetadataStatus = (typeof METADATA_STATUSES)[number]

/** The formats the API extracts metadata from (app/file_metadata.py). */
const METADATA_EXTENSIONS = new Set(['pdf', 'dcm', 'dicom', 'doc', 'docx'])

export function hasExtractableMetadata(extension: string): boolean {
  return METADATA_EXTENSIONS.has(extension.toLowerCase())
}

const DEIDENTIFIABLE_EXTENSIONS = new Set(['pdf', 'dcm', 'dicom', 'doc', 'docx'])

export function canDeidentify(extension: string): boolean {
  return DEIDENTIFIABLE_EXTENSIONS.has(extension.toLowerCase())
}

export const fileMetadataSchema = z.object({
  id: idSchema,
  file_id: idSchema,
  file_type: z.string(),
  metadata: z.record(z.string(), z.string()).default({}),
  // Permissive for the same reason as deid_status: the API owns it.
  status: z.string(),
  error: z.string().nullable().optional(),
  created_at: timestampSchema,
})

export type FileMetadata = z.infer<typeof fileMetadataSchema>

export function metadataTone(status: string): 'success' | 'danger' | 'neutral' {
  if (status === 'ok') return 'success'
  if (status === 'failed') return 'danger'
  return 'neutral'
}

// --------------------------------------------------------- bulk actions

export const bulkResultSchema = z.object({
  total: z.number(),
  changed: z.number(),
  skipped: z.number(),
  reasons: z.record(z.string(), z.number()).default({}),
})

export type BulkResult = z.infer<typeof bulkResultSchema>

/** 'Nothing to do', or what happened and what it left behind. */
export function bulkSummary(result: BulkResult, verb: string): string {
  if (result.total === 0) return 'There are no documents yet.'
  if (result.changed === 0) return `Nothing to ${verb}.`

  const done = `${result.changed} of ${result.total} ${verb === 'approve' ? 'approved' : 'queued'}`
  const why = Object.entries(result.reasons)
    .map(([reason, count]) => `${count} ${reason}`)
    .join(', ')

  return why ? `${done}; ${why}.` : `${done}.`
}

// -------------------------------------------------------------- previews

/**
 * How a format is shown. A PDF an <iframe> renders on its own; the other
 * two need the API to turn them into something a browser will display,
 * and anything else is only ever a download.
 */
export type PreviewKind = 'pdf' | 'image' | 'text' | 'download'

const IMAGE_EXTENSIONS = new Set(['dcm', 'dicom'])
const TEXT_EXTENSIONS = new Set(['doc', 'docx'])

export function previewKind(extension: string): PreviewKind {
  const value = (extension || '').toLowerCase()
  if (value === 'pdf') return 'pdf'
  if (IMAGE_EXTENSIONS.has(value)) return 'image'
  if (TEXT_EXTENSIONS.has(value)) return 'text'
  return 'download'
}

export const wordBlockSchema = z.object({
  kind: z.string(),
  style: z.string(),
  text: z.string(),
})

export const wordPreviewSchema = z.object({
  blocks: z.array(wordBlockSchema).default([]),
  tables: z.array(z.array(z.array(z.string()))).default([]),
  truncated: z.boolean().default(false),
})

export type WordPreview = z.infer<typeof wordPreviewSchema>

export type ImagePreview = { url: string; frames: number }

// ----------------------------------------------------------- upload jobs

export const uploadJobFileSchema = z.object({
  name: z.string(),
  status: z.string(),
  file_id: z.string().nullable().optional(),
  error: z.string().nullable().optional(),
})

export const uploadJobSchema = z.object({
  id: idSchema,
  application_id: idSchema,
  status: z.string(),
  total: z.number(),
  stored: z.number(),
  failed: z.number(),
  created_at: timestampSchema,
  finished_at: z.string().nullable().optional(),
  error: z.string().nullable().optional(),
  folder: z.string().nullable().optional(),
  files: z.array(uploadJobFileSchema).default([]),
})

export type UploadJob = z.infer<typeof uploadJobSchema>

/** Whether the batch is over, one way or another -- stop polling. */
export function isUploadJobSettled(job: UploadJob | undefined): boolean {
  return Boolean(job && ['done', 'partial', 'failed'].includes(job.status))
}

export function uploadJobTone(status: string): 'success' | 'warning' | 'danger' {
  if (status === 'done') return 'success'
  if (status === 'failed') return 'danger'
  return 'warning'
}

export function uploadJobSummary(job: UploadJob): string {
  if (job.status === 'failed') {
    return job.error
      ? `The upload failed: ${job.error}`
      : `None of the ${job.total} file${job.total === 1 ? '' : 's'} could be stored.`
  }
  if (job.status === 'partial') {
    return `${job.stored} of ${job.total} files stored; ${job.failed} failed.`
  }
  if (job.status === 'done') {
    return `${job.stored} file${job.stored === 1 ? '' : 's'} stored.`
  }
  return `Moving ${job.total} file${job.total === 1 ? '' : 's'} into storage…`
}
