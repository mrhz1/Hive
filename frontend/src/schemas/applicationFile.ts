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

/** Nothing may be submitted while a document is still undecided. */
export function undecidedCount(files: Array<{ review_status: string }>): number {
  return files.filter((file) => file.review_status !== 'approved' &&
    file.review_status !== 'rejected').length
}

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
