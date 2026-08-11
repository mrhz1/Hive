import { z } from 'zod'
import { idSchema, timestampSchema } from './common'

/**
 * Who *saw* what. The audit log records changes; this records reads,
 * downloads, exports and refusals -- the questions an incident asks.
 */
export const ACCESS_ACTIONS = [
  'read',
  'download',
  'export',
  'denied',
  'auth_failure',
  'integrity',
] as const

export type AccessAction = (typeof ACCESS_ACTIONS)[number]

const nullableText = z.string().nullable().optional()

export const accessLogSchema = z.object({
  id: idSchema,
  occurred_at: timestampSchema,
  action: z.string(),
  outcome: z.string(),
  actor_id: nullableText,
  actor_username: nullableText,
  actor_role: nullableText,
  source_ip: nullableText,
  user_agent: nullableText,
  request_id: nullableText,
  method: nullableText,
  path: nullableText,
  resource_type: nullableText,
  resource_id: nullableText,
  patient_id: nullableText,
  application_id: nullableText,
  /** Whether identified PHI left, as opposed to a redacted copy. */
  identified: z.boolean().nullable().optional(),
  record_count: z.number().nullable().optional(),
  byte_count: z.number().nullable().optional(),
  detail: nullableText,
})

export type AccessLog = z.infer<typeof accessLogSchema>

export const accessLogListSchema = z.array(accessLogSchema)

export type AccessLogFilters = {
  actor_username?: string
  patient_id?: string
  action?: string
  outcome?: string
  identified_only?: boolean
  /** YYYY-MM-DD, both inclusive. These select partitions, so bounding a
      query is what stops it reading every day ever recorded. */
  date_from?: string
  date_to?: string
  limit?: number
}

export function accessTone(
  action: string,
  outcome: string
): 'success' | 'info' | 'warning' | 'danger' | 'neutral' {
  if (outcome === 'denied') return 'warning'
  if (outcome === 'failure') return 'danger'
  if (action === 'export') return 'danger'
  if (action === 'download') return 'info'
  return 'neutral'
}

/** What the row did, in words, for people who do not read event names. */
export function accessSummary(entry: AccessLog): string {
  const what = entry.resource_type ?? 'record'
  if (entry.action === 'export') {
    return `Exported ${entry.record_count ?? 0} ${what} rows`
  }
  if (entry.action === 'download') return `Downloaded a ${what}`
  if (entry.action === 'denied') return `Refused: needs ${entry.resource_id}`
  if (entry.action === 'auth_failure') return entry.detail ?? 'Sign-in refused'
  if (entry.action === 'integrity') return entry.detail ?? 'Integrity check failed'
  return `Viewed a ${what}`
}
