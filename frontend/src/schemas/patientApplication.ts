import { z } from 'zod'
import { idSchema, timestampSchema } from './common'

export const APPLICATION_STATUSES = [
  'draft',
  'submitted',
  'approved',
  'rejected',
] as const
export type ApplicationStatus = (typeof APPLICATION_STATUSES)[number]

const nullableText = z.string().nullable().optional()
const nullableTimestamp = z.string().nullable().optional()

export const patientApplicationSchema = z.object({
  id: idSchema,
  patient_id: idSchema,
  submitted_by_id: nullableText,
  reviewed_by_id: nullableText,
  status: z.string(),
  description: nullableText,
  created_by_id: nullableText,
  updated_by_id: nullableText,
  submitted_at: nullableTimestamp,
  created_at: timestampSchema,
  updated_at: nullableTimestamp,
  reviewed_at: nullableTimestamp,
})

export type PatientApplication = z.infer<typeof patientApplicationSchema>

export const patientApplicationListSchema = z.array(patientApplicationSchema)

export function applicationTone(
  status: string
): 'neutral' | 'info' | 'success' | 'danger' {
  if (status === 'approved') return 'success'
  if (status === 'rejected') return 'danger'
  if (status === 'submitted') return 'info'
  return 'neutral'
}
