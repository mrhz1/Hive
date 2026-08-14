import { z } from 'zod'
import { idSchema, timestampSchema } from './common'

export const APPLICATION_STATUSES = [
  'draft',
  'submitted',
  'approved',
  'rejected',
  'deleted',
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
  status_reason: nullableText,
  /** The user who has to work on it; upload notices go to them. */
  assigned_to_id: nullableText,
  /**
   * Resolved by the API rather than looked up here: reading it off the
   * users list would need `user:view`, and the point is that somebody
   * with only `application:view` can find their own work.
   */
  assigned_to_username: nullableText,
  /**
   * Where this application's documents came from. Per application, not
   * per patient: a second application for the same patient routinely
   * draws on a different folder.
   */
  original_file_path: nullableText,
})

export type PatientApplication = z.infer<typeof patientApplicationSchema>

export const patientApplicationListSchema = z.array(patientApplicationSchema)

export function applicationTone(
  status: string
): 'neutral' | 'info' | 'success' | 'danger' {
  if (status === 'approved') return 'success'
  if (status === 'rejected' || status === 'deleted') return 'danger'
  if (status === 'submitted') return 'info'
  return 'neutral'
}

const NON_REJECTABLE = ['submitted', 'rejected', 'deleted']

export function canReject(status: string): boolean {
  return !NON_REJECTABLE.includes(status)
}

/** A deleted application keeps its row but has nothing left to act on. */
export function isDeleted(status: string): boolean {
  return status === 'deleted'
}
