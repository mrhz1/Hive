import { z } from 'zod'
import { idSchema, timestampSchema } from './common'

export const rejectedFileSchema = z.object({
  id: idSchema,
  application_id: z.string(),
  patient_id: z.string(),
  original_file_name: z.string(),
  deidentified_file_name: z.string().nullable().optional(),
  file_extension: z.string(),
  file_size: z.number(),
  created_at: timestampSchema,
  deid_status: z.string(),
  review_note: z.string().nullable().optional(),
  has_original: z.boolean(),
  has_deidentified: z.boolean(),
})

export type RejectedFile = z.infer<typeof rejectedFileSchema>

export const rejectedFileListSchema = z.array(rejectedFileSchema)

export function rejectionSearchText(file: RejectedFile): string {
  const values = [
    file.original_file_name,
    file.deidentified_file_name,
    file.patient_id,
    file.review_note,
    file.file_extension,
  ]
  return values.filter(Boolean).join(' ').toLowerCase()
}
