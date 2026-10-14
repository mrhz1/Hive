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

  checklist: z
    .object({
      passed: z.array(z.string()).optional(),
      failed: z.array(z.string()).optional(),
      by: z.string().optional(),
      at: z.string().optional(),
    })
    .nullable()
    .optional(),
})

export type PatientApplication = z.infer<typeof patientApplicationSchema>

export const ENROLLMENT_CHECKS = [
  { key: 'files_complete', label: 'All required files were submitted' },
  { key: 'eligible', label: 'The patient is eligible' },
  { key: 'consent', label: 'The right consent form is present' },
  { key: 'no_identifiers', label: 'No identifiers were found' },
] as const
export type EnrollmentCheck = (typeof ENROLLMENT_CHECKS)[number]['key']

export const CONSENT_CHECK: EnrollmentCheck = 'consent'

export function checkLabel(key: string): string {
  return ENROLLMENT_CHECKS.find((check) => check.key === key)?.label ?? key
}

export const patientApplicationListSchema = z.array(patientApplicationSchema)

export function applicationTone(
  status: string
): 'neutral' | 'info' | 'success' | 'danger' {
  if (status === 'approved') return 'success'
  if (status === 'rejected' || status === 'deleted') return 'danger'
  if (status === 'submitted') return 'info'
  return 'neutral'
}

const REJECTABLE = ['draft', 'approved', 'rejected']

export function canReject(status: string): boolean {
  return REJECTABLE.includes(status)
}

export function isReadOnly(status: string | undefined): boolean {
  return status === 'submitted' || status === 'deleted'
}

export function isDeleted(status: string): boolean {
  return status === 'deleted'
}

export function canDelete(status: string): boolean {
  return status === 'rejected'
}
