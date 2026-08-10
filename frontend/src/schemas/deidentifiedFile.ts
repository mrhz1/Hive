import { z } from 'zod'
import { idSchema, timestampSchema } from './common'

export const deidentifiedFileSchema = z.object({
  id: idSchema,
  application_id: idSchema,
  patient_id: z.string(),
  name: z.string(),
  original_file_name: z.string(),
  file_type: z.string(),
  file_size: z.number(),
  created_at: timestampSchema,
  deid_status: z.string(),
  de_identified_file_path: z.string().nullable().optional(),
})

export type DeidentifiedFile = z.infer<typeof deidentifiedFileSchema>

export const deidentifiedFileListSchema = z.array(deidentifiedFileSchema)

/** Everything a row can be searched by, lowercased once per row. */
export function fileHaystack(file: DeidentifiedFile): string {
  return [file.name, file.original_file_name, file.patient_id, file.file_type]
    .filter(Boolean)
    .join(' ')
    .toLowerCase()
}
