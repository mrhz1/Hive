import { z } from 'zod'
import { idSchema, timestampSchema } from './common'

/**
 * Mirrors app/schemas.py::DEID_STATUSES.
 *
 * 'pending' is the state every file is uploaded in -- nobody has asked
 * for it yet. 'queued' means somebody pressed the button and a Cloudera
 * AI Job run has been requested but has not claimed the row. Both count
 * as "in flight" for the UI only from 'queued' onwards, which is why
 * isDeidInFlight exists rather than an inline status comparison.
 */
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

/**
 * Mirrors app/schemas.py::PatientApplicationFile.
 *
 * Documents belong to an application, not to a patient directly -- a
 * patient's files are reached through their applications.
 *
 * Note the two spellings of the redacted-copy fields:
 * `deidentified_file_name` against `de_identified_file_path`. That is
 * what the Cloudera metastore has, and the API passes it through
 * unchanged rather than translating.
 *
 * There is no review_status here: a reviewer's verdict is recorded once,
 * on the application row.
 */
export const applicationFileSchema = z.object({
  id: idSchema,
  application_id: idSchema,
  original_file_name: z.string(),
  sanitized_file_name: z.string(),
  deidentified_file_name: z.string().nullable().optional(),
  file_extension: z.string(),
  mime_type: z.string(),
  file_size: z.number(),
  // Kept permissive rather than a strict enum: the OCR job owns this
  // value, and an unknown status should render, not blow up the page.
  deid_status: z.string(),
  is_deidentified: z.boolean(),
  created_at: timestampSchema,
  description: z.string().nullable().optional(),
  file_path: z.string(),
  de_identified_file_path: z.string().nullable().optional(),
})

export type ApplicationFile = z.infer<typeof applicationFileSchema>

export const applicationFileListSchema = z.array(applicationFileSchema)

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

/**
 * Mirrors app/schemas.py::METADATA_STATUSES. Three different answers,
 * kept apart because "this file has no metadata" and "we could not read
 * it" and "we do not parse this format" mean different things to whoever
 * is looking at the document.
 */
export const METADATA_STATUSES = ['ok', 'unsupported', 'failed'] as const
export type MetadataStatus = (typeof METADATA_STATUSES)[number]

/** The formats the API extracts metadata from (app/file_metadata.py). */
const METADATA_EXTENSIONS = new Set(['pdf', 'dcm', 'dicom', 'doc', 'docx'])

/**
 * Whether asking for metadata could return anything useful.
 *
 * Used to disable the button rather than hide it: a greyed-out control
 * says "not for this format", a missing one says nothing at all.
 */
export function hasExtractableMetadata(extension: string): boolean {
  return METADATA_EXTENSIONS.has(extension.toLowerCase())
}

/**
 * Mirrors app/schemas.py::FileMetadata.
 *
 * `metadata` is deliberately an open record of strings: a DICOM study
 * and a Word document share almost no fields, and the API normalises
 * every value to a string precisely so the client does not have to
 * handle three types per field.
 */
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
