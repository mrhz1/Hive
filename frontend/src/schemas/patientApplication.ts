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

  assigned_to_id: nullableText,

  assigned_to_username: nullableText,

  created_by_username: nullableText,
  submitted_by_username: nullableText,
  reviewed_by_username: nullableText,

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

const NON_REJECTABLE = ['submitted', 'deleted']

export function canReject(status: string): boolean {
  return !NON_REJECTABLE.includes(status)
}

export function isReadOnly(status: string | undefined): boolean {
  return status === 'submitted'
}

export function isDeleted(status: string): boolean {
  return status === 'deleted'
}

const UNDELETABLE = ['submitted', 'rejected', 'deleted']

export function canDelete(status: string): boolean {
  return !UNDELETABLE.includes(status)
}
