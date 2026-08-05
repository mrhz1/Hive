import { z } from 'zod'
import { idSchema, timestampSchema } from './common'

export const DEID_STATUSES = ['pending', 'processing', 'done', 'failed'] as const
export type DeidStatus = (typeof DEID_STATUSES)[number]

/** Mirrors app/schemas.py::PatientFile. */
export const patientFileSchema = z.object({
  id: idSchema,
  patient_id: idSchema,
  original_file_name: z.string(),
  sanitized_file_name: z.string(),
  deidentified_file_name: z.string().nullable().optional(),
  file_extension: z.string(),
  mime_type: z.string(),
  file_size: z.number(),
  // Kept permissive rather than a strict enum: the OCR job owns this
  // value, and an unknown status should render, not blow up the page.
  deid_status: z.string(),
  is_identified: z.boolean(),
  created_at: timestampSchema,
  description: z.string().nullable().optional(),
  file_path: z.string(),
  deidentified_file_path: z.string().nullable().optional(),
})

export type PatientFile = z.infer<typeof patientFileSchema>

export const patientFileListSchema = z.array(patientFileSchema)

/** Human-readable size for the table. */
export function formatFileSize(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}
