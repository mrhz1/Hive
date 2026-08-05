import { z } from 'zod'
import { idSchema, timestampSchema } from './common'

/**
 * Mirrors app/schemas.py::PatientApplication.
 *
 * An application is the workflow wrapper around a patient record: who
 * submitted it, who reviewed it, and where it is in the process. The
 * clinical facts live on the patient; this holds the provenance.
 */
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
  // Permissive rather than a strict enum, for the same reason as
  // deid_status: an unknown status should render, not blow up the page.
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

/**
 * The tone each status carries in a badge. Kept beside the statuses so a
 * new one cannot be added without deciding how it reads.
 */
export function applicationTone(
  status: string
): 'neutral' | 'info' | 'success' | 'danger' {
  if (status === 'approved') return 'success'
  if (status === 'rejected') return 'danger'
  if (status === 'submitted') return 'info'
  return 'neutral'
}
