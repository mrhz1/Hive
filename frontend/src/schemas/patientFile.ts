import { z } from 'zod'
import { idSchema, timestampSchema } from './common'

export const DEID_STATUSES = ['pending', 'processing', 'done', 'failed'] as const
export type DeidStatus = (typeof DEID_STATUSES)[number]

/**
 * The reviewer's decision, tracked separately from deid_status: "the OCR
 * job finished" and "a person accepted the result" are different facts,
 * and a file can be de-identified and still rejected.
 */
export const REVIEW_STATUSES = ['pending', 'approved', 'rejected'] as const
export type ReviewStatus = (typeof REVIEW_STATUSES)[number]

/** Mirrors app/schemas.py::PatientFile. */
export const patientFileSchema = z.object({
  id: idSchema,
  patient_id: idSchema,
  original_file_name: z.string(),
  sanitized_file_name: z.string(),
  de_identified_file_name: z.string().nullable().optional(),
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

  // Reviewer decision. Permissive for the same reason as deid_status.
  review_status: z.string(),
  review_description: z.string().nullable().optional(),
  reviewed_by_id: z.string().nullable().optional(),
  reviewed_at: z.string().nullable().optional(),
})

export type PatientFile = z.infer<typeof patientFileSchema>

export const patientFileListSchema = z.array(patientFileSchema)

/** Colour the de-identification state so progress is scannable. */
export function deidTone(
  status: string
): 'success' | 'warning' | 'danger' | 'neutral' {
  if (status === 'done') return 'success'
  if (status === 'processing') return 'warning'
  if (status === 'failed') return 'danger'
  return 'neutral'
}

export function reviewTone(status: string): 'success' | 'danger' | 'neutral' {
  if (status === 'approved') return 'success'
  if (status === 'rejected') return 'danger'
  return 'neutral'
}

/** Human-readable size for the table. */
export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}
